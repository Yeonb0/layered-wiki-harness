import argparse
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
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
from serve.meetings import AlreadyLinkedError, MeetingStore, NotFoundError
from serve.minutes import TEXT_MAX_CHARS, ConflictError, MinutesStore, source_doc_of

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
# 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능 - 회의 · 할 일은 노트와 같은 층 규칙으로 서버가 거른다
_MEETING_PATH = re.compile(r"/meetings(?:/([a-z0-9]{1,40}))?")
_WORKSPACE_PATH = "/workspaces"
# 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 문서는 합성 시연 코퍼스 차수 901. 시연 작업 폴더에만 쓰고 실험 코퍼스 · 평가 집계에 넣지 않는다 ( 3절 24 · 25 )
_MINUTES_PATH = "/minutes"
_PROPOSAL_PATH = re.compile(r"/proposals(?:/(901[0-9]{29})(/decide|/trace)?)?")
# 회의록 본문은 20000자까지이고 JSON 이스케이프로 한 글자가 6바이트까지 늘 수 있다
MINUTES_MAX_BODY_BYTES = TEXT_MAX_CHARS * 6 + MAX_BODY_BYTES
_TASK_PATH = re.compile(r"/tasks(?:/([a-z0-9]{1,40})(/progress)?)?")
_WAIT_VALUE = re.compile(r"[0-9]+")
# 본문 읽기에 실패해 이미 응답을 보냈다는 표지
_BAD_BODY = object()
# 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
LIVE_USER = "layered-wiki-demo-ui"
# 워크플로가 문서 한 건을 처리하는 동안 스트리밍 줄 사이가 길게 비므로 읽기 제한을 넉넉히 둔다
DIFY_READ_TIMEOUT_SECONDS = 600
# Dify 오류 응답 본문은 이만큼만 읽는다
_DIFY_ERROR_BODY_BYTES = 4096


class DifyError(Exception):
  pass


