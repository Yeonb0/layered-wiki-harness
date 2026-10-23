# 사용자 결정 2026-10-23 ( 지침 v3.1 · 3절 26 · 27 ) : 할 일 배정 · 회의 문서 생성은 분해 · 배치 에이전트와 분리된 별도 역할이다. 프롬프트 · 스키마 · 로그를 공유하지 않고 조건 비교에 들어가지 않는다. 결과는 에이전트 제안이며 사람이 확정한다
import json
import os
import re
from datetime import datetime

from agent.llm_client import GenerationConfig
from runner.v2_sequential import ENABLE_THINKING, TEMPERATURE

ASSIGN_PROMPT_VERSION = "assign-v1"
MAX_TOKENS = 1024
LOG_NAME = "assign_log.jsonl"
MAX_DECISIONS = 10
MAX_TASKS = 10
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SYSTEM_PROMPT = "\n".join([
  "너는 회의록에서 결정 사항과 할 일을 뽑는 역할이다.",
  "",
  "규칙",
  "1. 회의록에 적힌 내용만 쓴다. 없는 내용을 만들지 않는다.",
  "2. decisions 에는 회의에서 정해진 사항을, summary 에는 회의 요약을 쓴다.",
  "3. tasks 의 assignee 는 주어진 참석자 중에서만 고른다.",
  "4. due 는 회의록에 날짜가 적혀 있을 때만 그 날짜를 YYYY-MM-DD 로 쓴다. 적혀 있지 않으면 빈 문자열이다.",
  "5. evidence 에는 그 할 일의 근거가 된 회의록 문장을 한 글자도 바꾸지 않고 그대로 옮긴다.",
])


class AssignOutputError(ValueError):
  # 모델 출력을 쓸 수 없을 때 - 원문을 함께 들고 있어 배정 로그에 남긴다
  def __init__(self, message: str, raw_output: str) -> None:
    super().__init__(message)
    self.raw_output = raw_output


def assign_schema(attendees: list) -> dict:
  # 담당자 enum 은 참석자와 정확히 같다 - 참석자가 없으면 enum 이 비어 어떤 출력도 의미가 없다
  if not attendees:
    raise ValueError("참석자가 없다")
  return {
    "type": "object",
    "properties": {
      "decisions": {
        "type": "array", "maxItems": MAX_DECISIONS, "items": {"type": "string", "minLength": 1, "maxLength": 200},
      },
      "summary": {"type": "string", "minLength": 1, "maxLength": 600},
      "tasks": {
        "type": "array",
        "maxItems": MAX_TASKS,
        "items": {
          "type": "object",
          "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 80},
            "assignee": {"type": "string", "enum": list(attendees)},
            "due": {"type": "string", "pattern": "^(|[0-9]{4}-[0-9]{2}-[0-9]{2})$"},
            "evidence": {"type": "string", "minLength": 1, "maxLength": 300},
          },
          "required": ["title", "assignee", "due", "evidence"],
          "additionalProperties": False,
        },
      },
    },
    "required": ["decisions", "summary", "tasks"],
    "additionalProperties": False,
  }


def build_messages(meeting: dict, raw_text: str, attendees: list) -> list:
  User = "\n".join([
    f"회의 제목: {meeting['title']}",
    f"일시: {meeting['starts_at']} ~ {meeting['ends_at']}",
    f"참석자: {', '.join(attendees)}",
    "",
    "회의록",
    raw_text,
  ])
  return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": User}]


def _date_forms(due: str) -> list:
  Day = datetime.strptime(due, "%Y-%m-%d")
  return [due, f"{Day.month:02d}-{Day.day:02d}", f"{Day.month}월 {Day.day}일"]


def _task_shape_ok(task) -> bool:
  if not isinstance(task, dict) or set(task) != {"title", "assignee", "due", "evidence"}:
    return False
  if not all(isinstance(task[key], str) for key in task):
    return False
  return 1 <= len(task["title"]) <= 80 and 1 <= len(task["evidence"]) <= 300


