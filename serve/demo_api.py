import argparse
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from agent.layer_block import load_layer_block
from agent.llm_client import GenerationConfig, chat
from agent.placement import MODES
from agent.propose import _to_document_record, run_propose_doc
from agent.types import DownwardLink, NoteRecord
from build.public_build import view_selection
from labeling.gold import read_membership, visible_pairs_for
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
# 조회 한 번이 squid read_timeout 2분 안에 끝나야 한다
MAX_WAIT_SECONDS = 60
# 사용자 결정 2026-10-17 비동기 작업 + 조회 : squid read_timeout 2분 · client_lifetime 5분이라 문서 한 건 ( 85 ~ 450 s ) 동기 응답이 Dify HTTP 노드에서 끊긴다
_JOB_PATH = re.compile(r"/jobs/([0-9a-f]{32})")
_WAIT_VALUE = re.compile(r"[0-9]+")
# 본문 읽기에 실패해 이미 응답을 보냈다는 표지
_BAD_BODY = object()
# 사용자 결정 2026-10-22 : 합성 코퍼스는 가명 그대로 보인다 - 불러온 실행 manifest 의 args.snapshot 이 이 값이고 args.run_kind 가 아래 값일 때만
DEMO_SNAPSHOT = 900
DEMO_RUN_KIND = "demo"


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
    # 사용자 결정 2026-10-22 : 검색 · 배치는 소속 팀 표를 쓰고 이름 가림은 주인 집합을 그대로 쓴다
    self.membership = read_membership(Args["source_layers"])
    self.owners = set(self.membership.teams_by_owner)
    # 사용자 결정 2026-10-22 : 합성 코퍼스는 가명 그대로, 실제 코퍼스 볼트는 주인A … 로 가린다 - 두 키가 args 에 없으면 가리는 쪽이라 조용한 실패가 아니다
    self.show_names = Args.get("snapshot") == DEMO_SNAPSHOT and Args.get("run_kind") == DEMO_RUN_KIND
    self.labels = {Name: Name for Name in self.owners} if self.show_names else owner_labels(self.owners)
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
    # 사용자 결정 2026-10-17 비동기 작업 + 조회 : squid read_timeout 2분 · client_lifetime 5분이라 문서 한 건 ( 85 ~ 450 s ) 동기 응답이 Dify HTTP 노드에서 끊긴다
    self.jobs = {}
    # 잠금을 잡는 일과 지금 도는 job_id 를 적는 일이 한 덩어리여야 409 응답이 도는 작업을 정확히 가리킨다
    self.meta_lock = threading.Lock()
    self.current_job_id = None

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

  def viewers(self) -> dict:
    # 사용자 결정 2026-10-21 : 시연의 보는 사람별 보기는 서버 쪽 필터 결과이며 화면 로직이 아니다 - 보는 사람 목록도 서버가 낸다
    Personal = sorted(
      (
        {"viewer_id": "개인:" + self.labels[Owner], "layer": "개인", "label": self.labels[Owner], "teams": sorted(Teams)}
        for Owner, Teams in self.membership.teams_by_owner.items()
      ),
      key=lambda Item: Item["label"],
    )
    Teams = {Team for Teams_ in self.membership.teams_by_owner.values() for Team in Teams_}
    Teams |= {Doc.source_group for Doc in self.docs.values() if Doc.source_layer == "팀"}
    Team_items = [
      {"viewer_id": "팀:" + Team, "layer": "팀", "label": Team, "teams": [Team]} for Team in sorted(Teams)
    ]
    Company = [{"viewer_id": "전사", "layer": "전사", "label": "전사", "teams": []}]
    return self._mask({"show_names": self.show_names, "viewers": Personal + Team_items + Company})

  def _viewer_target(self, viewer_id: str):
    # 가린 label 을 실제 주인으로 되돌린다 - 목록에 없는 id 는 None
    for Item in self.viewers()["viewers"]:
      if Item["viewer_id"] == viewer_id:
        break
    else:
      return None
    if viewer_id == "전사":
      return "전사", None
    Layer, _, Label = viewer_id.partition(":")
    if Layer == "팀":
      return "팀", Label
    for Owner in self.membership.teams_by_owner:
      if self.labels[Owner] == Label:
        return "개인", Owner
    return None

  def view(self, mode: str, viewer_id: str, job_id) -> tuple:
    if mode not in self.cells:
      return 400, {"ok": False, "error_type": "BadRequest", "message": f"불러온 모드가 아니다: {list(self.cells)}"}
    Target = self._viewer_target(viewer_id)
    if Target is None:
      return 400, {"ok": False, "error_type": "BadRequest", "message": "viewers 에 없는 viewer 이다"}
    Notes = [asdict(Note) for Note in self.cells[mode]["notes"]]
    Dropped = None
    if job_id is not None:
      Job = self.jobs.get(job_id)
      if Job is None:
        return 404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 job_id"}
      # 끝나지 않았거나 다른 모드로 돈 작업의 노트는 이 모드의 기본 볼트와 맞지 않는다
      if Job["status"] != "completed" or Job["mode"] != mode:
        return 400, {"ok": False, "error_type": "BadRequest", "message": "완료된 같은 mode 의 작업이어야 한다"}
      Notes, Dropped = self._overlay(Notes, Job)
    try:
      Pairs = visible_pairs_for(Target[0], Target[1], self.membership)
      Included, Links, Counts = view_selection(Notes, Pairs)
      Items = []
      for Note in Included:
        Up, Opened = Links[Note["note_id"]]
        # 사용자 결정 2026-10-22 : 실제 코퍼스 실행은 본문을 글자 수로 가린다 ( build_view 의 --redact-body 와 같은 문구 )
        Body = Note["body"] if self.show_names else f"( 본문 {len(Note['body'])}자 가림 )"
        Items.append({
          "note_id": Note["note_id"], "title": Note["title"], "layer": Note["layer"],
          "group_label": group_label(Note["layer"], Note["group"], self.labels), "body": Body,
          "source_doc_id": Note["source_doc_id"], "source_layer": Note["source_layer"],
          "source_segment_ids": list(Note["source_segment_ids"]), "upward_links": Up, "opened_downward_links": Opened,
          "inserted_at_vault_size": Note["inserted_at_vault_size"],
        })
    except ValueError as Error:
      return 500, self._mask({"ok": False, "error_type": "ValueError", "message": str(Error)})
    if Dropped is not None:
      Counts["overlay_dangling_links_dropped"] = Dropped
    return 200, self._mask({"mode": mode, "viewer_id": viewer_id, "show_names": self.show_names, "notes": Items, "counts": Counts})

  def _overlay(self, Notes: list, Job: dict) -> tuple:
    # 완료된 작업의 새 노트가 그 문서의 기본 노트를 대신한다 - 요청 상태와 같은 규칙이다
    Result = Job["result"] or {}
    Path = os.path.join(Result["request_dir"], "new_notes.jsonl")
    with open(Path, encoding="utf-8") as File:
      New = [json.loads(Line) for Line in File if Line.strip()]
    Kept = [Note for Note in Notes if Note["source_doc_id"] != Job["doc_id"]]
    Ids = {Note["note_id"] for Note in Kept + New}
    Dropped = 0
    Out = []
    for Note in Kept:
      Note = dict(Note)
      # 지워진 기존 노트를 가리키던 링크는 대상이 없어 깨진 데이터가 되므로 빼고 수만 센다
      Up = [Target for Target in Note["upward_links"] if Target in Ids]
      Down = [Link for Link in Note["downward_conditional_links"] if Link["target_id"] in Ids]
      Dropped += len(Note["upward_links"]) - len(Up) + len(Note["downward_conditional_links"]) - len(Down)
      Note["upward_links"], Note["downward_conditional_links"] = Up, Down
      Out.append(Note)
    return Out + New, Dropped

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

  def _check_request(self, body):
    # run 과 submit 이 같은 검증 · 같은 오류 응답을 쓰도록 한 곳에 둔다 - 오류면 ( 응답, None, None )
    if not isinstance(body, dict) or not isinstance(body.get("doc_id"), str) or not isinstance(body.get("mode"), str):
      return (400, {"ok": False, "error_type": "BadRequest", "message": "본문은 doc_id · mode 문자열을 가진 JSON 이어야 한다"}), None, None
    DocId, Mode = body["doc_id"], body["mode"]
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 실행에 없던 문서는 기본 볼트와 대응이 없어 404 로 돌려준다
    if DocId not in self.docs:
      return (404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 doc_id"}), None, None
    if Mode not in self.cells:
      return (400, {"ok": False, "error_type": "BadRequest", "message": f"불러온 모드가 아니다: {list(self.cells)}"}), None, None
    return None, DocId, Mode

  def run(self, body) -> tuple[int, dict]:
    Error, DocId, Mode = self._check_request(body)
    if Error is not None:
      return Error
    # 시연 앞단 ( 사용자 결정 2026-10-16 Dify 필수 ) : 생성 서버 슬롯이 1개라 동시에 두 요청을 처리하면 서로 느려지거나 실패한다
    if not self.lock.acquire(blocking=False):
      return 409, {"ok": False, "error_type": "Busy", "message": "다른 요청을 처리 중이다"}
    try:
      return self._run_locked(DocId, Mode)
    finally:
      self.lock.release()

  # 사용자 결정 2026-10-17 비동기 작업 + 조회 : squid read_timeout 2분 · client_lifetime 5분이라 문서 한 건 ( 85 ~ 450 s ) 동기 응답이 Dify HTTP 노드에서 끊긴다
  def submit(self, body) -> tuple[int, dict]:
    Error, DocId, Mode = self._check_request(body)
    if Error is not None:
      return Error
    JobId = uuid.uuid4().hex
    Job = {
      "job_id": JobId, "doc_id": DocId, "mode": Mode, "status": "running", "submitted_at_utc": _utc_now(),
      "started_monotonic": time.monotonic(), "event": threading.Event(), "http_status": None, "result": None,
    }
    Job["thread"] = threading.Thread(target=self._job_main, args=(Job,), daemon=True)
    with self.meta_lock:
      if not self.lock.acquire(blocking=False):
        return 409, {
          "ok": False, "error_type": "Busy", "message": "다른 요청을 처리 중이다", "running_job_id": self.current_job_id,
        }
      self.current_job_id = JobId
      # 409 의 running_job_id 를 바로 조회해도 404 가 나지 않도록 레코드를 잠금과 같은 덩어리 안에서 등록한다
      self.jobs[JobId] = Job
    try:
      Job["thread"].start()
    except BaseException:
      # 스레드를 못 띄우면 잠금이 영영 잡혀 있고 레코드가 running 으로 남는다
      del self.jobs[JobId]
      with self.meta_lock:
        self.current_job_id = None
        self.lock.release()
      raise
    return 202, {"ok": True, "job_id": JobId, "status": "running"}

  def _job_main(self, Job: dict) -> None:
    try:
      Status, Result = self._run_locked(Job["doc_id"], Job["mode"])
      Job["http_status"] = Status
      Job["result"] = Result
      Job["status"] = "completed" if Status == 200 else "failed"
    except BaseException as Error:
      # 종료 신호도 레코드에는 실패로 남기고 다시 올린다
      Job["result"] = {"ok": False, "error_type": type(Error).__name__, "message": str(Error)}
      Job["status"] = "failed"
      raise
    finally:
      # 어떤 경로로 끝나든 잠금을 풀고 완료 이벤트를 세워야 레코드가 running 으로 남지 않는다
      with self.meta_lock:
        self.current_job_id = None
        self.lock.release()
      Job["event"].set()

  # 사용자 결정 2026-10-17 비동기 작업 + 조회 : squid read_timeout 2분 · client_lifetime 5분이라 문서 한 건 ( 85 ~ 450 s ) 동기 응답이 Dify HTTP 노드에서 끊긴다
  def job_status(self, job_id: str, wait_seconds: int) -> tuple[int, dict]:
    if not isinstance(wait_seconds, int) or isinstance(wait_seconds, bool) or not 0 <= wait_seconds <= MAX_WAIT_SECONDS:
      raise ValueError(f"wait_seconds 는 0 ~ {MAX_WAIT_SECONDS} 정수여야 한다: {wait_seconds!r}")
    Job = self.jobs.get(job_id)
    if Job is None:
      return 404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 job_id"}
    if Job["event"].wait(wait_seconds):
      Body = {
        "job_id": job_id, "status": Job["status"], "doc_id": Job["doc_id"], "mode": Job["mode"],
        "http_status": Job["http_status"], "result": Job["result"],
      }
    else:
      Body = {
        "job_id": job_id, "status": "running", "doc_id": Job["doc_id"], "mode": Job["mode"],
        "elapsed_s": round(time.monotonic() - Job["started_monotonic"], 1),
      }
    return 200, self._mask(Body)

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
        self.block, self.block_sha, self.membership, self.timeout_seconds, BaseLog,
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


def make_handler(App: DemoApp, cors_origin=None):
  class Handler(BaseHTTPRequestHandler):
    def _send(self, Status: int, Obj) -> None:
      Data = json.dumps(Obj, ensure_ascii=False).encode("utf-8")
      self.send_response(Status)
      self.send_header("Content-Type", "application/json; charset=utf-8")
      self.send_header("Content-Length", str(len(Data)))
      # 사용자 결정 2026-10-21 : 화면은 다른 출처에서 서버 쪽 필터 결과만 읽는다 - 옵션을 줬을 때만 CORS 헤더를 보낸다
      if cors_origin is not None:
        self.send_header("Access-Control-Allow-Origin", cors_origin)
      self.end_headers()
      self.wfile.write(Data)

    def do_OPTIONS(self) -> None:
      if cors_origin is None:
        self._send(404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"})
        return
      self.send_response(204)
      self.send_header("Access-Control-Allow-Origin", cors_origin)
      self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
      self.send_header("Access-Control-Allow-Headers", "Content-Type")
      self.send_header("Content-Length", "0")
      self.end_headers()

    def do_GET(self) -> None:
      if self.path == "/health":
        self._send(200, App.health())
      elif self.path == "/docs":
        self._send(200, App.doc_list())
      elif urlsplit(self.path).path == "/viewers":
        self._send(200, App.viewers())
      elif urlsplit(self.path).path == "/view":
        self._view(urlsplit(self.path).query)
      else:
        # 사용자 결정 2026-10-17 비동기 작업 + 조회 : squid read_timeout 2분 · client_lifetime 5분이라 문서 한 건 ( 85 ~ 450 s ) 동기 응답이 Dify HTTP 노드에서 끊긴다
        Parts = urlsplit(self.path)
        Match = _JOB_PATH.fullmatch(Parts.path)
        if Match is None:
          self._send(404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"})
          return
        Wait = self._parse_wait(Parts.query)
        if Wait is None:
          return
        Status, Obj = App.job_status(Match.group(1), Wait)
        self._send(Status, Obj)

    def _view(self, Query: str) -> None:
      # mode · viewer 는 정확히 하나씩, job 은 많아야 하나 - 그 밖은 400
      Params = parse_qs(Query, keep_blank_values=True)
      Mode, Viewer, Job = Params.get("mode", []), Params.get("viewer", []), Params.get("job", [])
      if len(Mode) != 1 or len(Viewer) != 1 or len(Job) > 1 or not Mode[0] or not Viewer[0] or (Job and not Job[0]):
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": "mode · viewer 는 하나씩, job 은 많아야 하나여야 한다"})
        return
      Status, Obj = App.view(Mode[0], Viewer[0], Job[0] if Job else None)
      self._send(Status, Obj)

    def _parse_wait(self, Query: str):
      # wait 는 없으면 0, 0 ~ MAX_WAIT_SECONDS 정수 하나만 받는다 - 그 밖은 400 을 보내고 None
      Values = parse_qs(Query, keep_blank_values=True).get("wait", ["0"])
      if len(Values) != 1 or not _WAIT_VALUE.fullmatch(Values[0]) or int(Values[0]) > MAX_WAIT_SECONDS:
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": f"wait 는 0 ~ {MAX_WAIT_SECONDS} 정수 하나여야 한다"})
        return None
      return int(Values[0])

    def _read_json_body(self):
      # POST /run 과 POST /jobs 가 같은 길이 · JSON 검사를 쓴다 - 오류면 400 을 보내고 _BAD_BODY ( JSON null 도 정상 본문이라 None 을 쓰지 않는다 )
      try:
        Length = int(self.headers.get("Content-Length", ""))
      except ValueError:
        Length = -1
      # 길이를 모르거나 상한을 넘는 본문은 읽지 않는다
      if Length < 0 or Length > MAX_BODY_BYTES:
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": "본문 길이가 없거나 너무 크다"})
        return _BAD_BODY
      try:
        return json.loads(self.rfile.read(Length).decode("utf-8"))
      except (UnicodeDecodeError, json.JSONDecodeError):
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": "JSON 이 아니다"})
        return _BAD_BODY

    def do_POST(self) -> None:
      if self.path not in ("/run", "/jobs"):
        self._send(404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"})
        return
      Body = self._read_json_body()
      if Body is _BAD_BODY:
        return
      Status, Obj = (App.run if self.path == "/run" else App.submit)(Body)
      self._send(Status, Obj)

    def log_message(self, Format, *Args) -> None:
      # 기본 접속 로그는 클라이언트 주소를 stderr 로 찍는다 - 화면에는 요청마다 숫자 · id 한 줄만 남긴다
      return

  return Handler


def make_server(App: DemoApp, host: str, port: int, cors_origin=None) -> ThreadingHTTPServer:
  # 동시에 들어온 요청이 409 를 받으려면 요청마다 스레드가 있어야 한다
  return ThreadingHTTPServer((host, port), make_handler(App, cors_origin))


def parse_args(argv=None) -> argparse.Namespace:
  Parser = argparse.ArgumentParser(description="시연 앞단 API ( 완료된 제안 실행의 기본 볼트 위에서 문서 한 건씩 처리 )")
  # 모델 · 검색 설정은 받지 않는다 - 실행 manifest 에서만 읽는다
  Parser.add_argument("--run-dir", required=True)
  Parser.add_argument("--host", required=True)
  Parser.add_argument("--port", required=True, type=int)
  # 기본값을 두지 않는다 - 주지 않으면 CORS 헤더를 보내지 않는다
  Parser.add_argument("--cors-origin", default=None)
  return Parser.parse_args(argv)


def _print_flush(Line: str) -> None:
  print(Line, flush=True)


def main(argv=None) -> None:
  Args = parse_args(argv)
  App = DemoApp(
    Args.run_dir, chat_fn=chat, embed_backend=None, commit_fn=lambda: git_head_commit(REPO_DIR),
    work_root=DEFAULT_WORK_ROOT, print_fn=_print_flush,
  )
  Server = make_server(App, Args.host, Args.port, cors_origin=Args.cors_origin)
  _print_flush(f"serve host={Args.host} port={Args.port} modes={len(App.cells)} docs={len(App.docs)}")
  Server.serve_forever()


if __name__ == "__main__":
  main()
