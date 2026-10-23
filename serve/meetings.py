# 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능. 회의 · 할 일은 노트와 같은 층 규칙으로 서버가 거른다. 합성 데이터만, 실험 경로와 무관
import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime

from labeling.gold import visible_pairs_for

MEETING_STATUS = ("scheduled", "done", "cancelled")
TASK_STATUS = ("todo", "doing", "done")
TASK_SOURCE = ("human", "agent_proposal", "agent_confirmed")
LAYERS = ("전사", "팀", "개인")
# 이 단계에서 API 로 만들 수 있는 할 일 출처는 사람뿐이다 - 에이전트 제안은 다음 단계의 경로로만 들어온다
API_SOURCES = ("human",)
PROGRESS_MAX_CHARS = 500
TITLE_MAX_CHARS = 200

_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MEETING_KEYS = (
  "meeting_id", "title", "starts_at", "ends_at", "workspace", "attendees", "agenda", "minutes_doc_id", "status",
)
_TASK_KEYS = ("task_id", "meeting_id", "title", "workspace", "assignee", "due", "status", "source", "progress")
_MEETING_INPUT = ("title", "starts_at", "ends_at", "workspace", "attendees", "agenda", "minutes_doc_id", "status")
_TASK_INPUT = ("title", "meeting_id", "workspace", "assignee", "due", "status", "source")
_TASK_UPDATE = ("title", "assignee", "due", "status")
# 사용자 결정 2026-10-23 ( 지침 v3.1 · 3절 26 · 27 ) : 회의 문서는 할 일 배정 역할이 낸 결과를 사람이 확정하기 전까지 제안으로 둔다
DOC_STATUS = ("proposal", "confirmed")
_DOC_KEYS = (
  "doc_id", "meeting_id", "workspace", "decisions", "summary", "task_ids", "status", "assign_id", "created_at", "confirmed_by",
  "confirmed_at",
)
_EMPTY = {"version": 1, "meetings": [], "tasks": []}


class AlreadyLinkedError(Exception):
  # 회의록이 이미 연결된 회의 - 409 로 돌려준다
  pass


class NotFoundError(Exception):
  # 볼 수 없는 항목과 없는 항목을 구분하지 않는다 - 존재 여부를 드러내지 않으려고 같은 오류를 쓴다
  pass


def _parse_time(value, name: str) -> datetime:
  if not isinstance(value, str) or not _TIME.match(value):
    raise ValueError(f"{name} 는 YYYY-MM-DDTHH:MM 형식이어야 한다: {value!r}")
  try:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")
  except ValueError:
    raise ValueError(f"{name} 가 올바른 시각이 아니다: {value!r}") from None


def _parse_date(value, name: str) -> str:
  if not isinstance(value, str) or not _DATE.match(value):
    raise ValueError(f"{name} 는 YYYY-MM-DD 형식이어야 한다: {value!r}")
  try:
    datetime.strptime(value, "%Y-%m-%d")
  except ValueError:
    raise ValueError(f"{name} 가 올바른 날짜가 아니다: {value!r}") from None
  return value


def _only_keys(body, allowed: tuple, what: str) -> None:
  if not isinstance(body, dict):
    raise ValueError(f"{what} 본문이 객체가 아니다")
  extra = sorted(set(body) - set(allowed))
  # 모르는 키를 조용히 버리면 보낸 값이 반영된 줄 안다
  if extra:
    raise ValueError(f"{what} 에서 바꿀 수 없거나 모르는 키: {extra}")


def _str_list(value, name: str) -> list:
  if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
    raise ValueError(f"{name} 는 비어 있지 않은 문자열 목록이어야 한다")
  return list(value)