def run_assign(meeting: dict, minutes_doc: dict, chat_fn, model_id: str, seed: int, timeout) -> dict:
  Attendees = list(meeting["attendees"])
  RawText = minutes_doc["raw_text"]
  Config = GenerationConfig(temperature=TEMPERATURE, seed=seed, max_tokens=MAX_TOKENS, enable_thinking=ENABLE_THINKING)
  Result = chat_fn(build_messages(meeting, RawText, Attendees), model_id, Config, assign_schema(Attendees), timeout_seconds=timeout)
  Raw = Result.text
  # 잘린 출력은 파싱하지 않는다
  if Result.finish_reason != "stop":
    raise AssignOutputError(f"finish_reason:{Result.finish_reason}", Raw)
  try:
    Parsed = json.loads(Raw)
  except json.JSONDecodeError as Error:
    raise AssignOutputError(f"JSON 이 아니다: {Error}", Raw) from None
  if not isinstance(Parsed, dict) or set(Parsed) != {"decisions", "summary", "tasks"}:
    raise AssignOutputError("decisions · summary · tasks 만 가진 객체가 아니다", Raw)
  Decisions, Summary, Tasks = Parsed["decisions"], Parsed["summary"], Parsed["tasks"]
  if (
    not isinstance(Decisions, list) or len(Decisions) > MAX_DECISIONS
    or not all(isinstance(Item, str) and 1 <= len(Item) <= 200 for Item in Decisions)
  ):
    raise AssignOutputError("decisions 형식이 맞지 않는다", Raw)
  if not isinstance(Summary, str) or not 1 <= len(Summary) <= 600:
    raise AssignOutputError("summary 형식이 맞지 않는다", Raw)
  if not isinstance(Tasks, list):
    raise AssignOutputError("tasks 가 목록이 아니다", Raw)

  Ok, Dropped, Problems = [], [], []
  for Index, Task in enumerate(Tasks):
    if Index >= MAX_TASKS:
      Dropped.append({"task": Task, "reason": "too_many_tasks"})
    elif not _task_shape_ok(Task):
      Dropped.append({"task": Task, "reason": "invalid_task"})
    # 스키마가 막아도 코드에서 한 번 더 : 참석자 밖 담당자
    elif Task["assignee"] not in Attendees:
      Dropped.append({"task": Task, "reason": "assignee_not_attendee"})
    # 근거는 공백 정규화 없이 회의록에 그대로 있어야 한다
    elif Task["evidence"] not in RawText:
      Dropped.append({"task": Task, "reason": "evidence_not_in_minutes"})
    else:
      Task = dict(Task)
      Due = Task["due"]
      if Due != "":
        if not _DATE.match(Due):
          Problems.append({"task_title": Task["title"], "problem": "due_bad_format", "given": Due})
          Task["due"] = ""
        else:
          try:
            Forms = _date_forms(Due)
          except ValueError:
            Problems.append({"task_title": Task["title"], "problem": "due_bad_format", "given": Due})
            Task["due"] = ""
          else:
            # 회의록에 그 날짜가 어떤 형태로도 없으면 기한만 비우고 할 일은 남긴다
            if not any(Form in RawText for Form in Forms):
              Problems.append({"task_title": Task["title"], "problem": "due_not_in_minutes", "given": Due})
              Task["due"] = ""
      Ok.append(Task)
  return {
    "parsed": Parsed, "tasks_ok": Ok, "tasks_dropped": Dropped, "problems": Problems, "raw_output": Raw,
    "prompt_version": ASSIGN_PROMPT_VERSION,
    "generation": {"model_id": model_id, "temperature": TEMPERATURE, "seed": seed, "max_tokens": MAX_TOKENS, "enable_thinking": ENABLE_THINKING},
  }


def append_log(dir_path: str, entry: dict) -> None:
  # 덧붙이기만 한다 - 실험 경로 로그 · 볼트에는 쓰지 않는다
  with open(os.path.join(dir_path, LOG_NAME), "a", encoding="utf-8") as File:
    File.write(json.dumps(entry, ensure_ascii=False) + "\n")
    File.flush()
    os.fsync(File.fileno())
