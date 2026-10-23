import copy
import json
import os
import subprocess
import unittest

from agent.llm_client import ChatResult
from serve.assign import ASSIGN_PROMPT_VERSION, AssignOutputError, LOG_NAME, assign_schema, run_assign
from serve.meetings import MeetingStore
from tests.test_demo_minutes import _ROOT, _SEED, MinutesBase, _chat as _layer_chat, _files

# 픽스처일 뿐이며 규칙과 무관하다 - 이름 · 제목 · 본문은 전부 합성이다
_TEXT = (
  "# 합성 회의록\n\n"
  "## 안건 하나\n팀원A 가 합성 표를 정리하기로 했다. 10월 31일 까지 끝낸다.\n\n"
  "## 안건 둘\n팀원B 가 합성 문서를 검토한다.\n\n"
  "## 안건 셋\n합성 결정 하나를 확인했다.\n"
)
_GOOD = {
  "decisions": ["합성 결정 하나를 확인했다"],
  "summary": "합성 요약 문장",
  "tasks": [
    {"title": "합성 표 정리", "assignee": "팀원A", "due": "2026-10-31", "evidence": "팀원A 가 합성 표를 정리하기로 했다."},
    {"title": "합성 문서 검토", "assignee": "팀원B", "due": "", "evidence": "팀원B 가 합성 문서를 검토한다."},
  ],
}
_SPY_STRINGS = ("합성 표 정리", "합성 문서 검토", "합성 요약 문장", "합성 결정 하나를 확인했다")
_MEETING = {
  "title": "합성 회의", "starts_at": "2026-10-20T10:00", "ends_at": "2026-10-20T11:00", "attendees": ["팀원A", "팀원B"],
}


def _reply(Text, Finish="stop") -> ChatResult:
  return ChatResult(
    text=Text, finish_reason=Finish, prompt_tokens=1, completion_tokens=1, elapsed_seconds=0.1, timings=None, request_body={},
    response_body={},
  )


def _stub(Output, Finish="stop"):
  # 받은 인자를 기록하는 가짜 chat_fn
  Calls = []

  def chat(messages, model_id, config, response_schema, *, timeout_seconds):
    Calls.append({"messages": messages, "model_id": model_id, "config": config, "schema": response_schema, "timeout": timeout_seconds})
    return _reply(Output if isinstance(Output, str) else json.dumps(Output, ensure_ascii=False), Finish)

  return chat, Calls


def _run(Output, Text=_TEXT, Finish="stop"):
  Chat, Calls = _stub(Output, Finish)
  return run_assign(_MEETING, {"raw_text": Text}, Chat, "합성모델", 7, 9), Calls


