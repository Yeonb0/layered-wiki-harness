import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from agent.b1 import run_b1_doc
from agent.layer_block import load_layer_block
from agent.llm_client import LLM_ENDPOINT_ENV, GenerationConfig, chat
from agent.placement import MODES
from agent.propose import run_propose_doc
from agent.types import SourceDoc, SourceSegment
from labeling.gold import read_ids, read_jsonl, read_owners
from retrieval.embeddings import EMBED_MAX_CHARS, EMBED_TIMEOUT_SECONDS, EMBEDDING_ENDPOINT_ENV
from retrieval.search import EXCERPT_LENGTH, LAYER_ORDER, Retriever
from runner.conditions import Condition, ConditionCell, build_interleaved_schedule
from runner.types import InputDoc

# 사용자 결정 2026-10-15 : temperature 0.0 과 thinking 끔은 전 조건 공통 상수다 - 인자로 받지 않는다
TEMPERATURE = 0.0
ENABLE_THINKING = False

# 구현한 조건만 받는다 - B0 · B2 같은 미구현 조건을 조용히 넘기지 않는다
IMPLEMENTED_CONDITIONS = ("제안", "B1")

# 셀 폴더 이름은 ascii 만 쓴다 - 조건 이름의 한글이 파일 시스템에 따라 깨지는 것을 막는다
_CONDITION_FOLDER = {"제안": "propose", "B1": "b1"}

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WORK_ROOT = os.path.expanduser("~/layered-wiki-work")


def cell_name(condition: str, mode: str) -> str:
  return f"{_CONDITION_FOLDER[condition]}_{mode}"


