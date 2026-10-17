import argparse
import json
import os
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent.layer_block import load_layer_block
from agent.llm_client import GenerationConfig, chat
from agent.placement import MODES
from agent.propose import _to_document_record, run_propose_doc
from agent.types import DownwardLink, NoteRecord
from labeling.gold import read_owners
from retrieval.search import Retriever
from runner.v2_sequential import (
  DEFAULT_WORK_ROOT,
  ENABLE_THINKING,
  REPO_DIR,
  TEMPERATURE,
  _validate_out_dir,
  git_head_commit,
  load_source_docs,
)

# 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 시연은 제안 조건 실행의 설정을 그대로 쓰므로 실행 manifest 의 args 에서 읽을 키를 고정한다
_REQUIRED_ARGS = (
  "segments", "docs", "doc_ids", "split_doc_ids", "selection", "source_layers", "criteria", "criteria_sha256",
  "conditions", "modes", "k", "gen_seed", "decompose_max_tokens", "place_max_tokens", "model_id", "timeout_seconds",
)
# 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 실행 기록과 구분하려고 요청 산출물은 작업 루트 아래 별도 폴더에 둔다
REQUEST_SUBDIR = "demo_api"
# 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 로그의 run_kind 로 시연 요청과 실험 실행을 가른다
RUN_KIND = "demo_api"
# 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 이 앞단은 제안 조건만 다룬다
CONDITION = "제안"
# 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 시작 때 노트를 임베딩하는 동안 화면이 멈춘 것처럼 보이지 않게 이 개수마다 진행 수를 찍는다
PROGRESS_EVERY = 10
# 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 요청 본문이 크면 메모리를 먹으므로 상한을 둔다
MAX_BODY_BYTES = 4096


def _utc_now() -> str:
  return datetime.now(timezone.utc).isoformat()


def _read_json(path: str):
  with open(path, encoding="utf-8") as File:
    return json.load(File)


def _restore_note(Row: dict) -> NoteRecord:
  try:
    Links = [DownwardLink(**Link) for Link in Row["downward_conditional_links"]]
    return NoteRecord(**{**Row, "downward_conditional_links": Links})
  except (KeyError, TypeError) as Error:
    # 필드가 다른 볼트 행은 어느 버전의 실행인지 알 수 없다
    raise ValueError(f"vault.jsonl 행을 NoteRecord 로 복원할 수 없다: {Error}") from Error


def _read_vault_notes(path: str) -> list[NoteRecord]:
  with open(path, encoding="utf-8") as File:
    return [_restore_note(json.loads(Line)) for Line in File if Line.strip()]


def owner_labels(Owners: set) -> dict:
  # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 정렬한 주인 목록 순서로 가려서 화면에 실제 이름이 나가지 않게 한다
  Sorted = sorted(Owners)
  return {Name: "주인" + (chr(ord("A") + Index) if Index < 26 else str(Index + 1)) for Index, Name in enumerate(Sorted)}


def group_label(Layer: str, Group, Labels: dict):
  if Layer == "개인":
    # 목록에 없는 개인 그룹은 가릴 이름이 없어 그대로 내보내게 되므로 막는다
    if Group not in Labels:
      raise ValueError("개인 그룹이 주인 목록에 없다")
    return Labels[Group]
  return Group