class RoleTest(unittest.TestCase):
  def test_schema_enum_is_exactly_the_attendees(self) -> None:
    Schema = assign_schema(["팀원A", "팀원B"])
    Task = Schema["properties"]["tasks"]["items"]
    self.assertEqual(Task["properties"]["assignee"]["enum"], ["팀원A", "팀원B"])
    self.assertEqual(Task["required"], ["title", "assignee", "due", "evidence"])
    self.assertIs(Task["additionalProperties"], False)
    self.assertIs(Schema["additionalProperties"], False)
    self.assertEqual((Schema["properties"]["decisions"]["maxItems"], Schema["properties"]["tasks"]["maxItems"]), (10, 10))
    with self.assertRaises(ValueError):
      assign_schema([])

  def test_call_shape_and_generation_settings(self) -> None:
    Result, Calls = _run(_GOOD)
    Call = Calls[0]
    self.assertEqual(Call["schema"]["properties"]["tasks"]["items"]["properties"]["assignee"]["enum"], ["팀원A", "팀원B"])
    self.assertEqual((Call["config"].temperature, Call["config"].seed, Call["config"].max_tokens, Call["config"].enable_thinking), (0.0, 7, 1024, False))
    self.assertEqual((Call["model_id"], Call["timeout"]), ("합성모델", 9))
    self.assertIn("팀원A, 팀원B", Call["messages"][1]["content"])
    self.assertEqual(Result["prompt_version"], ASSIGN_PROMPT_VERSION)
    self.assertEqual(Result["generation"]["seed"], 7)
    self.assertEqual([T["title"] for T in Result["tasks_ok"]], ["합성 표 정리", "합성 문서 검토"])
    self.assertEqual(Result["tasks_dropped"], [])

  def test_assignee_outside_attendees_is_dropped(self) -> None:
    Output = copy.deepcopy(_GOOD)
    Output["tasks"][0]["assignee"] = "팀원C"
    Result, _ = _run(Output)
    self.assertEqual([(D["task"]["title"], D["reason"]) for D in Result["tasks_dropped"]], [("합성 표 정리", "assignee_not_attendee")])
    self.assertEqual([T["title"] for T in Result["tasks_ok"]], ["합성 문서 검토"])

  def test_evidence_must_be_in_minutes_exactly(self) -> None:
    Output = copy.deepcopy(_GOOD)
    Output["tasks"][0]["evidence"] = "회의록에 없는 문장이다"
    # 공백만 다른 문장도 그대로가 아니다
    Output["tasks"][1]["evidence"] = "팀원B 가  합성 문서를 검토한다."
    Result, _ = _run(Output)
    self.assertEqual([D["reason"] for D in Result["tasks_dropped"]], ["evidence_not_in_minutes", "evidence_not_in_minutes"])
    self.assertEqual(Result["tasks_ok"], [])

  def test_due_not_in_minutes_is_blanked_with_a_problem(self) -> None:
    Output = copy.deepcopy(_GOOD)
    Output["tasks"][1]["due"] = "2026-11-30"
    Result, _ = _run(Output)
    self.assertEqual([T["due"] for T in Result["tasks_ok"]], ["2026-10-31", ""])
    self.assertEqual(Result["problems"], [{"task_title": "합성 문서 검토", "problem": "due_not_in_minutes", "given": "2026-11-30"}])

  def test_due_kept_in_each_written_form(self) -> None:
    for Written in ("10월 31일", "10-31", "2026-10-31"):
      Text = _TEXT.replace("10월 31일", Written)
      Result, _ = _run(_GOOD, Text=Text)
      self.assertEqual(Result["tasks_ok"][0]["due"], "2026-10-31", Written)
      self.assertEqual(Result["problems"], [], Written)

  def test_bad_due_format_is_blanked(self) -> None:
    Output = copy.deepcopy(_GOOD)
    Output["tasks"][0]["due"] = "내일"
    Output["tasks"][1]["due"] = "2026-02-31"
    Result, _ = _run(Output)
    self.assertEqual([T["due"] for T in Result["tasks_ok"]], ["", ""])
    self.assertEqual([P["problem"] for P in Result["problems"]], ["due_bad_format", "due_bad_format"])

  def test_unusable_output_raises_and_keeps_raw_output(self) -> None:
    for Output, Finish in (("not json", "stop"), (json.dumps(_GOOD), "length"), ('{"decisions": [], "summary": "", "tasks": []}', "stop"), ("[]", "stop")):
      with self.assertRaises(AssignOutputError, msg=Output) as Caught:
        _run(Output, Finish=Finish)
      self.assertEqual(Caught.exception.raw_output, Output)
      self.assertIsInstance(Caught.exception, ValueError)


