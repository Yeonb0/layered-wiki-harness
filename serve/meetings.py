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
_EMPTY = {"version": 1, "meetings": [], "tasks": []}


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
    # 구조와 워크스페이스만 시작 때 검사한다 - 회의 · 할 일 연결 규칙은 새로 쓸 때 검사한다 ( 예시 파일에는 그 규칙 밖의 연결이 있다 )
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
        if any(task["meeting_id"] == meeting_id for task in self.data["tasks"]):
          raise ValueError("연결된 할 일이 있어 workspace 를 바꿀 수 없다")
      row.update(checked)
      row["updated_at"] = self._now()
      self._save()
      return self._meeting_row(row)

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