# 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
def make_dify_fn(url: str, key: str, timeout_seconds: float = DIFY_READ_TIMEOUT_SECONDS):
  endpoint = url.rstrip("/") + "/workflows/run"
  # 환경 변수 프록시를 쓰지 않는다 - 빈 ProxyHandler 로 직접 연결한다
  opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

  def dify_fn(inputs: dict, user: str):
    body = json.dumps({"inputs": inputs, "response_mode": "streaming", "user": user}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
      endpoint, data=body, method="POST", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    )
    try:
      response = opener.open(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as error:
      # 오류에는 상태 코드와 응답 본문의 code · message 만 담는다 - 헤더 · 키는 담지 않는다
      code = message = None
      try:
        parsed = json.loads(error.read(_DIFY_ERROR_BODY_BYTES).decode("utf-8"))
        if isinstance(parsed, dict):
          code, message = parsed.get("code"), parsed.get("message")
      except (ValueError, OSError):
        pass
      finally:
        # 응답 객체를 닫아 파일 핸들이 남지 않게 한다
        error.close()
      raise DifyError(f"Dify HTTP {error.code} : code={code} message={message}") from None
    with response:
      for raw in response:
        line = raw.decode("utf-8").strip()
        # data: 줄만 이벤트다 - 빈 줄 · ping 같은 줄은 넘긴다
        if line.startswith("data: "):
          yield json.loads(line[len("data: "):])

  return dify_fn
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
  def __init__(self, run_dir, chat_fn, embed_backend, commit_fn, work_root, print_fn, dify_fn=None, meetings=None) -> None:
    self.chat_fn = chat_fn
    # 라이브 투입에서 Dify 스트리밍 이벤트를 차례로 내는 함수 - 없으면 라이브 투입을 받지 않는다
    self.dify_fn = dify_fn
    # 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능 - 회의 · 할 일은 노트와 같은 층 규칙으로 서버가 거른다
    # 회의 저장소 - None 이면 회의 경로는 모두 503 이다. 저장소는 구성원 표 · 표시 이름이 필요해서 main 이 앱을 만든 뒤 붙이기도 한다
    self.meetings = meetings
    # 회의록 저장소 - None 이면 회의록 경로는 모두 503 이다
    self.minutes = None
    self.decide_lock = threading.Lock()
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
    # 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
    self.live = None

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
    # 승인된 회의록 노트는 job 과 별개로 그 doc 의 mode 보기에 항상 겹친다 - 같은 doc 의 job 겹침이 이미 그 노트를 담으면 건너뛴다
    Notes, MinutesDropped, MinutesIds = self._minutes_overlay(Notes, mode, Job["doc_id"] if job_id is not None else None)
    if MinutesDropped:
      Dropped = (Dropped or 0) + MinutesDropped
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
    if self.minutes is not None:
      Counts["minutes_notes_included"] = sum(1 for Item in Items if Item["note_id"] in MinutesIds)
    return 200, self._mask({"mode": mode, "viewer_id": viewer_id, "show_names": self.show_names, "notes": Items, "counts": Counts})

  def _overlay(self, Notes: list, Job: dict) -> tuple:
    # 완료된 작업의 새 노트가 그 문서의 기본 노트를 대신한다 - 요청 상태와 같은 규칙이다
    Result = Job["result"] or {}
    Path = os.path.join(Result["request_dir"], "new_notes.jsonl")
    with open(Path, encoding="utf-8") as File:
      New = [json.loads(Line) for Line in File if Line.strip()]
    Kept = [Note for Note in Notes if Note["source_doc_id"] != Job["doc_id"]]
    Removed = {Note["note_id"] for Note in Notes if Note["source_doc_id"] == Job["doc_id"]}
    Ids = {Note["note_id"] for Note in Kept + New}
    Dropped = 0
    Out = []
    for Note in Kept:
      Note = dict(Note)
      # 지침 3절 20 : 링크는 에이전트가 만든 것만 그린다 - 새 노트가 옛 노트와 같은 id ( 문서id#n순번 ) 를 받아도 옛 노트를 가리키던 링크는 새 노트로 넘어가지 않는다
      # 지워진 기존 노트를 가리키던 링크는 빼고 수만 센다 - 대상이 지워진 노트이거나 어디에도 없는 경우다
      Up = [Target for Target in Note["upward_links"] if Target in Ids and Target not in Removed]
      Down = [Link for Link in Note["downward_conditional_links"] if Link["target_id"] in Ids and Link["target_id"] not in Removed]
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
  def submit(self, body, on_done=None) -> tuple[int, dict]:
    Error, DocId, Mode = self._check_request(body)
    if Error is not None:
      return Error
    JobId = uuid.uuid4().hex
    Job = {
      "job_id": JobId, "doc_id": DocId, "mode": Mode, "status": "running", "submitted_at_utc": _utc_now(),
      "started_monotonic": time.monotonic(), "event": threading.Event(), "http_status": None, "result": None,
      "on_done": on_done,
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
      # 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
      # 도는 라이브가 아직 작업을 못 붙였고 문서 · 모드가 같을 때만 그 작업이 라이브의 작업이다
      Live = self.live["record"] if self.live is not None else None
      if (
        Live is not None and Live["status"] == "running" and Live["job_id"] is None
        and Live["doc_id"] == DocId and Live["mode"] == Mode
      ):
        Live["job_id"] = JobId
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
      try:
        # 작업이 끝난 직후 호출자의 후처리 ( 회의록 doc 상태 ) - 조회하는 쪽이 완료를 보기 전에 끝나야 한다
        if Job.get("on_done") is not None:
          Job["on_done"](Job)
      finally:
        Job["event"].set()

  # 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
  def live_start(self, body) -> tuple[int, dict]:
    if self.dify_fn is None:
      return 503, {"ok": False, "error_type": "DifyNotConfigured", "message": "Dify 가 설정되지 않았다"}
    Error, DocId, Mode = self._check_request(body)
    if Error is not None:
      return Error
    Live = {
      "live_id": uuid.uuid4().hex, "doc_id": DocId, "mode": Mode, "status": "running", "started_at_utc": _utc_now(),
      "finished_at_utc": None, "elapsed_seconds": None, "workflow_run_id": None, "dify_status": None,
      "dify_outputs": None, "job_id": None, "error": None,
    }
    Internal = {"record": Live, "started_monotonic": time.monotonic()}
    with self.meta_lock:
      # 라이브가 돌고 있거나 작업 잠금이 잡혀 있으면 생성 서버 슬롯이 겹친다
      if (self.live is not None and self.live["record"]["status"] == "running") or self.lock.locked():
        return 409, {"ok": False, "error_type": "Busy", "message": "다른 요청을 처리 중이다"}
      self.live = Internal
    Internal["thread"] = threading.Thread(target=self._live_main, args=(Internal,), daemon=True)
    try:
      Internal["thread"].start()
    except BaseException:
      # 스레드를 못 띄우면 레코드가 running 으로 남는다
      with self.meta_lock:
        self.live = None
      raise
    return 202, {"ok": True, "live_id": Live["live_id"]}

  def _live_log(self, Live: dict, Elapsed: float) -> None:
    # 로그에는 live_id · doc_id · mode · 상태 · 시간만 찍는다 - 키 · 헤더 · 본문은 찍지 않는다
    self.print_fn(f"live {Live['live_id']} doc={Live['doc_id']} mode={Live['mode']} status={Live['status']} elapsed_s={Elapsed:.1f}")

  def _live_main(self, Internal: dict) -> None:
    Live = Internal["record"]
    self._live_log(Live, 0.0)
    Finished = False

    def fail(Type: str, Message: str) -> None:
      Live["status"] = "failed"
      Live["error"] = {"error_type": Type, "message": Message}

    try:
      for Event in self.dify_fn({"doc_id": Live["doc_id"], "mode": Live["mode"]}, LIVE_USER):
        Kind = Event.get("event")
        Data = Event.get("data") if isinstance(Event.get("data"), dict) else {}
        if Kind == "workflow_started":
          Live["workflow_run_id"] = Data.get("workflow_run_id") or Event.get("workflow_run_id")
        elif Kind == "workflow_finished":
          Live["dify_status"] = Data.get("status")
          Live["dify_outputs"] = Data.get("outputs")
          Finished = True
      if not Finished:
        fail("NoFinishEvent", "워크플로 종료 이벤트 없이 스트림이 끝났다")
      elif Live["dify_status"] != "succeeded":
        fail("DifyWorkflowFailed", f"dify_status={Live['dify_status']}")
      elif Live["job_id"] is None:
        fail("NoJobSubmitted", "워크플로가 시연 API 에 작업을 제출하지 않았다")
      else:
        Live["status"] = "completed"
    except Exception as Error:
      fail(type(Error).__name__, str(Error))
    finally:
      # 어떤 경로로 끝나든 running 으로 남지 않는다
      if Live["status"] == "running":
        fail("Interrupted", "라이브 처리가 중단됐다")
      Elapsed = time.monotonic() - Internal["started_monotonic"]
      Live["elapsed_seconds"] = round(Elapsed, 1)
      Live["finished_at_utc"] = _utc_now()
      self._live_log(Live, Elapsed)

  def live_status(self) -> tuple[int, dict]:
    Internal = self.live
    if Internal is None:
      return 200, {"status": "idle"}
    Live = dict(Internal["record"])
    if Live["status"] == "running":
      Live["elapsed_seconds"] = round(time.monotonic() - Internal["started_monotonic"], 1)
    # 워크플로 출력 · 오류 문구에 실제 주인 이름이 섞이지 않게 기존 가림 함수를 통과시킨다
    return 200, self._mask(Live)

  # 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능 - 회의 · 할 일은 노트와 같은 층 규칙으로 서버가 거른다
  def meetings_request(self, method: str, path: str, query: dict, body) -> tuple:
    if self.meetings is None:
      return 503, {"ok": False, "error_type": "MeetingsNotConfigured", "message": "회의 기능이 설정되지 않았다"}
    Match = _MEETING_PATH.fullmatch(path)
    Task = _TASK_PATH.fullmatch(path)
    Spaces = path == _WORKSPACE_PATH
    if Match is None and Task is None and not Spaces:
      return 404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"}
    try:
      # 모든 경로에 viewer 가 필수이고 목록에 없는 보는 사람은 400 이다
      if method == "GET":
        Values = query.get("viewer", [])
        if len(Values) != 1 or not Values[0]:
          raise ValueError("viewer 가 필요하다")
        ViewerId = Values[0]
        Single = {key: values for key, values in query.items() if key != "viewer"}
        for key, values in Single.items():
          if len(values) != 1:
            raise ValueError(f"{key} 는 하나만 줄 수 있다")
        Params = {key: values[0] for key, values in Single.items()}
      else:
        if not isinstance(body, dict) or not isinstance(body.get("viewer"), str) or not body["viewer"]:
          raise ValueError("본문에 viewer 가 필요하다")
        ViewerId = body["viewer"]
        Params = {key: value for key, value in body.items() if key != "viewer"}
      Target = self._viewer_target(ViewerId)
      if Target is None:
        raise ValueError("viewers 에 없는 viewer 이다")
      Store = self.meetings
      if Spaces:
        if method != "GET" or Params:
          raise ValueError("워크스페이스 목록은 viewer 만 받는 GET 이다")
        return 200, self._mask({"workspaces": Store.list_workspaces(Target)})
      if Match is not None:
        MeetingId = Match.group(1)
        if method == "GET" and MeetingId is None:
          _only = {"from", "to"}
          if set(Params) - _only:
            raise ValueError(f"모르는 쿼리: {sorted(set(Params) - _only)}")
          Result = {"meetings": Store.list_meetings(Target, Params.get("from"), Params.get("to"))}
          return 200, self._mask(Result)
        if method == "GET":
          if Params:
            raise ValueError(f"모르는 쿼리: {sorted(Params)}")
          return 200, self._mask(Store.get_meeting(Target, MeetingId))
        if MeetingId is None:
          return 201, self._mask(Store.create_meeting(Target, Params))
        return 200, self._mask(Store.update_meeting(Target, MeetingId, Params))
      TaskId, Progress = Task.group(1), Task.group(2)
      if method == "GET":
        if TaskId is not None:
          return 404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"}
        _only = {"meeting", "assignee"}
        if set(Params) - _only:
          raise ValueError(f"모르는 쿼리: {sorted(set(Params) - _only)}")
        return 200, self._mask({"tasks": Store.list_tasks(Target, Params.get("meeting"), Params.get("assignee"))})
      if TaskId is None:
        return 201, self._mask(Store.create_task(Target, Params))
      if Progress:
        _only_keys = set(Params) - {"text"}
        if _only_keys or "text" not in Params:
          raise ValueError("진행 기록 본문은 { viewer, text } 이어야 한다")
        return 200, self._mask(Store.add_progress(Target, TaskId, Params["text"]))
      return 200, self._mask(Store.update_task(Target, TaskId, Params))
    except NotFoundError as Error:
      return 404, {"ok": False, "error_type": "NotFound", "message": str(Error)}
    except ValueError as Error:
      return 400, self._mask({"ok": False, "error_type": "BadRequest", "message": str(Error)})

  # ---- 회의록 투입 · 승인 게이트 · 판정 기록 보기 ----
  def attach_minutes(self, Store: MinutesStore) -> None:
    # 시작 때 저장된 901 doc 를 doc 목록에 올린다 - 실험 코퍼스 경로에는 아무것도 쓰지 않는다
    self.minutes = Store
    for Record in Store.docs():
      if Record["status"] == "running":
        # 서버가 꺼져 작업이 끝나지 못한 doc 는 조용히 두지 않고 실패로 남긴다
        Record = self._fail_minutes(Record["doc_id"], "Interrupted : 서버가 다시 시작돼 작업이 끝나지 못했다")
      self.docs[Record["doc_id"]] = source_doc_of(Record)
      self.raw_sha[Record["doc_id"]] = Record["raw_sha256"]

  def _fail_minutes(self, DocId: str, Error: str) -> dict:
    # 실패한 투입은 기록으로 남기고 회의 연결은 풀어 다시 투입할 수 있게 한다
    Saved = self.minutes.update(DocId, status="failed", error=Error)
    if self.meetings is not None:
      self.meetings.unlink_minutes(Saved["meeting_id"], DocId)
    return Saved

  def _minutes_overlay(self, Notes: list, Mode: str, SkipDoc) -> tuple:
    if self.minutes is None:
      return Notes, 0, set()
    Approved = []
    for Record in self.minutes.docs():
      if Record["mode"] == Mode and Record["status"] == "decided" and Record["doc_id"] != SkipDoc:
        Approved += Record["approved_notes"]
    Ids = {Note["note_id"] for Note in Notes} | {Note["note_id"] for Note in Approved}
    Dropped = 0
    Out = []
    for Note in Approved:
      Note = dict(Note)
      Up = [Target for Target in Note["upward_links"] if Target in Ids]
      Down = [Link for Link in Note["downward_conditional_links"] if Link["target_id"] in Ids]
      Dropped += len(Note["upward_links"]) - len(Up) + len(Note["downward_conditional_links"]) - len(Down)
      Note["upward_links"], Note["downward_conditional_links"] = Up, Down
      Out.append(Note)
    return Notes + Out, Dropped, {Note["note_id"] for Note in Out}

  def _viewer_params(self, method: str, query: dict, body) -> tuple:
    if method == "GET":
      Values = query.get("viewer", [])
      if len(Values) != 1 or not Values[0]:
        raise ValueError("viewer 가 필요하다")
      Params = {}
      for Key, Many in query.items():
        if Key == "viewer":
          continue
        if len(Many) != 1:
          raise ValueError(f"{Key} 는 하나만 줄 수 있다")
        Params[Key] = Many[0]
      return Values[0], Params
    if not isinstance(body, dict) or not isinstance(body.get("viewer"), str) or not body["viewer"]:
      raise ValueError("본문에 viewer 가 필요하다")
    return body["viewer"], {Key: Value for Key, Value in body.items() if Key != "viewer"}

  def minutes_request(self, method: str, path: str, query: dict, body) -> tuple:
    if self.meetings is None:
      return 503, {"ok": False, "error_type": "MeetingsNotConfigured", "message": "회의 기능이 설정되지 않았다"}
    if self.minutes is None:
      return 503, {"ok": False, "error_type": "MinutesNotConfigured", "message": "회의록 투입이 설정되지 않았다"}
    Proposal = _PROPOSAL_PATH.fullmatch(path)
    if path != _MINUTES_PATH and Proposal is None:
      return 404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"}
    try:
      ViewerId, Params = self._viewer_params(method, query, body)
      Target = self._viewer_target(ViewerId)
      if Target is None:
        raise ValueError("viewers 에 없는 viewer 이다")
      if path == _MINUTES_PATH:
        if method != "POST":
          raise ValueError("회의록 투입은 POST 다")
        return self._minutes_submit(Target, Params)
      DocId, Action = Proposal.group(1), Proposal.group(2)
      if Action == "/decide":
        if method != "POST":
          raise ValueError("승인 · 반려는 POST 다")
        return self._decide(Target, DocId, Params)
      if method != "GET" or Params:
        raise ValueError("제안 조회는 viewer 만 받는 GET 이다")
      if DocId is None:
        return 200, self._mask({"proposals": self._proposal_list(Target)})
      if Action == "/trace":
        return 200, self._mask(self._trace(Target, DocId))
      return 200, self._mask(self._proposal_detail(Target, DocId))
    except NotFoundError as Error:
      return 404, {"ok": False, "error_type": "NotFound", "message": str(Error)}
    except AlreadyLinkedError as Error:
      return 409, {"ok": False, "error_type": "MinutesAlreadyLinked", "message": str(Error)}
    except ConflictError as Error:
      return 409, {"ok": False, "error_type": "Conflict", "message": str(Error)}
    except ValueError as Error:
      return 400, self._mask({"ok": False, "error_type": "BadRequest", "message": str(Error)})

  def _minutes_submit(self, Target, Params: dict) -> tuple:
    if set(Params) != {"meeting_id", "mode", "text"}:
      raise ValueError("본문은 { viewer, meeting_id, mode, text } 이어야 한다")
    MeetingId, Mode, Text = Params["meeting_id"], Params["mode"], Params["text"]
    if not isinstance(MeetingId, str) or not isinstance(Mode, str) or not isinstance(Text, str):
      raise ValueError("meeting_id · mode · text 는 문자열이어야 한다")
    if Target[0] != "개인":
      raise ValueError("회의록은 개인 보는 사람만 투입한다")
    try:
      Meeting = self.meetings.get_meeting(Target, MeetingId)
    except NotFoundError:
      raise ValueError("볼 수 없는 회의다") from None
    # 사용자 결정 2026-10-23 : 개인 일정에는 회의록 투입을 막는다 - 개인 문서의 팀 워크스페이스 ( source_team ) 를 지어내지 않는다
    if Meeting["workspace"]["layer"] == "개인":
      raise ValueError("개인 일정에는 회의록을 투입하지 않는다")
    Name = self.meetings.viewer_name(Target)
    if Name not in Meeting["attendees"]:
      raise ValueError("회의 참석자만 회의록을 투입한다")
    if Mode not in self.cells:
      raise ValueError(f"불러온 모드가 아니다: {list(self.cells)}")
    if not Text.strip() or len(Text) > TEXT_MAX_CHARS:
      raise ValueError(f"text 는 1 ~ {TEXT_MAX_CHARS}자여야 한다")
    if Meeting["minutes_doc_id"] is not None:
      raise AlreadyLinkedError("이미 회의록이 연결된 회의다")
    Record = self.minutes.create(Meeting, Mode, Text, Name, self.meetings.now_fn())
    DocId = Record["doc_id"]
    try:
      self.meetings.link_minutes(MeetingId, DocId)
    except Exception as Error:
      self.minutes.update(DocId, status="failed", error=f"{type(Error).__name__} : {Error}")
      raise
    self.docs[DocId] = source_doc_of(Record)
    self.raw_sha[DocId] = Record["raw_sha256"]
    Status, Body = self.submit({"doc_id": DocId, "mode": Mode}, on_done=self._minutes_done)
    if Status != 202:
      # 잠금이 잡혀 있으면 doc 는 실패로 남기고 회의 연결은 되돌린다
      self._fail_minutes(DocId, Body.get("error_type", "Unknown"))
      return Status, Body
    self.minutes.update(DocId, job_id=Body["job_id"])
    return 202, {"ok": True, "doc_id": DocId, "job_id": Body["job_id"]}

  def _minutes_done(self, Job: dict) -> None:
    # 작업이 끝난 시점에 doc 상태를 정한다 - 작업이 failed 이거나 decompose.ok 가 False 면 failed, 그 밖은 승인 대기. 노트는 아직 볼트에 넣지 않는다
    DocId = Job["doc_id"]
    try:
      Result = Job["result"] or {}
      Fields = {"job_id": Job["job_id"]}
      if Job["status"] != "completed":
        Fields.update(status="failed", error=f"{Result.get('error_type', 'Unknown')} : {Result.get('message', '')}")
      else:
        Fields["request_dir"] = Result["request_dir"]
        if not Result["decompose"]["ok"]:
          Fields.update(status="failed", error=f"DecomposeFailed : {Result['decompose']['error']}")
        else:
          Fields.update(status="awaiting_approval" if Result["notes"] else "decided", note_count=len(Result["notes"]))
      Saved = self.minutes.update(DocId, **Fields)
      if Saved["status"] == "failed":
        self._fail_minutes(DocId, Saved["error"])
    except Exception as Error:
      self._fail_minutes(DocId, f"{type(Error).__name__} : {Error}")

  def _proposal_doc(self, Target, DocId: str) -> tuple:
    # 볼 수 없는 회의의 doc 는 없는 doc 와 같은 404 다
    Record = self.minutes.get(DocId)
    if Record is None:
      raise NotFoundError("제안을 찾을 수 없다")
    try:
      Meeting = self.meetings.get_meeting(Target, Record["meeting_id"])
    except NotFoundError:
      raise NotFoundError("제안을 찾을 수 없다") from None
    return Record, Meeting

  def _proposal_notes(self, Record: dict) -> tuple:
    # 작업 산출물 ( log.jsonl · new_notes.jsonl ) 에서 노트별 ( place 항목, 응답용 노트, 노트 레코드 ) 를 읽는다
    if Record["request_dir"] is None:
      return [], []
    Dir = Record["request_dir"]
    with open(os.path.join(Dir, "log.jsonl"), encoding="utf-8") as File:
      Log = [json.loads(Line) for Line in File if Line.strip()]
    New = _read_vault_notes(os.path.join(Dir, "new_notes.jsonl"))
    Places = [Entry for Entry in Log if Entry["entry_type"] == "place"]
    Payload = self._notes_payload(Log, New)
    ById = {Note.note_id: Note for Note in New}
    return Log, [(Entry, Item, ById.get(Item["note_id"])) for Entry, Item in zip(Places, Payload)]

  def _decision_counts(self, Record: dict) -> dict:
    Approved = sum(1 for Item in Record["decisions"].values() if Item["decision"] == "approve")
    Rejected = len(Record["decisions"]) - Approved
    return {"approved": Approved, "rejected": Rejected, "pending": Record["note_count"] - len(Record["decisions"])}

  def _proposal_list(self, Target) -> list:
    Out = []
    for Record in self.minutes.docs():
      try:
        self.meetings.get_meeting(Target, Record["meeting_id"])
      except NotFoundError:
        continue
      Out.append({
        "doc_id": Record["doc_id"], "meeting_id": Record["meeting_id"], "mode": Record["mode"], "status": Record["status"],
        "note_count": Record["note_count"], **self._decision_counts(Record),
      })
    return sorted(Out, key=lambda Item: Item["doc_id"])

  def _proposal_detail(self, Target, DocId: str) -> dict:
    Record, _ = self._proposal_doc(Target, DocId)
    Notes = []
    if Record["status"] in ("awaiting_approval", "decided"):
      _, Rows = self._proposal_notes(Record)
      Pairs = visible_pairs_for(Target[0], Target[1], self.membership)
      Known = self._known_notes(Record["mode"], [Row[2] for Row in Rows if Row[2] is not None])
      for Entry, Item, Note in Rows:
        # 링크 대상이 이 보는 사람에게 보이지 않으면 id 가 새어 나가므로 빼고 수만 센다
        Up = [Id for Id in Item["upward_links"] if self._candidate_visible(Id, Known, Pairs)]
        Down = [
          {"target_id": Link["target_id"], "target_layer": Link["target_layer"]}
          for Link in Item["downward_links"] if (Link["target_layer"], self._link_group(Link, Note)) in Pairs
        ]
        Notes.append({
          "note_index": Entry["note_index"], "title": Item["title"], "layer": Item["layer"], "group_label": Item["group_label"],
          "body": (Note.body if self.show_names else f"( 본문 {len(Note.body)}자 가림 )") if Note is not None else None,
          "source_segment_ids": Item["source_segment_ids"], "upward_links": Up, "downward_links": Down,
          "hidden_links": len(Item["upward_links"]) - len(Up) + len(Item["downward_links"]) - len(Down),
          "problems": Item["problems"], "decision": Record["decisions"].get(str(Entry["note_index"])),
        })
    return {
      "doc_id": Record["doc_id"], "meeting_id": Record["meeting_id"], "mode": Record["mode"], "status": Record["status"],
      "error": Record["error"], "note_count": Record["note_count"], **self._decision_counts(Record), "notes": Notes,
    }

  def _link_group(self, Link: dict, Note) -> object:
    # 하향 조건부 링크의 대상 그룹은 노트 레코드의 가시성 조건에 있다
    for Item in Note.downward_conditional_links:
      if Item.target_id == Link["target_id"]:
        return Item.visibility_condition["group"]
    raise ValueError("링크의 가시성 조건을 찾을 수 없다")

  def _known_notes(self, Mode: str, Extra: list) -> dict:
    # 후보 · 링크 대상의 ( 층, 그룹 ) 을 찾는 표 - 기본 볼트, 승인된 회의록 노트, 이 제안의 새 노트
    Known = {Note.note_id: (Note.layer, Note.group) for Note in self.cells[Mode]["notes"]}
    for Record in self.minutes.docs():
      if Record["mode"] == Mode:
        for Note in Record["approved_notes"]:
          Known[Note["note_id"]] = (Note["layer"], Note["group"])
    for Note in Extra:
      Known[Note.note_id] = (Note.layer, Note.group)
    return Known

  @staticmethod
  def _candidate_visible(NoteId: str, Known: dict, Pairs: set) -> bool:
    # 알 수 없는 노트는 보이는지 확인할 수 없으므로 가린다
    return NoteId in Known and Known[NoteId] in Pairs

  def _trace(self, Target, DocId: str) -> dict:
    # 판정 기록 보기는 감사 기록을 보는 사람의 보기 범위 안에서만 보인다 - 보이지 않는 후보의 제목 · 근거는 누출 경로다 ( 3절 14 )
    Record, _ = self._proposal_doc(Target, DocId)
    if Record["request_dir"] is None:
      raise ConflictError("판정 기록이 아직 없다")
    Log, Rows = self._proposal_notes(Record)
    Pairs = visible_pairs_for(Target[0], Target[1], self.membership)
    Known = self._known_notes(Record["mode"], [Row[2] for Row in Rows if Row[2] is not None])
    Decompose = next(Entry for Entry in Log if Entry["entry_type"] == "decompose")
    Places = []
    for Entry, _, _ in Rows:
      Visible, HiddenIds = [], set()
      for Cand in Entry["candidates"]:
        if self._candidate_visible(Cand["id"], Known, Pairs):
          Visible.append({
            "id": Cand["id"], "layer": Cand["layer"], "group_label": group_label(Cand["layer"], Known[Cand["id"]][1], self.labels),
            "title": Cand["title"],
          })
        else:
          HiddenIds.add(Cand["id"])
      VisibleIds = {Cand["id"] for Cand in Visible}
      Verdict = Entry["verdict"]
      Up = [Id for Id in (Verdict["upward_links"] if Verdict else []) if Id in VisibleIds]
      Down = [Id for Id in (Verdict["downward_target_ids"] if Verdict else []) if Id in VisibleIds]
      Chosen = (len(Verdict["upward_links"]) + len(Verdict["downward_target_ids"])) if Verdict else 0
      Places.append({
        "note_index": Entry["note_index"], "layer": Verdict["layer"] if Verdict else None, "upward_links": Up, "downward_links": Down,
        "hidden_links": Chosen - len(Up) - len(Down),
        # 문제 문구에 가려진 후보 id 가 들어 있으면 그 문구는 내보내지 않는다
        "problems": [Text if not any(Id in Text for Id in HiddenIds) else "( 가려진 후보 관련 )" for Text in Entry["problems"]],
        "candidates": Visible, "hidden_candidates": len(HiddenIds),
        "rationale": Verdict["rationale"] if Verdict and not HiddenIds else None,
        "rationale_hidden": bool(HiddenIds and Verdict),
      })
    return {
      "doc_id": Record["doc_id"], "meeting_id": Record["meeting_id"], "mode": Record["mode"],
      "decompose": {
        "ok": Decompose["ok"], "error": Decompose["error"],
        "notes": [
          {"note_index": Index, "title": Note["title"], "segment_ids": list(Note["source_segment_ids"])}
          for Index, Note in enumerate(Decompose["notes"])
        ],
      },
      "places": Places,
    }

  def _decide(self, Target, DocId: str, Params: dict) -> tuple:
    # 승인 게이트는 에이전트 결과를 쓰기 전에 사람이 확인하는 문이며 승격 ( 층 이동 ) 이 아니다 - 층 · 그룹 · 링크는 바꿀 수 없다
    Record, Meeting = self._proposal_doc(Target, DocId)
    Name = self.meetings.viewer_name(Target)
    if Target[0] != "개인" or Name not in Meeting["attendees"]:
      raise ValueError("회의 참석자 ( 개인 보는 사람 ) 만 승인 · 반려한다")
    if set(Params) != {"decisions"}:
      raise ValueError("본문은 { viewer, decisions } 이어야 한다 ( 층 · 그룹 · 링크는 바꿀 수 없다 )")
    Items = Params["decisions"]
    if not isinstance(Items, list) or not Items:
      raise ValueError("decisions 는 비어 있지 않은 목록이어야 한다")
    with self.decide_lock:
      Record = self.minutes.get(DocId)
      if Record["status"] != "awaiting_approval":
        raise ConflictError(f"승인 대기 상태가 아니다: {Record['status']}")
      _, Rows = self._proposal_notes(Record)
      ByIndex = {Entry["note_index"]: (Item, Note) for Entry, Item, Note in Rows}
      Seen = set()
      for Item in Items:
        if not isinstance(Item, dict) or set(Item) != {"note_index", "decision"}:
          raise ValueError("decisions 항목은 { note_index, decision } 만 가질 수 있다 ( 층 · 그룹 · 링크는 바꿀 수 없다 )")
        Index, Decision = Item["note_index"], Item["decision"]
        if not isinstance(Index, int) or isinstance(Index, bool) or Index not in ByIndex:
          raise ValueError(f"알 수 없는 note_index: {Index!r}")
        if Decision not in ("approve", "reject"):
          raise ValueError(f"decision 은 approve 또는 reject 이다: {Decision!r}")
        if str(Index) in Record["decisions"] or Index in Seen:
          raise ValueError(f"이미 결정된 note_index 는 바꾸지 않는다: {Index}")
        if Decision == "approve" and ByIndex[Index][1] is None:
          raise ValueError(f"배치에 실패한 노트는 승인할 수 없다: {Index}")
        Seen.add(Index)
      At = self.meetings.now_fn().strftime("%Y-%m-%dT%H:%M")
      Decisions = dict(Record["decisions"])
      for Item in Items:
        Decisions[str(Item["note_index"])] = {"decision": Item["decision"], "by": Name, "at": At}
      Fields = {"decisions": Decisions}
      if len(Decisions) == Record["note_count"]:
        Rejected = {ByIndex[int(Key)][1].note_id for Key, Value in Decisions.items() if Value["decision"] == "reject" and ByIndex[int(Key)][1] is not None}
        Approved, Dropped = [], 0
        for Key in sorted(Decisions, key=int):
          if Decisions[Key]["decision"] != "approve":
            continue
          Note = asdict(ByIndex[int(Key)][1])
          Up = [Id for Id in Note["upward_links"] if Id not in Rejected]
          Down = [Link for Link in Note["downward_conditional_links"] if Link["target_id"] not in Rejected]
          Dropped += len(Note["upward_links"]) - len(Up) + len(Note["downward_conditional_links"]) - len(Down)
          Note["upward_links"], Note["downward_conditional_links"] = Up, Down
          Approved.append(Note)
        Fields.update(status="decided", approved_notes=Approved, approved_links_dropped=Dropped)
      Saved = self.minutes.update(DocId, **Fields)
    return 200, self._mask({"ok": True, "doc_id": DocId, "status": Saved["status"], **self._decision_counts(Saved)})

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
      elif urlsplit(self.path).path == "/live":
        Status, Obj = App.live_status()
        self._send(Status, Obj)
      elif _MEETING_PATH.fullmatch(urlsplit(self.path).path) or _TASK_PATH.fullmatch(urlsplit(self.path).path) or urlsplit(self.path).path == _WORKSPACE_PATH:
        Parts = urlsplit(self.path)
        Status, Obj = App.meetings_request("GET", Parts.path, parse_qs(Parts.query, keep_blank_values=True), None)
        self._send(Status, Obj)
      elif _PROPOSAL_PATH.fullmatch(urlsplit(self.path).path):
        Parts = urlsplit(self.path)
        Status, Obj = App.minutes_request("GET", Parts.path, parse_qs(Parts.query, keep_blank_values=True), None)
        self._send(Status, Obj)
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

    def _read_json_body(self, Limit=MAX_BODY_BYTES):
      # POST /run 과 POST /jobs 가 같은 길이 · JSON 검사를 쓴다 - 오류면 400 을 보내고 _BAD_BODY ( JSON null 도 정상 본문이라 None 을 쓰지 않는다 )
      try:
        Length = int(self.headers.get("Content-Length", ""))
      except ValueError:
        Length = -1
      # 길이를 모르거나 상한을 넘는 본문은 읽지 않는다
      if Length < 0 or Length > Limit:
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": "본문 길이가 없거나 너무 크다"})
        return _BAD_BODY
      try:
        return json.loads(self.rfile.read(Length).decode("utf-8"))
      except (UnicodeDecodeError, json.JSONDecodeError):
        self._send(400, {"ok": False, "error_type": "BadRequest", "message": "JSON 이 아니다"})
        return _BAD_BODY

    def do_POST(self) -> None:
      Path = urlsplit(self.path).path
      if self.path == Path and (_MEETING_PATH.fullmatch(Path) or _TASK_PATH.fullmatch(Path)):
        Body = self._read_json_body()
        if Body is _BAD_BODY:
          return
        Status, Obj = App.meetings_request("POST", Path, {}, Body)
        self._send(Status, Obj)
        return
      if self.path == Path and (Path == _MINUTES_PATH or _PROPOSAL_PATH.fullmatch(Path)):
        Body = self._read_json_body(MINUTES_MAX_BODY_BYTES if Path == _MINUTES_PATH else MAX_BODY_BYTES)
        if Body is _BAD_BODY:
          return
        Status, Obj = App.minutes_request("POST", Path, {}, Body)
        self._send(Status, Obj)
        return
      if self.path not in ("/run", "/jobs", "/live"):
        self._send(404, {"ok": False, "error_type": "NotFound", "message": "알 수 없는 경로"})
        return
      Body = self._read_json_body()
      if Body is _BAD_BODY:
        return
      Status, Obj = {"/run": App.run, "/jobs": App.submit, "/live": App.live_start}[self.path](Body)
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
  # 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
  # 기본 URL · 기본 변수 이름을 두지 않는다 - 둘 중 하나만 주면 라이브 투입이 반쯤 설정된 채로 뜬다
  Parser.add_argument("--dify-url", default=None)
  Parser.add_argument("--dify-key-env", default=None)
  # 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능 - 회의 · 할 일은 노트와 같은 층 규칙으로 서버가 거른다
  Parser.add_argument("--meetings-file", default=None)
  Parser.add_argument("--meetings-seed", default=None)
  # 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 문서는 합성 시연 코퍼스 차수 901. 시연 작업 폴더에만 쓴다
  Parser.add_argument("--minutes-dir", default=None)
  Args = Parser.parse_args(argv)
  if Args.minutes_dir is not None and Args.meetings_file is None:
    Parser.error("--minutes-dir 는 --meetings-file 과 함께 줘야 한다")
  if (Args.dify_url is None) != (Args.dify_key_env is None):
    Parser.error("--dify-url 과 --dify-key-env 는 함께 줘야 한다")
  # 예시만 주면 쓸 파일이 없다
  if Args.meetings_seed is not None and Args.meetings_file is None:
    Parser.error("--meetings-seed 는 --meetings-file 과 함께 줘야 한다")
  return Args


# 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
def dify_fn_from_args(Args, environ=None):
  if Args.dify_url is None:
    return None
  Environ = os.environ if environ is None else environ
  Key = Environ.get(Args.dify_key_env, "")
  # 키가 비었거나 없으면 멈춘다 - 메시지에는 변수 이름만 넣고 값은 넣지 않는다
  if not Key:
    raise SystemExit(f"환경 변수 {Args.dify_key_env} 가 비었거나 없다")
  return make_dify_fn(Args.dify_url, Key)


def meetings_from_args(Args, App, repo_dir=REPO_DIR):
  if Args.meetings_file is None:
    return None
  # 가린 실행 ( 실제 코퍼스 ) 에는 합성 회의 데이터를 섞지 않는다
  if not App.show_names:
    raise SystemExit("회의 기능은 합성 시연 실행에서만 켠다")
  Path = os.path.realpath(os.path.expanduser(Args.meetings_file))
  Repo = os.path.realpath(repo_dir)
  # 저장소 안에 쓰면 시연 중 바뀐 회의 파일이 커밋에 섞인다
  if os.path.commonpath([Repo, Path]) == Repo:
    raise SystemExit("회의 파일은 저장소 밖 시연 작업 폴더에 둔다")
  Seed = os.path.expanduser(Args.meetings_seed) if Args.meetings_seed is not None else None
  return MeetingStore(Path, Seed, App.membership, App.labels)


def minutes_from_args(Args, App, repo_dir=REPO_DIR):
  if Args.minutes_dir is None:
    return None
  # 가린 실행 ( 실제 코퍼스 ) 에는 합성 회의록을 섞지 않는다
  if not App.show_names:
    raise SystemExit("회의록 투입은 합성 시연 실행에서만 켠다")
  Path = os.path.realpath(os.path.expanduser(Args.minutes_dir))
  Repo = os.path.realpath(repo_dir)
  # 저장소 안에 쓰면 시연 중 바뀐 회의록 파일이 커밋에 섞인다
  if os.path.commonpath([Repo, Path]) == Repo:
    raise SystemExit("회의록 폴더는 저장소 밖 시연 작업 폴더에 둔다")
  return MinutesStore(Path)


def _print_flush(Line: str) -> None:
  print(Line, flush=True)


def main(argv=None) -> None:
  Args = parse_args(argv)
  App = DemoApp(
    Args.run_dir, chat_fn=chat, embed_backend=None, commit_fn=lambda: git_head_commit(REPO_DIR),
    work_root=DEFAULT_WORK_ROOT, print_fn=_print_flush, dify_fn=dify_fn_from_args(Args),
  )
  App.meetings = meetings_from_args(Args, App)
  Minutes = minutes_from_args(Args, App)
  if Minutes is not None:
    App.attach_minutes(Minutes)
  Server = make_server(App, Args.host, Args.port, cors_origin=Args.cors_origin)
  _print_flush(f"serve host={Args.host} port={Args.port} modes={len(App.cells)} docs={len(App.docs)}")
  Server.serve_forever()


if __name__ == "__main__":
  main()