class DueBoundaryTest(unittest.TestCase):
  def due_after(self, Text, Due, Starts="2026-10-20T10:00"):
    Output = copy.deepcopy(_GOOD)
    Output["tasks"][0]["due"] = Due
    Chat, _ = _stub(Output)
    Meeting = {**_MEETING, "starts_at": Starts}
    Result = run_assign(Meeting, {"raw_text": Text}, Chat, "합성모델", 7, 9)
    return Result["tasks_ok"][0]["due"], Result["problems"]

  def test_month_day_inside_a_longer_month_is_not_a_match(self) -> None:
    # 11월 3일 안에 1월 3일이 들어 있어도 1월 3일이 적힌 것은 아니다
    Text = _TEXT.replace("10월 31일", "11월 3일")
    Due, Problems = self.due_after(Text, "2026-01-03")
    self.assertEqual(Due, "")
    self.assertEqual(Problems, [{"task_title": "합성 표 정리", "problem": "due_not_in_minutes", "given": "2026-01-03"}])
    self.assertEqual(self.due_after(Text, "2026-11-03")[0], "2026-11-03")

  def test_year_less_forms_need_the_meeting_year(self) -> None:
    self.assertEqual(self.due_after(_TEXT, "2027-10-31")[0], "")
    self.assertEqual(self.due_after(_TEXT, "2026-10-31")[0], "2026-10-31")
    self.assertEqual(self.due_after(_TEXT.replace("10월 31일", "10-31"), "2027-10-31")[0], "")
    # 회의 연도가 2027 이면 같은 글이 2027 기한을 받친다
    self.assertEqual(self.due_after(_TEXT, "2027-10-31", Starts="2027-10-20T10:00")[0], "2027-10-31")

  def test_full_date_is_kept_in_any_year(self) -> None:
    Text = _TEXT.replace("10월 31일", "2027-10-31")
    self.assertEqual(self.due_after(Text, "2027-10-31"), ("2027-10-31", []))

  def test_digits_next_to_the_date_block_the_match(self) -> None:
    for Written in ("110-31", "10-310", "2026-10-310", "12026-10-31"):
      Text = _TEXT.replace("10월 31일", Written)
      Due, _ = self.due_after(Text, "2026-10-31")
      self.assertEqual(Due, "", Written)

  def test_short_form_inside_another_full_date_is_not_a_match(self) -> None:
    # 2027-10-31 의 끝부분 10-31 은 2026-10-31 이 적힌 것이 아니다
    Text = _TEXT.replace("10월 31일", "2027-10-31")
    self.assertEqual(self.due_after(Text, "2026-10-31")[0], "")


class AssignBase(MinutesBase):
  def setUp(self) -> None:
    super().setUp()
    self.Output = copy.deepcopy(_GOOD)
    self.Calls = []

  def chat(self, messages, model_id, config, response_schema, *, timeout_seconds):
    if "decisions" in response_schema["properties"]:
      self.Calls.append({"schema": response_schema, "config": config})
      return _reply(self.Output if isinstance(self.Output, str) else json.dumps(self.Output, ensure_ascii=False))
    return _layer_chat(messages, model_id, config, response_schema, timeout_seconds=timeout_seconds)

  def app(self, RunDir=None, Seed=_SEED):
    App = super().app(RunDir, Seed)
    App.chat_fn = self.chat
    return App

  def decided(self, App, Viewer="개인:팀원A", Meeting="m0007") -> str:
    DocId = self.submit(App, Viewer=Viewer, Meeting=Meeting, Text=_TEXT)
    Items = [{"note_index": Index, "decision": "approve"} for Index in range(App.minutes.get(DocId)["note_count"])]
    self.assertEqual(self.decide(App, Viewer, DocId, Items)[1]["status"], "decided")
    return DocId

  def start(self, App, Viewer="개인:팀원A", Meeting="m0007"):
    return App.meetings_request("POST", f"/meetings/{Meeting}/assign", {}, {"viewer": Viewer})

  def run_assign_flow(self, App, Viewer="개인:팀원A", Meeting="m0007") -> str:
    Status, Body = self.start(App, Viewer, Meeting)
    self.assertEqual(Status, 202, Body)
    self.assertTrue(App.assigns[Body["assign_id"]]["event"].wait(30))
    return Body["assign_id"]

  def api(self, App, Method, Path, Viewer, **Body):
    if Method == "GET":
      return App.meetings_request("GET", Path, {"viewer": [Viewer], **{Key: [Value] for Key, Value in Body.items()}}, None)
    return App.meetings_request("POST", Path, {}, {"viewer": Viewer, **Body})