class DemoApp:
  def __init__(self, run_dir, chat_fn, embed_backend, commit_fn, work_root, print_fn) -> None:
    self.chat_fn = chat_fn
    self.print_fn = print_fn
    self.work_root = work_root
    self.base_run = os.path.basename(os.path.normpath(run_dir))
    Manifest = _read_json(os.path.join(run_dir, "manifest.json"))
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 끝나지 않은 실행의 볼트는 일부 문서만 담고 있어 기본 볼트가 될 수 없다
    if Manifest.get("status") != "completed":
      raise ValueError(f"완료된 실행이 아니다: status={Manifest.get('status')!r}")
    Args = Manifest.get("args")
    if not isinstance(Args, dict):
      raise ValueError("manifest 에 args 가 없다")
    Missing = [Key for Key in _REQUIRED_ARGS if Key not in Args]
    if Missing:
      raise ValueError(f"manifest args 에 없는 키: {Missing}")
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 제안 조건이 아닌 실행의 볼트는 이 앞단의 호출 경로와 맞지 않는다
    if Args["conditions"] != [CONDITION]:
      raise ValueError(f"제안 조건만 있는 실행이어야 한다: conditions={Args['conditions']!r}")
    self.manifest = Manifest
    self.k = Args["k"]
    self.gen_seed = Args["gen_seed"]
    self.decompose_max_tokens = Args["decompose_max_tokens"]
    self.place_max_tokens = Args["place_max_tokens"]
    self.model_id = Args["model_id"]
    self.timeout_seconds = Args["timeout_seconds"]

    Docs, self.raw_sha = load_source_docs(
      Args["segments"], Args["docs"], Args["doc_ids"], Args["split_doc_ids"], Args["selection"]
    )
    DocById = {Doc.doc_id: Doc for Doc in Docs}
    DocOrder = Manifest["schedule"]["doc_order"]
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 실행에 들어간 문서만 받아야 기본 볼트와 문서 목록이 어긋나지 않는다
    NotLoaded = [Id for Id in DocOrder if Id not in DocById]
    if NotLoaded:
      raise ValueError(f"manifest 의 doc_order 에 있으나 적재되지 않은 문서: {NotLoaded}")
    self.docs = {Id: DocById[Id] for Id in DocOrder}
    self.owners = read_owners(Args["source_layers"])
    self.labels = owner_labels(self.owners)
    self.block, self.block_sha = load_layer_block(Args["criteria"], Args["criteria_sha256"])
    self.harness_commit = commit_fn()
    self.base_trial_id = Manifest["trial_id"]
    self.base_harness_commit = Manifest["harness_commit"]

    self.cells = {}
    for Mode in Args["modes"]:
      if Mode not in MODES:
        raise ValueError(f"알 수 없는 mode: {Mode!r}")
      VaultPath = os.path.join(run_dir, f"propose_{Mode}", "vault.jsonl")
      # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 셀 볼트가 없으면 그 모드의 기본 상태를 만들 수 없다
      if not os.path.isfile(VaultPath):
        raise ValueError(f"셀 볼트가 없다: propose_{Mode}")
      Notes = _read_vault_notes(VaultPath)
      Retr = Retriever(embed_backend=embed_backend)
      for Index, Note in enumerate(Notes, start=1):
        Retr.add(_to_document_record(Note), group=Note.group)
        if Index % PROGRESS_EVERY == 0 or Index == len(Notes):
          print_fn(f"load propose_{Mode} embedded={Index}/{len(Notes)}")
      if not Notes:
        print_fn(f"load propose_{Mode} embedded=0/0")
      self.cells[Mode] = {"notes": Notes, "retriever": Retr}
    self.lock = threading.Lock()

  def health(self) -> dict:
    return {
      "status": "ok",
      "modes": list(self.cells),
      "base_notes": {Mode: len(Cell["notes"]) for Mode, Cell in self.cells.items()},
      "base_run": self.base_run,
    }

  def doc_list(self) -> list[dict]:
    # 제목 · 본문 · 그룹 이름은 내보내지 않는다 - 식별자와 크기만
    return [
      {
        "doc_id": Doc.doc_id,
        "layer": Doc.source_layer,
        "segments": len(Doc.segments),
        "chars": sum(len(Seg.text) for Seg in Doc.segments),
      }
      for Doc in self.docs.values()
    ]

  def _mask(self, Obj):
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 모델이 만든 제목이나 오류 문구에 실제 주인 이름이 섞여도 응답에는 가린 이름만 나가게 한다
    Text = json.dumps(Obj, ensure_ascii=False)
    for Name in sorted(self.owners, key=len, reverse=True):
      Text = Text.replace(Name, self.labels[Name])
    return json.loads(Text)

  def _request_state(self, doc_id: str, mode: str):
    Base = self.cells[mode]
    Kept = [Note for Note in Base["notes"] if Note.source_doc_id != doc_id]
    KeptIds = {Note.note_id for Note in Kept}
    Retr = Retriever(embed_backend=Base["retriever"].embed_backend)
    # add() 는 노트를 다시 임베딩하므로 기본 색인의 ( 레코드, 벡터, 그룹 ) 을 내부 리스트째 복사한다 - 재임베딩 없이 요청 문서 노트만 뺀다
    for Entry, Group in zip(Base["retriever"].Index, Base["retriever"].Groups):
      if Entry[0].id in KeptIds:
        Retr.Index.append(Entry)
        Retr.Groups.append(Group)
    LayerGroupById = {Note.note_id: (Note.layer, Note.group) for Note in Kept}
    return Kept, LayerGroupById, Retr

  def _notes_payload(self, Log: list, NewNotes: list) -> list[dict]:
    ById = {Note.note_id: Note for Note in NewNotes}
    Titles = {}
    for Entry in Log:
      if Entry["entry_type"] == "decompose":
        Titles = {Index: Note["title"] for Index, Note in enumerate(Entry["notes"])}
    Payload = []
    for Entry in Log:
      if Entry["entry_type"] != "place":
        continue
      Candidates = [{"id": Cand["id"], "layer": Cand["layer"]} for Cand in Entry["candidates"]]
      Note = ById.get(Entry["note_id"])
      if Note is None:
        Payload.append({
          "note_id": None, "title": Titles.get(Entry["note_index"]), "layer": None, "group_label": None,
          "source_segment_ids": Entry["source_segment_ids"], "upward_links": [], "downward_links": [],
          "candidates": Candidates, "problems": Entry["problems"],
        })
        continue
      Down = []
      for Link in Note.downward_conditional_links:
        Condition = Link.visibility_condition
        Down.append({
          "target_id": Link.target_id,
          "target_layer": Condition["layer"],
          "target_group_label": group_label(Condition["layer"], Condition["group"], self.labels),
        })
      Payload.append({
        "note_id": Note.note_id, "title": Note.title, "layer": Note.layer,
        "group_label": group_label(Note.layer, Note.group, self.labels),
        "source_segment_ids": list(Note.source_segment_ids), "upward_links": list(Note.upward_links),
        "downward_links": Down, "candidates": Candidates, "problems": Entry["problems"],
      })
    return Payload

  def _summary_text(self, Doc, Decompose: dict, Notes: list[dict]) -> str:
    Lines = [
      f"문서 {Doc.doc_id} ( {Doc.source_layer} 층, 세그먼트 {len(Doc.segments)}개 ) 분해 "
      + ("성공" if Decompose["ok"] else f"실패 ( {Decompose['error']} )")
      + f", 노트 {Decompose['note_count']}개"
    ]
    for Index, Note in enumerate(Notes, start=1):
      if Note["note_id"] is None:
        Lines.append(f"- 노트 {Index} : {Note['title']} → 배치 실패 ( {', '.join(Note['problems'])} ), 후보 {len(Note['candidates'])}개")
      else:
        Lines.append(
          f"- 노트 {Index} : {Note['title']} → {Note['layer']} 층"
          + (f" ( {Note['group_label']} )" if Note["group_label"] else "")
          + f", 상향 링크 {len(Note['upward_links'])}개, 하향 조건부 링크 {len(Note['downward_links'])}개, 후보 {len(Note['candidates'])}개"
        )
    return "\n".join(Lines)

  def run(self, body) -> tuple[int, dict]:
    if not isinstance(body, dict) or not isinstance(body.get("doc_id"), str) or not isinstance(body.get("mode"), str):
      return 400, {"ok": False, "error_type": "BadRequest", "message": "본문은 doc_id · mode 문자열을 가진 JSON 이어야 한다"}
    DocId, Mode = body["doc_id"], body["mode"]
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 실행에 없던 문서는 기본 볼트와 대응이 없어 404 로 돌려준다
    if DocId not in self.docs:
      return 404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 doc_id"}
    if Mode not in self.cells:
      return 400, {"ok": False, "error_type": "BadRequest", "message": f"불러온 모드가 아니다: {list(self.cells)}"}
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 생성 서버 슬롯이 1개라 동시에 두 요청을 처리하면 서로 느려지거나 실패한다
    if not self.lock.acquire(blocking=False):
      return 409, {"ok": False, "error_type": "Busy", "message": "다른 요청을 처리 중이다"}
    try:
      return self._run_locked(DocId, Mode)
    finally:
      self.lock.release()

  def _run_locked(self, DocId: str, Mode: str) -> tuple[int, dict]:
    Doc = self.docs[DocId]
    Stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    Root = os.path.join(self.work_root, REQUEST_SUBDIR)
    os.makedirs(Root, exist_ok=True)
    RequestDir = _validate_out_dir(os.path.join(Root, f"{Stamp}_{DocId[:8]}_{Mode}"), self.work_root)
    os.makedirs(RequestDir)
    for FileName in ("log.jsonl", "new_notes.jsonl"):
      open(os.path.join(RequestDir, FileName), "x").close()
    TrialId = str(uuid.uuid4())
    RequestManifest = {
      "trial_id": TrialId,
      "run_kind": RUN_KIND,
      "base_run": self.base_run,
      "base_trial_id": self.base_trial_id,
      "base_harness_commit": self.base_harness_commit,
      "harness_commit": self.harness_commit,
      "doc_id": DocId,
      "mode": Mode,
      "k": self.k,
      "gen_seed": self.gen_seed,
      "decompose_max_tokens": self.decompose_max_tokens,
      "place_max_tokens": self.place_max_tokens,
      "model_id": self.model_id,
      "started_at_utc": _utc_now(),
      "ended_at_utc": None,
      "status": "running",
      "error": None,
    }

    def write_manifest() -> None:
      with open(os.path.join(RequestDir, "request_manifest.json"), "w", encoding="utf-8") as File:
        json.dump(RequestManifest, File, ensure_ascii=False, indent=2)

    write_manifest()
    Started = time.monotonic()
    try:
      VaultNotes, LayerGroupById, Retr = self._request_state(DocId, Mode)
      BaseSize = len(VaultNotes)
      BaseLog = {
        "trial_id": TrialId, "run_kind": RUN_KIND, "base_run": self.base_run, "base_trial_id": self.base_trial_id,
        "base_harness_commit": self.base_harness_commit, "harness_commit": self.harness_commit,
        "condition": CONDITION, "mode": Mode, "k": self.k, "gen_seed": self.gen_seed, "raw_sha256": self.raw_sha[DocId],
      }
      Log = run_propose_doc(
        Doc, Mode, self.k, Retr, VaultNotes, LayerGroupById, self.chat_fn, self.model_id,
        GenerationConfig(temperature=TEMPERATURE, seed=self.gen_seed, max_tokens=self.decompose_max_tokens, enable_thinking=ENABLE_THINKING),
        GenerationConfig(temperature=TEMPERATURE, seed=self.gen_seed, max_tokens=self.place_max_tokens, enable_thinking=ENABLE_THINKING),
        self.block, self.block_sha, self.owners, self.timeout_seconds, BaseLog,
      )
      NewNotes = VaultNotes[BaseSize:]
      with open(os.path.join(RequestDir, "log.jsonl"), "a", encoding="utf-8") as File:
        for Entry in Log:
          File.write(json.dumps(Entry, ensure_ascii=False) + "\n")
      with open(os.path.join(RequestDir, "new_notes.jsonl"), "a", encoding="utf-8") as File:
        for Note in NewNotes:
          File.write(json.dumps(asdict(Note), ensure_ascii=False) + "\n")
      DecomposeEntry = next(Entry for Entry in Log if Entry["entry_type"] == "decompose")
      Decompose = {"ok": DecomposeEntry["ok"], "error": DecomposeEntry["error"], "note_count": len(DecomposeEntry["notes"])}
      Notes = self._notes_payload(Log, NewNotes)
      Elapsed = time.monotonic() - Started
      Response = {
        "ok": all(Entry["ok"] for Entry in Log),
        "elapsed_s": round(Elapsed, 3),
        "request_dir": RequestDir,
        "decompose": Decompose,
        "notes": Notes,
        "summary_text": self._summary_text(Doc, Decompose, Notes),
      }
      Response = self._mask(Response)
    except BaseException as Error:
      RequestManifest["status"] = "aborted"
      RequestManifest["error"] = {"type": type(Error).__name__, "message": str(Error)}
      RequestManifest["ended_at_utc"] = _utc_now()
      write_manifest()
      # 시스템 종료 신호는 삼키지 않는다
      if not isinstance(Error, Exception):
        raise
      self.print_fn(f"run {DocId} {Mode} error={type(Error).__name__}")
      return 500, self._mask({"ok": False, "error_type": type(Error).__name__, "message": str(Error)})
    RequestManifest["status"] = "completed"
    RequestManifest["ended_at_utc"] = _utc_now()
    write_manifest()
    self.print_fn(
      f"run {DocId} {Mode} ok={Response['ok']} notes={len(Notes)} base_notes={BaseSize} elapsed_s={Elapsed:.1f}"
    )
    return 200, Response