def git_head_commit(repo_dir: str) -> str:
  # 미추적 .py 도 import 되면 실행 코드라 HEAD 해시가 실제 코드를 가리키지 않는다 - 미추적 파일도 막는다
  Dirty = subprocess.run(
    ["git", "-C", repo_dir, "status", "--porcelain"], capture_output=True, text=True, check=True
  ).stdout.strip()
  if Dirty:
    raise ValueError(f"커밋 안 된 변경 또는 미추적 파일이 있다: {Dirty.splitlines()}")
  return subprocess.run(["git", "-C", repo_dir, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def _sha256_file(path: str) -> str:
  with open(path, "rb") as File:
    return hashlib.sha256(File.read()).hexdigest()


def _excluded_ids(selection_path: str) -> set:
  with open(selection_path, encoding="utf-8") as File:
    Obj = json.load(File)
  Ids = Obj.get("excluded_pages", {}).get("ids") if isinstance(Obj, dict) else None
  # 제외 목록을 못 읽으면 제외 대상이 조용히 투입된다
  if not isinstance(Ids, list) or not all(isinstance(I, str) for I in Ids):
    raise ValueError("selection 파일에 excluded_pages.ids ( 문자열 목록 ) 가 없다")
  return set(Ids)


def load_source_docs(segments_path: str, docs_path: str, doc_ids_path: str, split_doc_ids_path: str, selection_path: str):
  Ids = read_ids(doc_ids_path)
  # 투입할 문서가 없으면 실행이 의미가 없다
  if not Ids:
    raise ValueError("투입 문서 id 목록이 비어 있다")
  # 같은 문서를 두 번 투입하면 볼트에 같은 노트가 두 번 쌓인다
  if len(set(Ids)) != len(Ids):
    raise ValueError("투입 문서 id 목록에 중복이 있다")
  SplitIds = set(read_ids(split_doc_ids_path))
  # 분할 파일 밖 문서는 파일럿 · 본실험 구분이 깨진다
  NotInSplit = [I for I in Ids if I not in SplitIds]
  if NotInSplit:
    raise ValueError(f"split 파일에 없는 문서 id: {NotInSplit}")
  # 선택 단계에서 제외한 페이지는 투입 대상이 아니다
  ExcludedPages = _excluded_ids(selection_path)
  Excluded = [I for I in Ids if I in ExcludedPages]
  if Excluded:
    raise ValueError(f"selection 에서 제외된 문서 id: {Excluded}")

  Wanted = set(Ids)
  DocsById = {}
  for Row in read_jsonl(docs_path):
    # docs.jsonl 에 같은 id 가 두 번 있으면 메타데이터가 모호하다
    if Row.get("doc_id") in DocsById:
      raise ValueError(f"docs.jsonl 에 doc_id 중복: {Row.get('doc_id')}")
    DocsById[Row.get("doc_id")] = Row
  SegsById = {}
  for Row in read_jsonl(segments_path):
    if Row.get("doc_id") in Wanted:
      SegsById.setdefault(Row["doc_id"], []).append(Row)

  Docs = []
  RawSha = {}
  for DocId in Ids:
    Meta = DocsById.get(DocId)
    # 메타데이터가 없으면 층 · 그룹 · 제목을 확인할 수 없다
    if Meta is None:
      raise ValueError(f"docs.jsonl 에 없는 문서: {DocId}")
    for Key in ("title", "layer", "group", "raw_sha256"):
      if Key not in Meta:
        raise ValueError(f"docs.jsonl 행에 {Key} 가 없다: {DocId}")
    # 제목이 문자열이 아니면 프롬프트와 검색 질의가 깨진다
    if not isinstance(Meta["title"], str):
      raise ValueError(f"title 이 문자열이 아니다: {DocId}")
    # 출처 층이 층 순서에 없으면 이후 층 규칙을 적용할 수 없다
    if Meta["layer"] not in LAYER_ORDER:
      raise ValueError(f"알 수 없는 layer: {Meta['layer']!r} ( {DocId} )")
    Segs = SegsById.get(DocId, [])
    # 세그먼트가 없으면 분해할 입력이 없다
    if not Segs:
      raise ValueError(f"세그먼트가 0개인 문서: {DocId}")
    for Seg in Segs:
      for Key in ("segment_id", "seq", "layer", "group", "text"):
        if Key not in Seg:
          raise ValueError(f"segments.jsonl 행에 {Key} 가 없다: {DocId}")
      # seq 는 정렬 기준이라 정수여야 하고 text 는 원문 문자열이어야 한다
      if not isinstance(Seg["seq"], int) or isinstance(Seg["seq"], bool) or not isinstance(Seg["text"], str):
        raise ValueError(f"세그먼트의 seq 나 text 형식이 잘못됐다: {Seg['segment_id']}")
    Pairs = {(Seg["layer"], Seg["group"]) for Seg in Segs}
    # 한 문서의 세그먼트는 같은 출처 층 · 그룹이어야 한다
    if len(Pairs) != 1:
      raise ValueError(f"한 문서 세그먼트의 layer · group 이 서로 다르다: {DocId}")
    # 세그먼트와 docs.jsonl 이 다르면 어느 쪽이 맞는지 알 수 없다
    if next(iter(Pairs)) != (Meta["layer"], Meta["group"]):
      raise ValueError(f"세그먼트의 layer · group 이 docs.jsonl 과 다르다: {DocId}")
    Docs.append(SourceDoc(
      doc_id=DocId,
      title=Meta["title"],
      source_layer=Meta["layer"],
      source_group=Meta["group"],
      segments=[SourceSegment(segment_id=S["segment_id"], seq=S["seq"], text=S["text"]) for S in Segs],
    ))
    RawSha[DocId] = Meta["raw_sha256"]
  return Docs, RawSha


def _positive_int(Value, name: str) -> None:
  # bool 은 int 의 하위 형이라 따로 거른다
  if not isinstance(Value, int) or isinstance(Value, bool) or Value <= 0:
    raise ValueError(f"{name} 는 양의 정수여야 한다: {Value!r}")


def _validate_cells(conditions: list, modes: list) -> None:
  # 조건 · 모드가 비면 실행할 셀이 없다
  if not conditions or not modes:
    raise ValueError("conditions 와 modes 는 비어 있으면 안 된다")
  # 같은 조건 · 모드를 두 번 받으면 셀 폴더가 겹친다
  if len(set(conditions)) != len(conditions) or len(set(modes)) != len(modes):
    raise ValueError("conditions 나 modes 에 중복이 있다")
  for Condition_ in conditions:
    if Condition_ not in IMPLEMENTED_CONDITIONS:
      raise ValueError(f"구현하지 않은 조건: {Condition_!r} ( 구현: {list(IMPLEMENTED_CONDITIONS)} )")
  for Mode in modes:
    if Mode not in MODES:
      raise ValueError(f"알 수 없는 mode: {Mode!r}")


def _validate_max_tokens(conditions: list, decompose_max_tokens, place_max_tokens, b1_max_tokens) -> None:
  # 실행 셀에 필요한 max_tokens 만 요구한다 - 기본값을 넣으면 조건 간 상한이 조용히 달라진다
  if "제안" in conditions:
    _positive_int(decompose_max_tokens, "decompose_max_tokens")
    _positive_int(place_max_tokens, "place_max_tokens")
  if "B1" in conditions:
    _positive_int(b1_max_tokens, "b1_max_tokens")


def _validate_out_dir(out_dir: str, work_root: str) -> str:
  Root = os.path.realpath(work_root)
  Target = os.path.realpath(out_dir)
  # 작업 루트 밖에 쓰면 저장소나 코퍼스 폴더를 건드릴 수 있다
  if os.path.commonpath([Root, Target]) != Root or Target == Root:
    raise ValueError(f"out_dir 는 작업 루트({Root}) 아래여야 한다: {out_dir}")
  # 이미 있는 폴더는 볼트가 비어 있다는 보장이 없다
  if os.path.exists(Target):
    raise ValueError(f"out_dir 가 이미 있다: {Target}")
  return Target


def _append_jsonl(path: str, rows: list) -> None:
  with open(path, "a", encoding="utf-8") as File:
    for Row in rows:
      File.write(json.dumps(Row, ensure_ascii=False) + "\n")


def _utc_now() -> str:
  return datetime.now(timezone.utc).isoformat()


def run_v2(
  *,
  segments_path,
  docs_path,
  doc_ids_path,
  split_doc_ids_path,
  selection_path,
  source_layers_path,
  criteria_path,
  criteria_sha256,
  conditions,
  modes,
  k,
  gen_seed,
  order_seed,
  decompose_max_tokens,
  place_max_tokens,
  b1_max_tokens,
  model_id,
  timeout_seconds,
  snapshot,
  run_kind,
  out_dir,
  chat_fn,
  embed_backend,
  commit_fn,
  work_root,
  print_fn,
) -> dict:
  _validate_cells(conditions, modes)
  _validate_max_tokens(conditions, decompose_max_tokens, place_max_tokens, b1_max_tokens)
  _positive_int(k, "k")
  for Name, Value in (("gen_seed", gen_seed), ("order_seed", order_seed), ("snapshot", snapshot)):
    # 시드와 스냅샷 번호는 재현 기록이라 정수여야 한다
    if not isinstance(Value, int) or isinstance(Value, bool):
      raise ValueError(f"{Name} 는 정수여야 한다: {Value!r}")
  # 제한 시간이 0 이하면 호출이 바로 실패한다
  if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
    raise ValueError(f"timeout_seconds 는 양수여야 한다: {timeout_seconds!r}")
  for Name, Value in (("model_id", model_id), ("run_kind", run_kind)):
    # 로그 항목에 들어갈 식별 문자열이 비면 결과를 구분할 수 없다
    if not isinstance(Value, str) or not Value:
      raise ValueError(f"{Name} 는 비어 있지 않은 문자열이어야 한다")
  OutPath = _validate_out_dir(out_dir, work_root)

  Docs, RawSha = load_source_docs(segments_path, docs_path, doc_ids_path, split_doc_ids_path, selection_path)
  Owners = read_owners(source_layers_path)
  Block, BlockSha = load_layer_block(criteria_path, criteria_sha256)
  HarnessCommit = commit_fn()

  # 일정은 문서 객체가 아니라 id 와 제목만으로 만든다 - 순서를 만드는 데 본문은 필요 없다
  Cells = [ConditionCell(condition=Condition(C), mode=M, k=k) for C in conditions for M in modes]
  Schedule = build_interleaved_schedule([InputDoc(id=D.doc_id, title=D.title, body="") for D in Docs], Cells, order_seed)
  DocById = {D.doc_id: D for D in Docs}
  DocOrder = []
  for ScheduleDoc, _ in Schedule:
    if ScheduleDoc.id not in DocOrder:
      DocOrder.append(ScheduleDoc.id)
  CellOrderPerDoc = {}
  for ScheduleDoc, ScheduleCell in Schedule:
    CellOrderPerDoc.setdefault(ScheduleDoc.id, []).append(cell_name(ScheduleCell.condition.value, ScheduleCell.mode))

  TrialId = str(uuid.uuid4())
  # 셀마다 빈 볼트 · 새 Retriever · 새 LayerGroupById 를 따로 가진다 - 셀 간 볼트 공유 금지
  States = {}
  os.makedirs(OutPath)
  for Cell in Cells:
    Name = cell_name(Cell.condition.value, Cell.mode)
    CellDir = os.path.join(OutPath, Name)
    os.makedirs(CellDir)
    for FileName in ("log.jsonl", "vault.jsonl"):
      open(os.path.join(CellDir, FileName), "x").close()
    States[Name] = {
      "dir": CellDir,
      "vault_notes": [],
      "retriever": Retriever(embed_backend=embed_backend),
      "layer_group_by_id": {},
      "written": 0,
    }

  Manifest = {
    "trial_id": TrialId,
    "args": {
      "segments": segments_path, "docs": docs_path, "doc_ids": doc_ids_path, "split_doc_ids": split_doc_ids_path,
      "selection": selection_path, "source_layers": source_layers_path, "criteria": criteria_path,
      "criteria_sha256": criteria_sha256, "conditions": list(conditions), "modes": list(modes), "k": k,
      "gen_seed": gen_seed, "order_seed": order_seed, "decompose_max_tokens": decompose_max_tokens,
      "place_max_tokens": place_max_tokens, "b1_max_tokens": b1_max_tokens, "model_id": model_id,
      "timeout_seconds": timeout_seconds, "snapshot": snapshot, "run_kind": run_kind, "out_dir": OutPath,
    },
    "schedule": {
      "doc_order": DocOrder,
      "cell_order_per_doc": CellOrderPerDoc,
      "entries": [
        {"schedule_index": Index, "doc_id": D.id, "cell": cell_name(C.condition.value, C.mode)}
        for Index, (D, C) in enumerate(Schedule)
      ],
    },
    "harness_commit": HarnessCommit,
    "input_sha256": {
      "segments": _sha256_file(segments_path), "docs": _sha256_file(docs_path), "doc_ids": _sha256_file(doc_ids_path),
      "split_doc_ids": _sha256_file(split_doc_ids_path), "selection": _sha256_file(selection_path),
      "source_layers": _sha256_file(source_layers_path), "criteria": _sha256_file(criteria_path),
    },
    "layer_block_sha256": BlockSha,
    "model_id": model_id,
    # 서버 주소는 환경 변수로만 받으므로 어느 서버로 돌렸는지 기록에 남긴다
    "endpoints": {LLM_ENDPOINT_ENV: os.environ.get(LLM_ENDPOINT_ENV), EMBEDDING_ENDPOINT_ENV: os.environ.get(EMBEDDING_ENDPOINT_ENV)},
    "embed_max_chars": EMBED_MAX_CHARS,
    "embed_timeout_seconds": EMBED_TIMEOUT_SECONDS,
    "excerpt_length": EXCERPT_LENGTH,
    # 해시 시드는 강제하지 않고 실제 값만 남긴다 - 없으면 null
    "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
    "python_version": platform.python_version(),
    "started_at_utc": _utc_now(),
    "ended_at_utc": None,
    "status": None,
    "error": None,
  }

  def write_manifest() -> None:
    with open(os.path.join(OutPath, "manifest.json"), "w", encoding="utf-8") as File:
      json.dump(Manifest, File, ensure_ascii=False, indent=2)

  # 강제 종료돼도 trial_id · 일정 · 해시가 남도록 실행 전에 한 번 쓴다
  Manifest["status"] = "running"
  write_manifest()

  try:
    for ScheduleIndex, (ScheduleDoc, Cell) in enumerate(Schedule):
      Condition_ = Cell.condition.value
      Name = cell_name(Condition_, Cell.mode)
      State = States[Name]
      Doc = DocById[ScheduleDoc.id]
      # 사용하지 않는 max_tokens 는 null 로 남겨 셀이 어떤 상한으로 돌았는지 로그만 보고 알 수 있게 한다
      BaseLog = {
        "trial_id": TrialId,
        "run_kind": run_kind,
        "snapshot": snapshot,
        "harness_commit": HarnessCommit,
        "model_id": model_id,
        "criteria_sha256": criteria_sha256,
        "condition": Condition_,
        "mode": Cell.mode,
        "k": k,
        "gen_seed": gen_seed,
        "order_seed": order_seed,
        "decompose_max_tokens": decompose_max_tokens if Condition_ == "제안" else None,
        "place_max_tokens": place_max_tokens if Condition_ == "제안" else None,
        "b1_max_tokens": b1_max_tokens if Condition_ == "B1" else None,
        "doc_order_index": DocOrder.index(Doc.doc_id),
        "schedule_index": ScheduleIndex,
        "raw_sha256": RawSha[Doc.doc_id],
      }
      Started = time.monotonic()
      if Condition_ == "제안":
        Log = run_propose_doc(
          Doc, Cell.mode, k, State["retriever"], State["vault_notes"], State["layer_group_by_id"], chat_fn, model_id,
          GenerationConfig(temperature=TEMPERATURE, seed=gen_seed, max_tokens=decompose_max_tokens, enable_thinking=ENABLE_THINKING),
          GenerationConfig(temperature=TEMPERATURE, seed=gen_seed, max_tokens=place_max_tokens, enable_thinking=ENABLE_THINKING),
          Block, BlockSha, Owners, timeout_seconds, BaseLog,
        )
      else:
        Log = run_b1_doc(
          Doc, Cell.mode, k, State["retriever"], State["vault_notes"], State["layer_group_by_id"], chat_fn, model_id,
          GenerationConfig(temperature=TEMPERATURE, seed=gen_seed, max_tokens=b1_max_tokens, enable_thinking=ENABLE_THINKING),
          Block, BlockSha, Owners, timeout_seconds, BaseLog,
        )
      Elapsed = time.monotonic() - Started
      # 문서 하나가 끝날 때마다 덧붙인다 - 중간에 멈춰도 그 앞까지의 기록이 남는다
      _append_jsonl(os.path.join(State["dir"], "log.jsonl"), Log)
      NewNotes = State["vault_notes"][State["written"]:]
      _append_jsonl(os.path.join(State["dir"], "vault.jsonl"), [asdict(Note) for Note in NewNotes])
      State["written"] = len(State["vault_notes"])
      # 화면에는 숫자와 식별자만 찍는다 - 제목 · 본문 · raw_text · rationale 은 찍지 않는다
      print_fn(
        f"{ScheduleIndex} {Name} {Doc.doc_id} entries={len(Log)} ok={sum(1 for E in Log if E['ok'])} elapsed_s={Elapsed:.1f}"
      )
  except BaseException as Error:
    # 예외를 삼키지 않는다 - 중단 사실과 사유를 manifest 에 남기고 그대로 다시 올린다
    Manifest["status"] = "aborted"
    Manifest["error"] = {"type": type(Error).__name__, "message": str(Error)}
    Manifest["ended_at_utc"] = _utc_now()
    write_manifest()
    raise
  Manifest["status"] = "completed"
  Manifest["ended_at_utc"] = _utc_now()
  write_manifest()
  return Manifest


def parse_args(argv=None) -> argparse.Namespace:
  Parser = argparse.ArgumentParser(description="v2 순차 실행기 ( 제안 · B1 조건 )")
  # 아래 인자는 기본값이 없다 - 빠뜨리면 실행 조건이 조용히 달라진다
  Parser.add_argument("--segments", required=True)
  Parser.add_argument("--docs", required=True)
  Parser.add_argument("--doc-ids", required=True)
  Parser.add_argument("--split-doc-ids", required=True)
  Parser.add_argument("--selection", required=True)
  Parser.add_argument("--source-layers", required=True)
  Parser.add_argument("--criteria", required=True)
  Parser.add_argument("--criteria-sha256", required=True)
  Parser.add_argument("--conditions", required=True, nargs="+")
  Parser.add_argument("--modes", required=True, nargs="+")
  Parser.add_argument("--k", required=True, type=int)
  Parser.add_argument("--gen-seed", required=True, type=int)
  Parser.add_argument("--order-seed", required=True, type=int)
  # max_tokens 는 실행 셀에 필요한 것만 run_v2 가 요구한다
  Parser.add_argument("--decompose-max-tokens", type=int)
  Parser.add_argument("--place-max-tokens", type=int)
  Parser.add_argument("--b1-max-tokens", type=int)
  Parser.add_argument("--model-id", required=True)
  Parser.add_argument("--timeout-seconds", required=True, type=float)
  Parser.add_argument("--snapshot", required=True, type=int)
  Parser.add_argument("--run-kind", required=True)
  Parser.add_argument("--out-dir", required=True)
  return Parser.parse_args(argv)


def _print_flush(Line: str) -> None:
  # tee 로 파이프할 때 끝날 때까지 화면이 비는 것을 막으려고 출력마다 flush 한다
  print(Line, flush=True)


def main(argv=None) -> None:
  Args = parse_args(argv)
  run_v2(
    segments_path=Args.segments,
    docs_path=Args.docs,
    doc_ids_path=Args.doc_ids,
    split_doc_ids_path=Args.split_doc_ids,
    selection_path=Args.selection,
    source_layers_path=Args.source_layers,
    criteria_path=Args.criteria,
    criteria_sha256=Args.criteria_sha256,
    conditions=Args.conditions,
    modes=Args.modes,
    k=Args.k,
    gen_seed=Args.gen_seed,
    order_seed=Args.order_seed,
    decompose_max_tokens=Args.decompose_max_tokens,
    place_max_tokens=Args.place_max_tokens,
    b1_max_tokens=Args.b1_max_tokens,
    model_id=Args.model_id,
    timeout_seconds=Args.timeout_seconds,
    snapshot=Args.snapshot,
    run_kind=Args.run_kind,
    out_dir=Args.out_dir,
    # 실제 chat · 임베딩 연결은 CLI 에서만 한다 - 임베딩은 백엔드를 주입하지 않으면 서버 호출 경로를 쓴다
    chat_fn=chat,
    embed_backend=None,
    commit_fn=lambda: git_head_commit(REPO_DIR),
    work_root=DEFAULT_WORK_ROOT,
    print_fn=_print_flush,
  )


if __name__ == "__main__":
  main()