class FlowTest(AssignBase):
  def test_assign_confirm_discard_and_confirm_document(self) -> None:
    App = self.app()
    self.decided(App)
    AssignId = self.run_assign_flow(App)
    Status, Info = self.api(App, "GET", "/meetings/m0007/assign", "개인:팀원B")
    self.assertEqual((Status, Info), (200, {
      "assign_id": AssignId, "status": "done", "error": None, "tasks_dropped": 0, "dropped": [], "problems": [],
    }))
    Tasks = self.api(App, "GET", "/tasks", "개인:팀원B", meeting="m0007")[1]["tasks"]
    Agent = [T for T in Tasks if T["source"] == "agent_proposal"]
    self.assertEqual([(T["title"], T["assignee"], T["due"], T["status"]) for T in Agent], [
      ("합성 표 정리", "팀원A", "2026-10-31", "todo"), ("합성 문서 검토", "팀원B", None, "todo"),
    ])
    self.assertTrue(all(T["workspace"] == {"layer": "팀", "group": "팀1"} and T["meeting_id"] == "m0007" for T in Agent))
    Docs = self.api(App, "GET", "/meeting-docs", "개인:팀원B", meeting="m0007")[1]["documents"]
    self.assertEqual(len(Docs), 1)
    Doc = Docs[0]
    self.assertEqual((Doc["status"], Doc["assign_id"], Doc["summary"], Doc["decisions"]), ("proposal", AssignId, "합성 요약 문장", ["합성 결정 하나를 확인했다"]))
    self.assertEqual(Doc["task_ids"], [T["task_id"] for T in Agent])
    # 남은 제안 할 일이 있으면 문서를 확정하지 못한다
    Status, Body = self.api(App, "POST", f"/meeting-docs/{Doc['doc_id']}/confirm", "개인:팀원B")
    self.assertEqual((Status, Body["message"]), (400, "할 일을 먼저 확정하거나 버린다"))
    First, Second = Agent
    Status, Body = self.api(App, "POST", f"/tasks/{First['task_id']}/confirm", "개인:팀원B")
    self.assertEqual((Status, Body["source"]), (200, "agent_confirmed"))
    Status, Body = self.api(App, "POST", f"/tasks/{Second['task_id']}/discard", "개인:팀원B")
    self.assertEqual((Status, Body), (200, {"ok": True, "task_id": Second["task_id"]}))
    self.assertNotIn(Second["task_id"], [T["task_id"] for T in self.api(App, "GET", "/tasks", "개인:팀원B")[1]["tasks"]])
    Status, Body = self.api(App, "POST", f"/meeting-docs/{Doc['doc_id']}/confirm", "개인:팀원E")
    self.assertEqual((Status, Body["status"], Body["confirmed_by"], Body["task_ids"]), (200, "confirmed", "팀원E", [First["task_id"]]))
    # 확정된 뒤에는 담당자가 진행 기록을 쓴다
    Status, Body = self.api(App, "POST", f"/tasks/{First['task_id']}/progress", "개인:팀원A", text="합성 진행 기록")
    self.assertEqual((Status, Body["progress"][-1]["author"]), (200, "팀원A"))
    # 문서가 확정되면 다시 배정을 요청할 수 있다
    self.run_assign_flow(App)

  def test_agent_tasks_carry_evidence_that_is_in_the_minutes(self) -> None:
    App = self.app()
    DocId = self.decided(App)
    self.run_assign_flow(App)
    Raw = App.minutes.get(DocId)["raw_text"]
    Tasks = self.api(App, "GET", "/tasks", "개인:팀원B", meeting="m0007")[1]["tasks"]
    Agent = [T for T in Tasks if T["source"] == "agent_proposal"]
    self.assertEqual([T["evidence"] for T in Agent], [Item["evidence"] for Item in _GOOD["tasks"]])
    self.assertTrue(all(T["evidence"] in Raw for T in Agent))
    # 사람이 만든 할 일에는 evidence 키가 없다
    self.assertTrue(all("evidence" not in T for T in Tasks if T["source"] == "human"))
    # 확정 · 수정을 거쳐도 남는다
    Confirmed = self.api(App, "POST", f"/tasks/{Agent[0]['task_id']}/confirm", "개인:팀원B")[1]
    self.assertEqual(Confirmed["evidence"], Agent[0]["evidence"])

  def test_api_rejects_evidence(self) -> None:
    App = self.app()
    Status, Body = self.api(App, "POST", "/tasks", "개인:팀원A", title="합성", assignee="팀원A", meeting_id="m0007", evidence="꾸민 근거")
    self.assertEqual(Status, 400, Body)
    self.assertEqual(self.api(App, "POST", "/tasks/t0001", "개인:팀원A", evidence="꾸민 근거")[0], 400)

  def test_state_survives_restart(self) -> None:
    App = self.app()
    self.decided(App)
    self.run_assign_flow(App)
    Again = self.app(Seed=None)
    self.assertEqual(len(self.api(Again, "GET", "/meeting-docs", "개인:팀원B")[1]["documents"]), 1)
    self.assertEqual(self.start(Again)[1]["error_type"], "AssignPending")