def make_handler(App: DemoApp):
  class Handler(BaseHTTPRequestHandler):
    def _send(self, Status: int, Obj) -> None:
      Data = json.dumps(Obj, ensure_ascii=False).encode("utf-8")
      self.send_response(Status)
      self.send_header("Content-Type", "application/json; charset=utf-8")
      self.send_header("Content-Length", str(len(Data)))
      self.end_headers()
      self.wfile.write(Data)

    def do_GET(self) -> None:
      if self.path == "/health":
        self._send(200, App.health())
      elif self.path == "/docs":
        self._send(200, App.doc_list())
      else:
        self._send(404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"})

    def do_POST(self) -> None:
      if self.path != "/run":
        self._send(404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"})
        return
      try:
        Length = int(self.headers.get("Content-Length", ""))
      except ValueError:
        Length = -1
      # 길이를 모르거나 상한을 넘는 본문은 읽지 않는다
      if Length < 0 or Length > MAX_BODY_BYTES:
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": "본문 길이가 없거나 너무 크다"})
        return
      try:
        Body = json.loads(self.rfile.read(Length).decode("utf-8"))
      except (UnicodeDecodeError, json.JSONDecodeError):
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": "JSON 이 아니다"})
        return
      Status, Obj = App.run(Body)
      self._send(Status, Obj)

    def log_message(self, Format, *Args) -> None:
      # 기본 접속 로그는 클라이언트 주소를 stderr 로 찍는다 - 화면에는 요청마다 숫자 · id 한 줄만 남긴다
      return

  return Handler


def make_server(App: DemoApp, host: str, port: int) -> ThreadingHTTPServer:
  # 동시에 들어온 요청이 409 를 받으려면 요청마다 스레드가 있어야 한다
  return ThreadingHTTPServer((host, port), make_handler(App))


def parse_args(argv=None) -> argparse.Namespace:
  Parser = argparse.ArgumentParser(description="시연 앞단 API ( 완료된 제안 실행의 기본 볼트 위에서 문서 한 건씩 처리 )")
  # 모델 · 검색 설정은 받지 않는다 - 실행 manifest 에서만 읽는다
  Parser.add_argument("--run-dir", required=True)
  Parser.add_argument("--host", required=True)
  Parser.add_argument("--port", required=True, type=int)
  return Parser.parse_args(argv)


def _print_flush(Line: str) -> None:
  print(Line, flush=True)


def main(argv=None) -> None:
  Args = parse_args(argv)
  App = DemoApp(
    Args.run_dir, chat_fn=chat, embed_backend=None, commit_fn=lambda: git_head_commit(REPO_DIR),
    work_root=DEFAULT_WORK_ROOT, print_fn=_print_flush,
  )
  Server = make_server(App, Args.host, Args.port)
  _print_flush(f"serve host={Args.host} port={Args.port} modes={len(App.cells)} docs={len(App.docs)}")
  Server.serve_forever()


if __name__ == "__main__":
  main()