class MeetingStore:
  def __init__(self, path, seed_path, membership, owner_labels: dict, now_fn=None) -> None:
    self.path = path
    self.membership = membership
    # 실제 주인 이름 → 표시 이름. 회의 데이터에는 표시 이름이 들어 있다
    self.labels = dict(owner_labels)
    self.owner_of = {label: owner for owner, label in self.labels.items()}
    # 표시 이름이 겹치면 참석자를 한 사람으로 정할 수 없다
    if len(self.owner_of) != len(self.labels):
      raise ValueError("주인 표시 이름이 겹친다")
    self.teams = sorted({team for teams in membership.teams_by_owner.values() for team in teams})
    self.now_fn = now_fn or datetime.now
    self.lock = threading.Lock()
    self._load_or_seed(seed_path)
    self._check_loaded()

  # ---- 저장 ----
  def _load_or_seed(self, seed_path) -> None:
    folder = os.path.dirname(os.path.abspath(self.path))
    os.makedirs(folder, exist_ok=True)
    if not os.path.exists(self.path):
      # 파일이 없을 때만 예시를 그대로 복사한다 - 있는 파일은 덮어쓰지 않는다
      if seed_path is not None:
        Temp = tempfile.NamedTemporaryFile(dir=folder, delete=False)
        Temp.close()
        shutil.copyfile(seed_path, Temp.name)
        os.replace(Temp.name, self.path)
      else:
        self.data = json.loads(json.dumps(_EMPTY))
        self._save()
        return
    try:
      with open(self.path, encoding="utf-8") as File:
        self.data = json.load(File)
    except json.JSONDecodeError as Error:
      # 깨진 파일을 비어 있는 것으로 보고 덮어쓰면 기록이 사라진다
      raise ValueError(f"회의 파일의 JSON 이 깨졌다: {self.path} ( {Error} )") from None

  def _save(self) -> None:
    folder = os.path.dirname(os.path.abspath(self.path))
    descriptor, temp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
      with os.fdopen(descriptor, "w", encoding="utf-8") as File:
        json.dump(self.data, File, ensure_ascii=False, indent=2)
        File.write("\n")
        File.flush()
        os.fsync(File.fileno())
      os.replace(temp, self.path)
    except BaseException:
      if os.path.exists(temp):
        os.remove(temp)
      raise

  def _check_loaded(self) -> None:
    # 시작 때도 새로 쓸 때와 같은 규칙을 모든 항목에 적용한다 - 규칙 밖 데이터가 파일에 있으면 조용히 받지 않고 멈춘다 ( 지침 9절 조용한 실패 )
    if not isinstance(self.data, dict) or self.data.get("version") != 1:
      raise ValueError("회의 파일 version 이 1 이 아니다")
    for name, keys in (("meetings", _MEETING_KEYS), ("tasks", _TASK_KEYS)):
      rows = self.data.get(name)
      if not isinstance(rows, list):
        raise ValueError(f"회의 파일의 {name} 가 목록이 아니다")
      for row in rows:
        if not isinstance(row, dict) or any(key not in row for key in keys):
          raise ValueError(f"회의 파일의 {name} 항목에 필수 키가 없다")
        self._workspace(row["workspace"])
    for name, key in (("meetings", "meeting_id"), ("tasks", "task_id")):
      ids = [row[key] for row in self.data[name]]
      if len(set(ids)) != len(ids):
        raise ValueError(f"회의 파일의 {name} 에 id 중복이 있다")
    meeting_workspace = {}
    for row in self.data["meetings"]:
      try:
        self._check_meeting_fields({key: row[key] for key in _MEETING_INPUT})
      except ValueError as Error:
        raise ValueError(f"회의 파일의 회의 {row['meeting_id']} 가 규칙에 맞지 않는다: {Error}") from None
      meeting_workspace[row["meeting_id"]] = row["workspace"]
    # documents 는 선택 키다 - 없으면 빈 목록으로 읽는다
    documents = self.data.setdefault("documents", [])
    if not isinstance(documents, list):
      raise ValueError("회의 파일의 documents 가 목록이 아니다")
    for row in self.data["tasks"]:
      try:
        # source 는 API 로 만들 때만 사람으로 제한한다 - 시작 때는 agent_proposal · agent_confirmed 도 받는다 ( API 는 만들 수 없지만 파일에는 있을 수 있다 )
        self._check_task_fields({key: row[key] for key in ("title", "workspace", "assignee", "due", "status", "source")})
        self._check_progress(row["progress"])
      except ValueError as Error:
        raise ValueError(f"회의 파일의 할 일 {row['task_id']} 가 규칙에 맞지 않는다: {Error}") from None
      meeting_id = row["meeting_id"]
      if meeting_id is None:
        continue
      if meeting_id not in meeting_workspace:
        raise ValueError(f"회의 파일의 할 일 {row['task_id']} 가 없는 회의 {meeting_id!r} 에 연결돼 있다 ( 연결 규칙 )")
      if row["workspace"] != meeting_workspace[meeting_id]:
        raise ValueError(f"회의 파일의 할 일 {row['task_id']} 가 다른 workspace 의 회의 {meeting_id} 에 연결돼 있다 ( 연결 규칙 )")
    task_ids = {row["task_id"] for row in self.data["tasks"]}
    document_ids = [row.get("doc_id") if isinstance(row, dict) else None for row in documents]
    if len(set(document_ids)) != len(document_ids):
      raise ValueError("회의 파일의 documents 에 id 중복이 있다")
    for row in documents:
      try:
        self._check_document(row, meeting_workspace, task_ids)
      except ValueError as Error:
        raise ValueError(f"회의 파일의 회의 문서 {row.get('doc_id') if isinstance(row, dict) else row!r} 가 규칙에 맞지 않는다: {Error}") from None

  def _check_document(self, row, meeting_workspace: dict, task_ids: set) -> None:
    if not isinstance(row, dict) or any(key not in row for key in _DOC_KEYS):
      raise ValueError("필수 키가 없다")
    if row["meeting_id"] not in meeting_workspace:
      raise ValueError("없는 회의에 연결돼 있다")
    # 회의 문서는 연결한 회의와 같은 워크스페이스여야 한다 - 보기 규칙이 회의와 같다
    if self._workspace(row["workspace"]) != meeting_workspace[row["meeting_id"]]:
      raise ValueError("연결한 회의와 workspace 가 다르다")
    _str_list(row["decisions"], "decisions")
    if not isinstance(row["summary"], str) or not isinstance(row["assign_id"], str) or not row["assign_id"]:
      raise ValueError("summary · assign_id 는 문자열이어야 한다")
    _str_list(row["task_ids"], "task_ids")
    if any(task_id not in task_ids for task_id in row["task_ids"]):
      raise ValueError("없는 할 일을 가리킨다")
    if row["status"] not in DOC_STATUS:
      raise ValueError(f"알 수 없는 문서 status: {row['status']!r}")
    _parse_time(row["created_at"], "created_at")
    if row["status"] == "confirmed":
      if not isinstance(row["confirmed_by"], str) or not row["confirmed_by"]:
        raise ValueError("확정한 문서에는 confirmed_by 가 있어야 한다")
      _parse_time(row["confirmed_at"], "confirmed_at")
    elif row["confirmed_by"] is not None or row["confirmed_at"] is not None:
      raise ValueError("제안 문서에는 confirmed_by · confirmed_at 이 없어야 한다")

  def _check_progress(self, progress) -> None:
    if not isinstance(progress, list):
      raise ValueError("progress 가 목록이 아니다")
    for item in progress:
      if not isinstance(item, dict) or set(item) != {"at", "author", "text"}:
        raise ValueError("progress 항목은 { at, author, text } 이어야 한다")
      _parse_time(item["at"], "progress.at")
      if item["author"] not in self.owner_of:
        raise ValueError(f"progress 작성자를 알 수 없다: {item['author']!r}")
      text = item["text"]
      if not isinstance(text, str) or not text.strip() or len(text) > PROGRESS_MAX_CHARS:
        raise ValueError(f"progress text 는 1 ~ {PROGRESS_MAX_CHARS}자 문자열이어야 한다")

  # ---- 워크스페이스 · 보이는 범위 ----
  def _workspace(self, value) -> dict:
    if not isinstance(value, dict) or set(value) != {"layer", "group"}:
      raise ValueError("workspace 는 { layer, group } 이어야 한다")
    layer, group = value["layer"], value["group"]
    if layer not in LAYERS:
      raise ValueError(f"알 수 없는 workspace 층: {layer!r}")
    if layer == "전사" and group is not None:
      raise ValueError("전사 workspace 의 group 은 null 이어야 한다")
    if layer == "팀" and group not in self.teams:
      raise ValueError(f"알 수 없는 팀: {group!r}")
    if layer == "개인" and group not in self.owner_of:
      raise ValueError(f"알 수 없는 주인: {group!r}")
    return {"layer": layer, "group": group}

  def can_see(self, target, workspace) -> bool:
    ws = self._workspace(workspace)
    pairs = visible_pairs_for(target[0], target[1], self.membership)
    # 개인 workspace 는 표시 이름을 실제 주인으로 되돌려 대조한다 - 그 주인 본인만 쌍에 들어 있다
    group = self.owner_of[ws["group"]] if ws["layer"] == "개인" else ws["group"]
    return (ws["layer"], group) in pairs

  def members_of(self, workspace) -> list:
    ws = self._workspace(workspace)
    if ws["layer"] == "전사":
      return sorted(self.labels.values())
    if ws["layer"] == "팀":
      return sorted(self.labels[owner] for owner, teams in self.membership.teams_by_owner.items() if ws["group"] in teams)
    return [ws["group"]]

  def viewer_name(self, target) -> str:
    if target[0] == "개인":
      return self.labels[target[1]]
    return f"팀:{target[1]}" if target[0] == "팀" else "전사"

  def list_workspaces(self, target) -> list:
    # 보는 사람이 볼 수 있는 워크스페이스만 - 전사 → 팀 → 개인 순이고 개인은 can_see 가 본인 것만 남긴다
    candidates = [{"layer": "전사", "group": None}]
    candidates += [{"layer": "팀", "group": team} for team in self.teams]
    candidates += [{"layer": "개인", "group": label} for label in sorted(self.labels.values())]
    return [
      {"workspace": ws, "label": ws["group"] or "전사", "members": self.members_of(ws)}
      for ws in candidates if self.can_see(target, ws)
    ]

  def _now(self) -> str:
    return self.now_fn().strftime("%Y-%m-%dT%H:%M")

  def _meeting_row(self, row: dict) -> dict:
    return {key: row.get(key) for key in _MEETING_KEYS + ("created_by", "updated_at")}

  def _task_row(self, row: dict) -> dict:
    return {key: row.get(key) for key in _TASK_KEYS}

  def _visible_meeting(self, target, meeting_id: str) -> dict:
    for row in self.data["meetings"]:
      if row["meeting_id"] == meeting_id and self.can_see(target, row["workspace"]):
        return row
    raise NotFoundError("회의를 찾을 수 없다")

  def _visible_task(self, target, task_id: str) -> dict:
    for row in self.data["tasks"]:
      if row["task_id"] == task_id and self.can_see(target, row["workspace"]):
        return row
    raise NotFoundError("할 일을 찾을 수 없다")

  # ---- 검사 ----
  def _check_meeting_fields(self, fields: dict) -> dict:
    title = fields["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX_CHARS:
      raise ValueError(f"title 은 1 ~ {TITLE_MAX_CHARS}자 문자열이어야 한다")
    starts, ends = _parse_time(fields["starts_at"], "starts_at"), _parse_time(fields["ends_at"], "ends_at")
    if not starts < ends:
      raise ValueError("starts_at 은 ends_at 보다 앞이어야 한다")
    workspace = self._workspace(fields["workspace"])
    attendees = _str_list(fields["attendees"], "attendees")
    if len(set(attendees)) != len(attendees):
      raise ValueError("attendees 에 중복이 있다")
    allowed = set(self.members_of(workspace))
    outside = [name for name in attendees if name not in allowed]
    # 그 워크스페이스를 볼 수 없는 사람이 참석자면 회의 제목이 그 사람에게 새어 나간다
    if outside:
      raise ValueError(f"워크스페이스 구성원이 아닌 참석자: {outside}")
    agenda = _str_list(fields["agenda"], "agenda")
    minutes = fields["minutes_doc_id"]
    if minutes is not None and (not isinstance(minutes, str) or not minutes):
      raise ValueError("minutes_doc_id 는 문자열 또는 null 이어야 한다")
    if fields["status"] not in MEETING_STATUS:
      raise ValueError(f"알 수 없는 회의 status: {fields['status']!r}")
    return {
      "title": title, "starts_at": fields["starts_at"], "ends_at": fields["ends_at"], "workspace": workspace,
      "attendees": attendees, "agenda": agenda, "minutes_doc_id": minutes, "status": fields["status"],
    }

  def _check_task_fields(self, fields: dict) -> dict:
    title = fields["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX_CHARS:
      raise ValueError(f"title 은 1 ~ {TITLE_MAX_CHARS}자 문자열이어야 한다")
    workspace = self._workspace(fields["workspace"])
    assignee = fields["assignee"]
    if assignee not in self.members_of(workspace):
      raise ValueError(f"워크스페이스 구성원이 아닌 담당자: {assignee!r}")
    due = fields["due"]
    if due is not None:
      _parse_date(due, "due")
    if fields["status"] not in TASK_STATUS:
      raise ValueError(f"알 수 없는 할 일 status: {fields['status']!r}")
    if fields["source"] not in TASK_SOURCE:
      raise ValueError(f"알 수 없는 source: {fields['source']!r}")
    return {
      "title": title, "workspace": workspace, "assignee": assignee, "due": due, "status": fields["status"],
      "source": fields["source"],
    }

  def _next_id(self, rows: list, key: str, prefix: str) -> str:
    numbers = [int(row[key][len(prefix):]) for row in rows if re.fullmatch(prefix + r"\d+", row[key])]
    return f"{prefix}{max(numbers, default=0) + 1:04d}"

  # ---- 회의 ----
  def list_meetings(self, target, date_from=None, date_to=None) -> list:
    if date_from is not None:
      _parse_date(date_from, "from")
    if date_to is not None:
      _parse_date(date_to, "to")
    with self.lock:
      rows = [row for row in self.data["meetings"] if self.can_see(target, row["workspace"])]
      if date_from is not None:
        rows = [row for row in rows if row["starts_at"][:10] >= date_from]
      if date_to is not None:
        rows = [row for row in rows if row["starts_at"][:10] <= date_to]
      return [self._meeting_row(row) for row in sorted(rows, key=lambda r: (r["starts_at"], r["meeting_id"]))]

  def get_meeting(self, target, meeting_id: str) -> dict:
    with self.lock:
      return self._meeting_row(self._visible_meeting(target, meeting_id))

  def create_meeting(self, target, body) -> dict:
    _only_keys(body, _MEETING_INPUT, "회의 만들기")
    missing = [key for key in ("title", "starts_at", "ends_at", "workspace") if key not in body]
    if missing:
      raise ValueError(f"회의 만들기에 없는 키: {missing}")
    fields = {"attendees": [], "agenda": [], "minutes_doc_id": None, "status": "scheduled", **body}
    with self.lock:
      checked = self._check_meeting_fields(fields)
      # 볼 수 없는 워크스페이스에는 만들 수 없다
      if not self.can_see(target, checked["workspace"]):
        raise ValueError("볼 수 없는 workspace 에는 회의를 만들 수 없다")
      row = {"meeting_id": self._next_id(self.data["meetings"], "meeting_id", "m"), **checked}
      row["created_by"] = self.viewer_name(target)
      row["updated_at"] = self._now()
      self.data["meetings"].append(row)
      self._save()
      return self._meeting_row(row)

  def update_meeting(self, target, meeting_id: str, body) -> dict:
    _only_keys(body, _MEETING_INPUT, "회의 바꾸기")
    with self.lock:
      row = self._visible_meeting(target, meeting_id)
      merged = {key: row[key] for key in _MEETING_INPUT}
      merged.update(body)
      checked = self._check_meeting_fields(merged)
      if checked["workspace"] != row["workspace"]:
        if not self.can_see(target, checked["workspace"]):
          raise ValueError("볼 수 없는 workspace 로는 옮길 수 없다")
        # 연결된 할 일이 있으면 워크스페이스를 옮길 수 없다 - 할 일은 회의와 같은 워크스페이스여야 한다
        if any(task["meeting_id"] == meeting_id for task in self.data["tasks"]) or any(
          doc["meeting_id"] == meeting_id for doc in self.data["documents"]
        ):
          raise ValueError("연결된 할 일이 있어 workspace 를 바꿀 수 없다")
      row.update(checked)
      row["updated_at"] = self._now()
      self._save()
      return self._meeting_row(row)

  # 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 - 회의의 minutes_doc_id 연결은 비어 있을 때만 한 번 걸고, 실패하면 되돌린다
  def link_minutes(self, meeting_id: str, doc_id: str) -> None:
    with self.lock:
      for row in self.data["meetings"]:
        if row["meeting_id"] == meeting_id:
          if row["minutes_doc_id"] is not None:
            raise AlreadyLinkedError("이미 회의록이 연결된 회의다")
          row["minutes_doc_id"] = doc_id
          self._save()
          return
    raise NotFoundError("회의를 찾을 수 없다")

  def unlink_minutes(self, meeting_id: str, doc_id: str) -> None:
    with self.lock:
      for row in self.data["meetings"]:
        if row["meeting_id"] == meeting_id and row["minutes_doc_id"] == doc_id:
          row["minutes_doc_id"] = None
          self._save()
          return

  # ---- 회의 문서 · 에이전트 제안 할 일 ----
  def _meeting_row_of(self, meeting_id: str) -> dict:
    for row in self.data["meetings"]:
      if row["meeting_id"] == meeting_id:
        return row
    raise NotFoundError("회의를 찾을 수 없다")

  def _attendee(self, target, meeting: dict) -> str:
    # 확정 · 버리기 · 배정 요청은 그 회의의 참석자 ( 개인 보는 사람 ) 만 한다
    if target[0] != "개인" or self.viewer_name(target) not in meeting["attendees"]:
      raise ValueError("회의 참석자 ( 개인 보는 사람 ) 만 할 수 있다")
    return self.viewer_name(target)

  def has_pending_document(self, meeting_id: str) -> bool:
    with self.lock:
      return any(doc["meeting_id"] == meeting_id and doc["status"] == "proposal" for doc in self.data["documents"])

  def add_agent_proposal(self, meeting_id: str, result: dict, assign_id: str) -> dict:
    # 내부 전용 - HTTP 로 source 를 받는 경로는 그대로 사람만 만든다
    with self.lock:
      meeting = self._meeting_row_of(meeting_id)
      checked_rows = []
      for item in result["tasks_ok"]:
        due = item["due"] or None
        checked = self._check_task_fields({
          "title": item["title"], "workspace": meeting["workspace"], "assignee": item["assignee"], "due": due, "status": "todo",
          "source": "agent_proposal",
        })
        checked_rows.append(checked)
      parsed = result["parsed"]
      # 모두 검사를 통과한 뒤에만 쓴다 - 일부만 들어간 제안을 남기지 않는다
      created = []
      for checked in checked_rows:
        row = {"task_id": self._next_id(self.data["tasks"], "task_id", "t"), "meeting_id": meeting_id, **checked, "progress": []}
        row = {key: row[key] for key in _TASK_KEYS}
        self.data["tasks"].append(row)
        created.append(row)
      document = {
        "doc_id": self._next_id(self.data["documents"], "doc_id", "d"), "meeting_id": meeting_id, "workspace": meeting["workspace"],
        "decisions": list(parsed["decisions"]), "summary": parsed["summary"], "task_ids": [row["task_id"] for row in created],
        "status": "proposal", "assign_id": assign_id, "created_at": self._now(), "confirmed_by": None, "confirmed_at": None,
      }
      self.data["documents"].append(document)
      self._save()
      return {"document": json.loads(json.dumps(document)), "tasks": [self._task_row(row) for row in created]}

  def _visible_document(self, target, doc_id: str) -> dict:
    for row in self.data["documents"]:
      if row["doc_id"] == doc_id and self.can_see(target, row["workspace"]):
        return row
    raise NotFoundError("회의 문서를 찾을 수 없다")

  def list_documents(self, target, meeting_id=None) -> list:
    with self.lock:
      rows = [row for row in self.data["documents"] if self.can_see(target, row["workspace"])]
      if meeting_id is not None:
        rows = [row for row in rows if row["meeting_id"] == meeting_id]
      return [json.loads(json.dumps(row)) for row in sorted(rows, key=lambda r: (r["created_at"], r["doc_id"]))]

  def confirm_task(self, target, task_id: str) -> dict:
    with self.lock:
      row = self._visible_task(target, task_id)
      self._attendee(target, self._meeting_row_of(row["meeting_id"]))
      if row["source"] != "agent_proposal":
        raise ValueError("에이전트 제안 상태의 할 일만 확정한다")
      row["source"] = "agent_confirmed"
      self._save()
      return self._task_row(row)

  def discard_task(self, target, task_id: str) -> dict:
    with self.lock:
      row = self._visible_task(target, task_id)
      self._attendee(target, self._meeting_row_of(row["meeting_id"]))
      # 사람이 만든 할 일과 이미 확정한 할 일은 버리지 않는다
      if row["source"] != "agent_proposal":
        raise ValueError("에이전트 제안 상태의 할 일만 버린다")
      self.data["tasks"].remove(row)
      for doc in self.data["documents"]:
        if task_id in doc["task_ids"]:
          doc["task_ids"].remove(task_id)
      self._save()
      return {"ok": True, "task_id": task_id}

  def confirm_document(self, target, doc_id: str) -> dict:
    with self.lock:
      doc = self._visible_document(target, doc_id)
      name = self._attendee(target, self._meeting_row_of(doc["meeting_id"]))
      if doc["status"] != "proposal":
        raise ValueError("제안 상태의 회의 문서만 확정한다")
      remaining = [row for row in self.data["tasks"] if row["task_id"] in doc["task_ids"] and row["source"] == "agent_proposal"]
      if remaining:
        raise ValueError("할 일을 먼저 확정하거나 버린다")
      doc["status"] = "confirmed"
      doc["confirmed_by"] = name
      doc["confirmed_at"] = self._now()
      self._save()
      return json.loads(json.dumps(doc))

  # ---- 할 일 ----
  def list_tasks(self, target, meeting_id=None, assignee=None) -> list:
    with self.lock:
      rows = [row for row in self.data["tasks"] if self.can_see(target, row["workspace"])]
      if meeting_id is not None:
        rows = [row for row in rows if row["meeting_id"] == meeting_id]
      if assignee is not None:
        rows = [row for row in rows if row["assignee"] == assignee]
      return [self._task_row(row) for row in sorted(rows, key=lambda r: (r["due"] or "9999-99-99", r["task_id"]))]

  def create_task(self, target, body) -> dict:
    _only_keys(body, _TASK_INPUT, "할 일 만들기")
    missing = [key for key in ("title", "assignee") if key not in body]
    if missing:
      raise ValueError(f"할 일 만들기에 없는 키: {missing}")
    with self.lock:
      meeting = None
      if body.get("meeting_id") is not None:
        try:
          meeting = self._visible_meeting(target, body["meeting_id"])
        except NotFoundError:
          raise ValueError("연결할 회의를 찾을 수 없다") from None
      workspace = body.get("workspace", meeting["workspace"] if meeting else None)
      if workspace is None:
        raise ValueError("회의가 없는 할 일은 workspace 가 필요하다")
      fields = {"due": None, "status": "todo", "source": "human", **body, "workspace": workspace}
      if fields["source"] not in API_SOURCES:
        raise ValueError(f"API 로는 source 가 {list(API_SOURCES)} 인 할 일만 만든다")
      checked = self._check_task_fields(fields)
      if not self.can_see(target, checked["workspace"]):
        raise ValueError("볼 수 없는 workspace 에는 할 일을 만들 수 없다")
      # 할 일은 연결한 회의와 같은 워크스페이스여야 한다
      if meeting is not None and checked["workspace"] != meeting["workspace"]:
        raise ValueError("연결한 회의와 workspace 가 다르다")
      row = {"task_id": self._next_id(self.data["tasks"], "task_id", "t"), "meeting_id": body.get("meeting_id"), **checked}
      row = {key: row[key] for key in _TASK_KEYS if key != "progress"}
      row["progress"] = []
      self.data["tasks"].append(row)
      self._save()
      return self._task_row(row)

  def update_task(self, target, task_id: str, body) -> dict:
    _only_keys(body, _TASK_UPDATE, "할 일 바꾸기")
    with self.lock:
      row = self._visible_task(target, task_id)
      merged = {key: row[key] for key in ("title", "workspace", "assignee", "due", "status", "source")}
      merged.update(body)
      checked = self._check_task_fields(merged)
      row.update({key: checked[key] for key in _TASK_UPDATE})
      self._save()
      return self._task_row(row)

  def add_progress(self, target, task_id: str, text) -> dict:
    # 진행 기록은 개인만 쓴다 - 팀 · 전사 보는 사람은 작성자가 정해지지 않는다
    if target[0] != "개인":
      raise ValueError("진행 기록은 개인 보는 사람만 쓴다")
    if not isinstance(text, str) or not text.strip() or len(text) > PROGRESS_MAX_CHARS:
      raise ValueError(f"text 는 1 ~ {PROGRESS_MAX_CHARS}자 문자열이어야 한다")
    with self.lock:
      row = self._visible_task(target, task_id)
      row["progress"].append({"at": self._now(), "author": self.viewer_name(target), "text": text})
      self._save()
      return self._task_row(row)