class RuleTest(AssignBase):
  def test_requires_decided_minutes(self) -> None:
    App = self.app()
    # 회의록이 없다
    self.assertEqual(self.start(App)[0], 400)
    DocId = self.submit(App, Text=_TEXT)
    self.assertEqual(App.minutes.get(DocId)["status"], "awaiting_approval")
    Status, Body = self.start(App)
    self.assertEqual((Status, Body["error_type"]), (400, "BadRequest"))
    self.assertEqual(self.Calls, [])

  def test_only_attendee_individuals_may_request(self) -> None:
    App = self.app()
    # 팀2 회의를 새로 만든다 ( 참석자는 팀원C · 팀원D )
    Status, Meeting = self.api(App, "POST", "/meetings", "개인:팀원C", title="합성 팀2 회의", starts_at="2026-11-01T10:00", ends_at="2026-11-01T11:00", workspace={"layer": "팀", "group": "팀2"}, attendees=["팀원C", "팀원D"])
    self.assertEqual(Status, 201)
    Id = Meeting["meeting_id"]
    self.decided(App, Viewer="개인:팀원C", Meeting=Id)
    # 팀2 구성원이지만 참석자가 아니다
    self.assertEqual(self.start(App, "개인:팀원F", Id)[0], 400)
    self.assertEqual(self.start(App, "팀:팀2", Id)[0], 400)
    # 볼 수 없는 보는 사람은 없는 회의와 같은 404
    self.assertEqual(self.start(App, "개인:팀원A", Id)[0], 404)
    self.run_assign_flow(App, "개인:팀원C", Id)

  def test_second_request_while_proposal_is_409(self) -> None:
    App = self.app()
    self.decided(App)
    self.run_assign_flow(App)
    Status, Body = self.start(App)
    self.assertEqual((Status, Body["error_type"]), (409, "AssignPending"))
    self.assertEqual(len(self.Calls), 1)

  def test_busy_lock_is_409(self) -> None:
    App = self.app()
    self.decided(App)
    App.lock.acquire()
    try:
      Status, Body = self.start(App)
    finally:
      App.lock.release()
    self.assertEqual((Status, Body["error_type"]), (409, "Busy"))
    self.assertEqual(self.Calls, [])
    self.run_assign_flow(App)

  def test_lock_is_released_after_the_job(self) -> None:
    App = self.app()
    self.decided(App)
    self.run_assign_flow(App)
    self.assertFalse(App.lock.locked())

  def test_only_agent_proposals_can_be_confirmed_or_discarded(self) -> None:
    App = self.app()
    self.decided(App)
    self.run_assign_flow(App)
    Agent = self.api(App, "GET", "/tasks", "개인:팀원B", meeting="m0007")[1]["tasks"]
    Proposal = next(T for T in Agent if T["source"] == "agent_proposal")
    # 사람이 만든 할 일
    for Action in ("confirm", "discard"):
      self.assertEqual(self.api(App, "POST", "/tasks/t0001/" + Action, "개인:팀원B")[0], 400, Action)
    # 팀 보는 사람 · 비참석자 ( 볼 수 없는 사람은 404 )
    self.assertEqual(self.api(App, "POST", f"/tasks/{Proposal['task_id']}/confirm", "팀:팀1")[0], 400)
    self.assertEqual(self.api(App, "POST", f"/tasks/{Proposal['task_id']}/confirm", "개인:팀원C")[0], 404)
    # 확정한 할 일은 버리지 못하고 다시 확정하지도 못한다
    self.assertEqual(self.api(App, "POST", f"/tasks/{Proposal['task_id']}/confirm", "개인:팀원B")[0], 200)
    self.assertEqual(self.api(App, "POST", f"/tasks/{Proposal['task_id']}/discard", "개인:팀원B")[0], 400)
    self.assertEqual(self.api(App, "POST", f"/tasks/{Proposal['task_id']}/confirm", "개인:팀원B")[0], 400)
    # 본문에 다른 키가 있으면 받지 않는다
    self.assertEqual(self.api(App, "POST", f"/tasks/{Proposal['task_id']}/confirm", "개인:팀원B", source="human")[0], 400)

  def test_api_still_creates_only_human_tasks(self) -> None:
    App = self.app()
    for Source in ("agent_proposal", "agent_confirmed"):
      Status, Body = self.api(App, "POST", "/tasks", "개인:팀원A", title="합성", assignee="팀원A", meeting_id="m0007", source=Source)
      self.assertEqual(Status, 400, Source)
    self.assertEqual(self.api(App, "POST", "/tasks", "개인:팀원A", title="합성", assignee="팀원A", meeting_id="m0007")[0], 201)

  def test_document_confirm_needs_attendee_and_proposal_state(self) -> None:
    App = self.app()
    self.decided(App)
    self.run_assign_flow(App)
    Doc = self.api(App, "GET", "/meeting-docs", "개인:팀원B")[1]["documents"][0]
    for Task in Doc["task_ids"]:
      self.api(App, "POST", f"/tasks/{Task}/confirm", "개인:팀원B")
    self.assertEqual(self.api(App, "POST", f"/meeting-docs/{Doc['doc_id']}/confirm", "팀:팀1")[0], 400)
    self.assertEqual(self.api(App, "POST", f"/meeting-docs/{Doc['doc_id']}/confirm", "개인:팀원C")[0], 404)
    self.assertEqual(self.api(App, "POST", f"/meeting-docs/{Doc['doc_id']}/confirm", "개인:팀원B")[0], 200)
    self.assertEqual(self.api(App, "POST", f"/meeting-docs/{Doc['doc_id']}/confirm", "개인:팀원B")[0], 400)

  def test_dropped_items_are_reported_with_title_and_reason_only(self) -> None:
    App = self.app()
    self.decided(App)
    self.Output["tasks"][0]["assignee"] = "팀원C"
    self.Output["tasks"][1]["due"] = "2026-12-25"
    self.run_assign_flow(App)
    Info = self.api(App, "GET", "/meetings/m0007/assign", "개인:팀원B")[1]
    self.assertEqual(Info["status"], "done")
    self.assertEqual((Info["tasks_dropped"], Info["dropped"]), (1, [{"title": "합성 표 정리", "reason": "assignee_not_attendee"}]))
    self.assertEqual(Info["problems"], [{"task_title": "합성 문서 검토", "problem": "due_not_in_minutes", "given": "2026-12-25"}])
    self.assertNotIn("evidence", json.dumps(Info, ensure_ascii=False))
    Tasks = self.api(App, "GET", "/tasks", "개인:팀원B", meeting="m0007")[1]["tasks"]
    self.assertEqual([T["title"] for T in Tasks if T["source"] == "agent_proposal"], ["합성 문서 검토"])

  def test_no_assign_job_yet_is_404(self) -> None:
    App = self.app()
    self.assertEqual(self.api(App, "GET", "/meetings/m0007/assign", "개인:팀원B")[0], 404)


class SpyTest(AssignBase):
  def test_other_team_sees_nothing_of_the_result(self) -> None:
    App = self.app()
    self.decided(App)
    self.run_assign_flow(App)
    Seen = json.dumps([
      self.api(App, "GET", "/tasks", "개인:팀원B")[1], self.api(App, "GET", "/meeting-docs", "개인:팀원B")[1],
      self.api(App, "GET", "/meetings", "개인:팀원B")[1],
    ], ensure_ascii=False)
    # 대조군 : 같은 팀은 제목 · 요약이 보인다
    for Text in _SPY_STRINGS[:3]:
      self.assertIn(Text, Seen)
    Texts = []
    Status, Body = self.api(App, "GET", "/tasks", "개인:팀원C")
    self.assertEqual(Status, 200)
    Texts.append(json.dumps(Body, ensure_ascii=False))
    Texts.append(json.dumps(self.api(App, "GET", "/meeting-docs", "개인:팀원C")[1], ensure_ascii=False))
    Texts.append(json.dumps(self.api(App, "GET", "/meeting-docs", "개인:팀원C", meeting="m0007")[1], ensure_ascii=False))
    Texts.append(json.dumps(self.api(App, "GET", "/meetings", "개인:팀원C")[1], ensure_ascii=False))
    for Path in ("/meetings/m0007/assign", "/meetings/m0007"):
      Status, Body = self.api(App, "GET", Path, "개인:팀원C")
      self.assertEqual(Status, 404)
      Texts.append(json.dumps(Body, ensure_ascii=False))
    Docs = self.api(App, "GET", "/meeting-docs", "개인:팀원B")[1]["documents"]
    Status, Body = self.api(App, "POST", f"/meeting-docs/{Docs[0]['doc_id']}/confirm", "개인:팀원C")
    self.assertEqual(Status, 404)
    Texts.append(json.dumps(Body, ensure_ascii=False))
    for Text in Texts:
      for Spy in _SPY_STRINGS:
        self.assertNotIn(Spy, Text)
    self.assertEqual(self.api(App, "GET", "/meeting-docs", "개인:팀원C")[1], {"documents": []})


class IsolationTest(AssignBase):
  def test_only_the_assign_log_is_added_to_the_minutes_folder(self) -> None:
    Git = lambda: subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=_ROOT, capture_output=True, text=True, check=True).stdout
    App = self.app()
    DocId = self.decided(App)
    Before, GitBefore, DataBefore = _files(self.Work.name), Git(), _files(self.Data)
    AssignId = self.run_assign_flow(App)
    self.assertEqual(Git(), GitBefore)
    self.assertEqual(_files(self.Data), DataBefore)
    After = _files(self.Work.name)
    Added = sorted(set(After) - set(Before))
    self.assertEqual(Added, [os.path.join(self.MinutesDir, LOG_NAME)])
    # 회의록 저장소 파일과 실험 경로 요청 산출물은 바뀌지 않는다
    for Path, Digest in Before.items():
      if Path != self.File:
        self.assertEqual(After[Path], Digest, Path)
    with open(os.path.join(self.MinutesDir, LOG_NAME), encoding="utf-8") as File:
      Lines = [json.loads(Line) for Line in File if Line.strip()]
    self.assertEqual(len(Lines), 1)
    Entry = Lines[0]
    Record = App.minutes.get(DocId)
    self.assertEqual((Entry["assign_id"], Entry["meeting_id"], Entry["doc_id"]), (AssignId, "m0007", DocId))
    self.assertEqual((Entry["prompt_version"], Entry["model_id"], Entry["seed"], Entry["raw_sha256"]), (ASSIGN_PROMPT_VERSION, App.model_id, App.gen_seed, Record["raw_sha256"]))
    self.assertEqual(Entry["parsed"], _GOOD)
    self.assertEqual(json.loads(Entry["raw_output"]), _GOOD)
    self.assertIsNone(Entry["error"])
    self.assertTrue(Entry["started_at"] and Entry["ended_at"])
    for Key in ("tasks_dropped", "problems"):
      self.assertIn(Key, Entry)
    # 호출은 한 번이고 설정은 기존 상수와 시드를 쓴다
    Config = self.Calls[0]["config"]
    self.assertEqual((Config.temperature, Config.seed, Config.max_tokens, Config.enable_thinking), (0.0, App.gen_seed, 1024, False))

  def test_unusable_output_fails_the_job_and_creates_nothing(self) -> None:
    App = self.app()
    self.decided(App)
    self.Output = "not json"
    AssignId = self.run_assign_flow(App)
    Info = self.api(App, "GET", "/meetings/m0007/assign", "개인:팀원B")[1]
    self.assertEqual(Info["status"], "failed")
    self.assertTrue(Info["error"].startswith("AssignOutputError"))
    Tasks = self.api(App, "GET", "/tasks", "개인:팀원B", meeting="m0007")[1]["tasks"]
    self.assertFalse([T for T in Tasks if T["source"] != "human"])
    self.assertEqual(self.api(App, "GET", "/meeting-docs", "개인:팀원B")[1], {"documents": []})
    with open(os.path.join(self.MinutesDir, LOG_NAME), encoding="utf-8") as File:
      Entry = json.loads(File.readline())
    self.assertEqual((Entry["assign_id"], Entry["raw_output"], Entry["parsed"]), (AssignId, "not json", None))
    self.assertTrue(Entry["error"].startswith("AssignOutputError"))
    # 잠금이 풀려 있어 고친 출력으로 다시 요청할 수 있다
    self.assertFalse(App.lock.locked())
    self.Output = copy.deepcopy(_GOOD)
    self.run_assign_flow(App)
    self.assertEqual(len(self.api(App, "GET", "/meeting-docs", "개인:팀원B")[1]["documents"]), 1)


class DocumentFileTest(AssignBase):
  def test_start_checks_documents(self) -> None:
    App = self.app()
    with open(self.File, encoding="utf-8") as File:
      Data = json.load(File)
    Good = {
      "doc_id": "d0001", "meeting_id": "m0007", "workspace": {"layer": "팀", "group": "팀1"}, "decisions": ["합성"], "summary": "합성",
      "task_ids": ["t0001"], "status": "proposal", "assign_id": "a1", "created_at": "2026-10-23T10:00", "confirmed_by": None,
      "confirmed_at": None,
    }
    Cases = {
      "다른 workspace": {"workspace": {"layer": "팀", "group": "팀2"}},
      "없는 회의": {"meeting_id": "m9999"},
      "없는 할 일": {"task_ids": ["t9999"]},
      "알 수 없는 status": {"status": "끝"},
      "제안인데 확정자가 있다": {"confirmed_by": "팀원A"},
      "확정인데 확정자가 없다": {"status": "confirmed"},
    }
    def write(Doc):
      Edited = copy.deepcopy(Data)
      Edited["documents"] = [Doc]
      with open(self.File, "w", encoding="utf-8") as File:
        json.dump(Edited, File, ensure_ascii=False)
    write(Good)
    Store = MeetingStore(self.File, None, App.membership, App.labels)
    self.assertEqual([D["doc_id"] for D in Store.list_documents(("개인", "팀원A"))], ["d0001"])
    self.assertEqual(Store.list_documents(("개인", "팀원C")), [])
    for Name, Change in Cases.items():
      write({**Good, **Change})
      with self.assertRaises(ValueError, msg=Name):
        MeetingStore(self.File, None, App.membership, App.labels)
    # 할 일의 evidence 는 있으면 1 ~ 300자 문자열이다
    for Bad in ("", 3, "가" * 301):
      Edited = copy.deepcopy(Data)
      Edited["tasks"][0]["evidence"] = Bad
      with open(self.File, "w", encoding="utf-8") as File:
        json.dump(Edited, File, ensure_ascii=False)
      with self.assertRaises(ValueError, msg=repr(Bad)):
        MeetingStore(self.File, None, App.membership, App.labels)
    # documents 가 없는 파일은 빈 목록으로 읽는다
    with open(self.File, "w", encoding="utf-8") as File:
      json.dump(Data, File, ensure_ascii=False)
    self.assertEqual(MeetingStore(self.File, None, App.membership, App.labels).list_documents(("개인", "팀원A")), [])


if __name__ == "__main__":
  unittest.main()
