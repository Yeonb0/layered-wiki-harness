import contextlib
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime

import serve.demo_api as D
from agent.layer_block import MARK
from agent.llm_client import ChatResult
from runner.v2_sequential import run_v2
from serve.demo_api import DemoApp, make_server
from serve.meetings import MeetingStore

# 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다 ( 합성 시연 코퍼스 소속 표와 같은 모양 )
_TABLE = {"팀원A": ["팀1"], "팀원B": ["팀1"], "팀원C": ["팀2"], "팀원D": ["팀2"], "팀원E": ["팀1", "팀2"], "팀원F": ["팀1", "팀2"]}
_SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo_corpus", "meetings", "seed_meetings.json")
_CRITERIA = f"## 가 {MARK}\n합성 본문\n## 나\n".encode("utf-8")
_CRITERIA_SHA = hashlib.sha256(_CRITERIA).hexdigest()
_NOW = datetime(2026, 10, 24, 9, 30)
_TEAM2_TITLES = ("경제팀 회의 : 상점 개편", "경제팀 회의 : 인플레이션 대응", "환율표 초안", "콤보 보상 의견 모으기 ( 경제팀 쪽 )", "장비 수리비 수치 초안")


def _result(Obj) -> ChatResult:
  return ChatResult(
    text=json.dumps(Obj, ensure_ascii=False), finish_reason="stop", prompt_tokens=1, completion_tokens=1,
    elapsed_seconds=0.1, timings=None, request_body={}, response_body={},
  )


def fake_chat(messages, model_id, config, response_schema, *, timeout_seconds):
  Props = response_schema["properties"]
  if "assign" in Props:
    return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["합성 제목"]})
  return _result({"layer": Props["layer"]["enum"][0], "upward_links": [], "downward_links": [], "rationale": "합성 근거"})


def _embed(Texts):
  return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


class MeetingsBase(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.Tmp = tempfile.TemporaryDirectory()
    Data = os.path.join(cls.Tmp.name, "data")
    os.makedirs(Data)
    Docs = [("문서전사", "전사", None), ("문서팀1", "팀", "팀1")]
    with open(os.path.join(Data, "segments.jsonl"), "w", encoding="utf-8") as File:
      for Id, Layer, Group in Docs:
        File.write(json.dumps({"segment_id": f"{Id}-s1", "doc_id": Id, "seq": 1, "layer": Layer, "group": Group, "text": f"{Id} 합성 글"}, ensure_ascii=False) + "\n")
    with open(os.path.join(Data, "docs.jsonl"), "w", encoding="utf-8") as File:
      for Index, (Id, Layer, Group) in enumerate(Docs):
        File.write(json.dumps({"doc_id": Id, "title": f"{Id} 제목", "layer": Layer, "group": Group, "raw_sha256": f"{Index:064d}"}, ensure_ascii=False) + "\n")
    with open(os.path.join(Data, "ids.txt"), "w", encoding="utf-8") as File:
      File.write("".join(f"{Doc[0]}\n" for Doc in Docs))
    with open(os.path.join(Data, "selection.json"), "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"ids": []}}, File)
    Layers = os.path.join(Data, "source_layers.json")
    with open(Layers, "w", encoding="utf-8") as File:
      json.dump({"personal_owner_teams": _TABLE}, File, ensure_ascii=False)
    with open(os.path.join(Data, "criteria.md"), "wb") as File:
      File.write(_CRITERIA)
    Work = os.path.join(cls.Tmp.name, "work")
    os.makedirs(Work)
    p = lambda Name: os.path.join(Data, Name)
    cls.RunDemo = os.path.join(Work, "demo_run")
    cls.RunReal = os.path.join(Work, "real_run")
    for Out, Snapshot, Kind in ((cls.RunDemo, 900, "demo"), (cls.RunReal, 1, "synthetic")):
      run_v2(
        segments_path=p("segments.jsonl"), docs_path=p("docs.jsonl"), doc_ids_path=p("ids.txt"), split_doc_ids_path=p("ids.txt"),
        selection_path=p("selection.json"), source_layers_path=Layers, criteria_path=p("criteria.md"),
        criteria_sha256=_CRITERIA_SHA, conditions=["제안"], modes=["all_layers", "split_by_layer"], k=3, gen_seed=7, order_seed=11,
        decompose_max_tokens=100, place_max_tokens=50, b1_max_tokens=None, model_id="합성모델", timeout_seconds=9,
        snapshot=Snapshot, run_kind=Kind, out_dir=Out, chat_fn=fake_chat, embed_backend=_embed,
        commit_fn=lambda: "b" * 40, work_root=Work, print_fn=lambda Line: None,
      )

  @classmethod
  def tearDownClass(cls) -> None:
    cls.Tmp.cleanup()

  def setUp(self) -> None:
    self.Work = tempfile.TemporaryDirectory()
    self.addCleanup(self.Work.cleanup)
    self.File = os.path.join(self.Work.name, "meetings.json")

  def app(self, RunDir=None, seeded=True) -> DemoApp:
    App = DemoApp(
      RunDir or self.RunDemo, chat_fn=fake_chat, embed_backend=_embed, commit_fn=lambda: "d" * 40, work_root=self.Work.name,
      print_fn=lambda Line: None,
    )
    if seeded:
      App.meetings = self.store(App)
    return App

  def store(self, App, Seed=_SEED) -> MeetingStore:
    return MeetingStore(self.File, Seed, App.membership, App.labels, now_fn=lambda: _NOW)

  def get(self, App, Path, Viewer, **Query):
    Params = {"viewer": [Viewer], **{key: [value] for key, value in Query.items()}}
    return App.meetings_request("GET", Path, Params, None)

  def post(self, App, Path, Viewer, **Body):
    return App.meetings_request("POST", Path, {}, {"viewer": Viewer, **Body})

  def ids(self, Response, Key="meetings", IdKey="meeting_id"):
    return [Item[IdKey] for Item in Response[Key]]


class SeedTest(MeetingsBase):
  def test_seed_counts_and_members(self) -> None:
    App = self.app()
    Store = App.meetings
    with open(_SEED, encoding="utf-8") as File:
      Seed = json.load(File)
    self.assertEqual((len(Seed["meetings"]), len(Seed["tasks"])), (7, 6))
    for Meeting in Seed["meetings"]:
      Allowed = set(Store.members_of(Meeting["workspace"]))
      self.assertTrue(set(Meeting["attendees"]) <= Allowed, Meeting["meeting_id"])
    for Task in Seed["tasks"]:
      self.assertIn(Task["assignee"], Store.members_of(Task["workspace"]), Task["task_id"])

  def test_members_of(self) -> None:
    Store = self.app().meetings
    self.assertEqual(Store.members_of({"layer": "팀", "group": "팀1"}), ["팀원A", "팀원B", "팀원E", "팀원F"])
    self.assertEqual(Store.members_of({"layer": "개인", "group": "팀원E"}), ["팀원E"])
    self.assertEqual(len(Store.members_of({"layer": "전사", "group": None})), 6)

  def test_invalid_workspaces_raise_value_error(self) -> None:
    Store = self.app().meetings
    for Bad in ({"layer": "팀", "group": "팀9"}, {"layer": "전사", "group": "팀1"}, {"layer": "개인", "group": "없는사람"},
                {"layer": "없는층", "group": None}, {"layer": "팀"}, "팀1"):
      with self.assertRaises(ValueError, msg=Bad):
        Store.members_of(Bad)


class VisibilityTest(MeetingsBase):
  def test_team1_only_member_never_sees_team2_titles(self) -> None:
    App = self.app()
    Text = ""
    for Path in ("/meetings", "/tasks"):
      Status, Body = self.get(App, Path, "개인:팀원A")
      self.assertEqual(Status, 200)
      Text += json.dumps(Body, ensure_ascii=False)
    for Title in _TEAM2_TITLES:
      self.assertNotIn(Title, Text)
    self.assertEqual(self.ids(self.get(App, "/meetings", "개인:팀원A")[1]), ["m0001", "m0003", "m0005", "m0007"])
    self.assertEqual(self.ids(self.get(App, "/tasks", "개인:팀원A")[1], "tasks", "task_id"), ["t0001", "t0002", "t0004"])

  def test_member_of_both_teams_sees_everything_including_own_personal(self) -> None:
    App = self.app()
    Body = self.get(App, "/meetings", "개인:팀원E")[1]
    self.assertEqual(sorted(self.ids(Body)), [f"m000{n}" for n in range(1, 8)])
    self.assertEqual(self.ids(self.get(App, "/tasks", "개인:팀원E")[1], "tasks", "task_id").__len__(), 6)

  def test_other_personal_schedule_is_hidden_and_direct_open_is_404(self) -> None:
    App = self.app()
    Body = self.get(App, "/meetings", "개인:팀원F")[1]
    self.assertNotIn("m0006", self.ids(Body))
    self.assertEqual(len(Body["meetings"]), 6)
    Status, Missing = self.get(App, "/meetings/m0006", "개인:팀원F")
    Status_unknown, Unknown = self.get(App, "/meetings/m9999", "개인:팀원F")
    self.assertEqual(Status, 404)
    # 없는 id 와 볼 수 없는 id 는 같은 응답이다
    self.assertEqual((Status_unknown, Unknown), (Status, Missing))
    self.assertEqual(self.get(App, "/meetings/m0006", "개인:팀원E")[0], 200)

  def test_company_and_team_viewers(self) -> None:
    App = self.app()
    self.assertEqual(self.ids(self.get(App, "/meetings", "전사")[1]), ["m0005"])
    self.assertEqual(self.ids(self.get(App, "/meetings", "팀:팀2")[1]), ["m0002", "m0004", "m0005"])
    self.assertEqual(self.ids(self.get(App, "/tasks", "전사")[1], "tasks", "task_id"), [])

  def test_date_range_and_sorting(self) -> None:
    App = self.app()
    Body = self.get(App, "/meetings", "개인:팀원E", **{"from": "2026-10-14", "to": "2026-10-28"})[1]
    self.assertEqual(self.ids(Body), ["m0003", "m0004", "m0006", "m0005"])
    self.assertEqual(self.get(App, "/meetings", "개인:팀원E", **{"from": "10월"})[0], 400)

  def test_viewer_is_required_and_must_be_listed(self) -> None:
    App = self.app()
    self.assertEqual(App.meetings_request("GET", "/meetings", {}, None)[0], 400)
    self.assertEqual(self.get(App, "/meetings", "개인:없는사람")[0], 400)
    self.assertEqual(App.meetings_request("POST", "/tasks", {}, {"title": "x"})[0], 400)

  def test_bad_paths_and_ids_are_404(self) -> None:
    App = self.app()
    self.assertEqual(self.get(App, "/meetings/M0001", "전사")[0], 404)
    self.assertEqual(self.get(App, "/meetings/" + "a" * 41, "전사")[0], 404)
    self.assertEqual(self.get(App, "/tasks/t0001", "전사")[0], 404)


class CreateTest(MeetingsBase):
  def meeting(self, **Over):
    return {
      "title": "합성 회의", "starts_at": "2026-11-01T10:00", "ends_at": "2026-11-01T11:00",
      "workspace": {"layer": "팀", "group": "팀1"}, "attendees": ["팀원A", "팀원B"], "agenda": ["안건 하나"], **Over,
    }

  def test_creating_in_a_workspace_the_viewer_cannot_see_is_400(self) -> None:
    App = self.app()
    Status, Body = self.post(App, "/meetings", "개인:팀원A", **self.meeting(workspace={"layer": "팀", "group": "팀2"}, attendees=["팀원C"]))
    self.assertEqual(Status, 400)
    self.assertEqual(Body["error_type"], "BadRequest")
    self.assertEqual(self.post(App, "/meetings", "개인:팀원F", **self.meeting(workspace={"layer": "개인", "group": "팀원E"}, attendees=["팀원E"]))[0], 400)

  def test_attendee_outside_the_workspace_is_400(self) -> None:
    App = self.app()
    self.assertEqual(self.post(App, "/meetings", "개인:팀원A", **self.meeting(attendees=["팀원A", "팀원C"]))[0], 400)

  def test_field_checks_are_400(self) -> None:
    App = self.app()
    for Over in (
      {"starts_at": "2026-11-01T11:00", "ends_at": "2026-11-01T10:00"}, {"starts_at": "2026-11-01 10:00"}, {"ends_at": "내일"},
      {"title": ""}, {"title": "가" * 201}, {"status": "열림"}, {"agenda": "안건"}, {"minutes_doc_id": 3},
      {"attendees": ["팀원A", "팀원A"]}, {"meeting_id": "m9999"}, {"created_by": "팀원A"}, {"몰라": 1},
    ):
      self.assertEqual(self.post(App, "/meetings", "개인:팀원A", **self.meeting(**Over))[0], 400, Over)
    self.assertEqual(self.post(App, "/meetings", "개인:팀원A", title="제목만")[0], 400)

  def test_normal_meeting_is_written_to_file_and_read_back_the_same(self) -> None:
    App = self.app()
    Status, Created = self.post(App, "/meetings", "개인:팀원A", **self.meeting())
    self.assertEqual(Status, 201)
    self.assertEqual(Created["meeting_id"], "m0008")
    self.assertEqual((Created["created_by"], Created["updated_at"], Created["status"]), ("팀원A", "2026-10-24T09:30", "scheduled"))
    Reread = MeetingStore(self.File, None, App.membership, App.labels, now_fn=lambda: _NOW)
    Target = ("개인", "팀원A")
    self.assertEqual(Reread.get_meeting(Target, "m0008"), Created)
    self.assertEqual(Reread.list_meetings(Target), App.meetings.list_meetings(Target))
    with open(self.File, encoding="utf-8") as File:
      self.assertEqual(len(json.load(File)["meetings"]), 8)

  def test_update_changes_only_sent_keys_and_rechecks(self) -> None:
    App = self.app()
    Status, Body = self.post(App, "/meetings/m0007", "개인:팀원A", title="바꾼 제목")
    self.assertEqual(Status, 200)
    self.assertEqual((Body["title"], Body["agenda"]), ("바꾼 제목", ["콤보 보상 경험치 / 골드 결정", "밸런스 시트 반영"]))
    self.assertEqual(self.post(App, "/meetings/m0007", "개인:팀원A", attendees=["팀원A", "팀원C"])[0], 400)
    self.assertEqual(self.post(App, "/meetings/m0007", "개인:팀원A", workspace={"layer": "팀", "group": "팀2"})[0], 400)
    # 볼 수 없는 회의는 바꾸려 해도 404 이다
    self.assertEqual(self.post(App, "/meetings/m0002", "개인:팀원A", title="x")[0], 404)

  def test_moving_a_meeting_with_linked_tasks_is_400(self) -> None:
    App = self.app()
    self.assertEqual(self.post(App, "/meetings/m0001", "개인:팀원E", workspace={"layer": "팀", "group": "팀2"}, attendees=["팀원E"])[0], 400)
    # 연결된 할 일이 없는 회의는 옮길 수 있다
    Status, Body = self.post(App, "/meetings/m0007", "개인:팀원E", workspace={"layer": "팀", "group": "팀2"}, attendees=["팀원E"])
    self.assertEqual((Status, Body["workspace"]), (200, {"layer": "팀", "group": "팀2"}))


class TaskTest(MeetingsBase):
  def test_task_on_a_meeting_of_another_workspace_is_400(self) -> None:
    App = self.app()
    Status, _ = self.post(App, "/tasks", "개인:팀원E", title="합성 할 일", assignee="팀원E", meeting_id="m0002", workspace={"layer": "팀", "group": "팀1"})
    self.assertEqual(Status, 400)
    # 볼 수 없는 회의에는 붙일 수 없다
    self.assertEqual(self.post(App, "/tasks", "개인:팀원A", title="합성 할 일", assignee="팀원A", meeting_id="m0002")[0], 400)

  def test_task_inherits_the_meeting_workspace(self) -> None:
    App = self.app()
    Status, Task = self.post(App, "/tasks", "개인:팀원A", title="합성 할 일", assignee="팀원B", meeting_id="m0007", due="2026-11-03")
    self.assertEqual(Status, 201)
    self.assertEqual((Task["task_id"], Task["workspace"], Task["status"], Task["source"], Task["progress"]), ("t0007", {"layer": "팀", "group": "팀1"}, "todo", "human", []))

  def test_agent_sources_cannot_be_created_through_the_api(self) -> None:
    App = self.app()
    for Source in ("agent_proposal", "agent_confirmed", "사람"):
      Status, _ = self.post(App, "/tasks", "개인:팀원A", title="합성 할 일", assignee="팀원A", workspace={"layer": "팀", "group": "팀1"}, source=Source)
      self.assertEqual(Status, 400, Source)

  def test_assignee_and_field_checks(self) -> None:
    App = self.app()
    Base = {"title": "합성 할 일", "workspace": {"layer": "팀", "group": "팀1"}}
    self.assertEqual(self.post(App, "/tasks", "개인:팀원A", assignee="팀원C", **Base)[0], 400)
    self.assertEqual(self.post(App, "/tasks", "개인:팀원A", assignee="팀원A", due="내일", **Base)[0], 400)
    self.assertEqual(self.post(App, "/tasks", "개인:팀원A", assignee="팀원A", status="끝", **Base)[0], 400)
    self.assertEqual(self.post(App, "/tasks", "개인:팀원A", assignee="팀원A", title="", workspace=Base["workspace"])[0], 400)
    self.assertEqual(self.post(App, "/tasks", "개인:팀원A", assignee="팀원A", workspace=Base["workspace"])[0], 400)

  def test_update_task(self) -> None:
    App = self.app()
    Status, Task = self.post(App, "/tasks/t0004", "개인:팀원A", status="done", due="2026-10-30")
    self.assertEqual((Status, Task["status"], Task["due"]), (200, "done", "2026-10-30"))
    self.assertEqual(self.post(App, "/tasks/t0004", "개인:팀원A", assignee="팀원C")[0], 400)
    self.assertEqual(self.post(App, "/tasks/t0004", "개인:팀원A", source="agent_proposal")[0], 400)
    self.assertEqual(self.post(App, "/tasks/t0003", "개인:팀원A", status="done")[0], 404)

  def test_filters(self) -> None:
    App = self.app()
    self.assertEqual(self.ids(self.get(App, "/tasks", "개인:팀원E", meeting="m0001")[1], "tasks", "task_id"), ["t0001", "t0002"])
    self.assertEqual(self.ids(self.get(App, "/tasks", "개인:팀원E", assignee="팀원F")[1], "tasks", "task_id"), ["t0005"])

  def test_progress_has_author_and_time(self) -> None:
    App = self.app()
    Status, Task = self.post(App, "/tasks/t0001/progress", "개인:팀원B", text="합성 진행 기록")
    self.assertEqual(Status, 200)
    self.assertEqual(Task["progress"][-1], {"at": "2026-10-24T09:30", "author": "팀원B", "text": "합성 진행 기록"})

  def test_progress_by_team_or_company_viewer_is_400(self) -> None:
    App = self.app()
    self.assertEqual(self.post(App, "/tasks/t0001/progress", "팀:팀1", text="합성")[0], 400)
    self.assertEqual(self.post(App, "/tasks/t0001/progress", "전사", text="합성")[0], 400)

  def test_progress_text_length_limits(self) -> None:
    App = self.app()
    self.assertEqual(self.post(App, "/tasks/t0001/progress", "개인:팀원B", text="가" * 501)[0], 400)
    self.assertEqual(self.post(App, "/tasks/t0001/progress", "개인:팀원B", text="가" * 500)[0], 200)
    self.assertEqual(self.post(App, "/tasks/t0001/progress", "개인:팀원B", text="")[0], 400)
    self.assertEqual(self.post(App, "/tasks/t0001/progress", "개인:팀원B", text="   ")[0], 400)
    self.assertEqual(self.post(App, "/tasks/t0001/progress", "개인:팀원B", text="합성", 몰라=1)[0], 400)

  def test_progress_on_an_invisible_task_is_404(self) -> None:
    App = self.app()
    self.assertEqual(self.post(App, "/tasks/t0003/progress", "개인:팀원A", text="합성")[0], 404)


class StorageTest(MeetingsBase):
  def test_broken_file_stops_and_is_not_overwritten(self) -> None:
    App = self.app(seeded=False)
    with open(self.File, "w", encoding="utf-8") as File:
      File.write("{깨진 JSON")
    with self.assertRaises(ValueError):
      self.store(App)
    with open(self.File, encoding="utf-8") as File:
      self.assertEqual(File.read(), "{깨진 JSON")

  def test_seed_is_copied_only_when_the_file_is_missing(self) -> None:
    App = self.app(seeded=False)
    self.store(App)
    with open(self.File, "rb") as Copy, open(_SEED, "rb") as Seed:
      self.assertEqual(Copy.read(), Seed.read())
    Store = MeetingStore(self.File, _SEED, App.membership, App.labels, now_fn=lambda: _NOW)
    Store.update_task(("개인", "팀원A"), "t0004", {"status": "done"})
    Again = MeetingStore(self.File, _SEED, App.membership, App.labels, now_fn=lambda: _NOW)
    self.assertEqual(Again.list_tasks(("개인", "팀원A"), "m0003")[0]["status"], "done")

  def test_no_seed_starts_empty(self) -> None:
    App = self.app(seeded=False)
    Store = MeetingStore(self.File, None, App.membership, App.labels)
    self.assertEqual(Store.list_meetings(("전사", None)), [])
    with open(self.File, encoding="utf-8") as File:
      self.assertEqual(json.load(File), {"version": 1, "meetings": [], "tasks": []})

  def test_structure_errors_stop_the_start(self) -> None:
    App = self.app(seeded=False)
    for Content in ('{"version": 2, "meetings": [], "tasks": []}', '{"version": 1, "meetings": {}, "tasks": []}',
                    '{"version": 1, "meetings": [{"meeting_id": "m1"}], "tasks": []}', "[]"):
      with open(self.File, "w", encoding="utf-8") as File:
        File.write(Content)
      with self.assertRaises(ValueError, msg=Content):
        self.store(App)

  def test_writes_leave_no_temp_files(self) -> None:
    App = self.app()
    App.meetings.create_meeting(("개인", "팀원A"), {"title": "합성", "starts_at": "2026-11-01T10:00", "ends_at": "2026-11-01T11:00", "workspace": {"layer": "팀", "group": "팀1"}})
    self.assertEqual(os.listdir(self.Work.name).count("meetings.json"), 1)
    self.assertEqual([Name for Name in os.listdir(self.Work.name) if Name.endswith(".tmp")], [])

  def test_responses_are_masked_through_the_existing_mask(self) -> None:
    # 가린 실행에서는 회의 기능을 켜지 않지만 응답은 항상 _mask 를 통과한다 - 표시 이름이 실제 이름과 같으면 그대로다
    App = self.app()
    Body = self.get(App, "/meetings/m0006", "개인:팀원E")[1]
    self.assertEqual(Body["workspace"], {"layer": "개인", "group": "팀원E"})

  def test_without_a_store_every_route_is_503(self) -> None:
    App = self.app(seeded=False)
    for Method, Path in (("GET", "/meetings"), ("GET", "/tasks"), ("POST", "/meetings"), ("POST", "/tasks/t0001/progress")):
      Status, Body = App.meetings_request(Method, Path, {"viewer": ["전사"]}, {"viewer": "전사"})
      self.assertEqual((Status, Body["error_type"]), (503, "MeetingsNotConfigured"), Path)


class LoadCheckTest(MeetingsBase):
  # 픽스처일 뿐이며 규칙과 무관하다 - 예시 파일을 복사해 규칙을 어기게 고친 파일로 시작을 시험한다
  def write_edited(self, edit) -> None:
    with open(_SEED, encoding="utf-8") as File:
      data = json.load(File)
    edit(data)
    with open(self.File, "w", encoding="utf-8") as File:
      json.dump(data, File, ensure_ascii=False)

  def test_load_rejects_task_linked_to_other_workspace_meeting(self) -> None:
    App = self.app(seeded=False)
    # t0005 는 팀2 할 일인데 팀1 회의 m0003 에 붙인다
    self.write_edited(lambda data: next(t for t in data["tasks"] if t["task_id"] == "t0005").update(meeting_id="m0003"))
    with self.assertRaisesRegex(ValueError, "t0005"):
      self.store(App, Seed=None)

  def test_load_rejects_attendee_outside_workspace(self) -> None:
    App = self.app(seeded=False)
    # 팀2 회의 m0002 참석자에 팀1 만 속한 팀원A 를 넣는다
    self.write_edited(lambda data: next(m for m in data["meetings"] if m["meeting_id"] == "m0002")["attendees"].append("팀원A"))
    with self.assertRaisesRegex(ValueError, "m0002"):
      self.store(App, Seed=None)

  def test_load_rejects_other_rule_violations(self) -> None:
    App = self.app(seeded=False)
    edits = {
      "시각 순서": lambda d: d["meetings"][0].update(starts_at="2026-10-07T16:00"),
      "상태": lambda d: d["tasks"][0].update(status="끝"),
      "기한 형식": lambda d: d["tasks"][0].update(due="내일"),
      "담당자": lambda d: d["tasks"][0].update(assignee="팀원C"),
      "source 값": lambda d: d["tasks"][0].update(source="사람"),
      "진행 기록 형식": lambda d: d["tasks"][0].update(progress=[{"at": "어제", "author": "팀원B", "text": "합성"}]),
      "없는 회의": lambda d: d["tasks"][0].update(meeting_id="m9999"),
    }
    for name, edit in edits.items():
      self.write_edited(edit)
      with self.assertRaises(ValueError, msg=name):
        self.store(App, Seed=None)

  def test_load_accepts_agent_sources_that_the_api_cannot_create(self) -> None:
    App = self.app(seeded=False)
    # API 로 만들 수 없을 뿐 파일에는 있을 수 있다
    self.write_edited(lambda data: data["tasks"][0].update(source="agent_proposal"))
    Store = self.store(App, Seed=None)
    self.assertEqual(Store.list_tasks(("개인", "팀원B"), "m0001")[0]["source"], "agent_proposal")

  def test_seed_passes_full_load_check(self) -> None:
    App = self.app()
    self.assertEqual(len(App.meetings.list_meetings(("개인", "팀원E"))), 7)
    Status, Body = self.get(App, "/tasks", "팀:팀2")
    self.assertEqual(Status, 200)
    self.assertNotIn("m0003", json.dumps(Body, ensure_ascii=False))
    self.assertEqual(self.ids(Body, "tasks", "task_id"), ["t0003", "t0006", "t0005"])


class HttpTest(MeetingsBase):
  def serve(self, App, Cors=None) -> str:
    Server = make_server(App, "127.0.0.1", 0, cors_origin=Cors)
    Thread = threading.Thread(target=Server.serve_forever, daemon=True)
    Thread.start()
    self.addCleanup(Thread.join, 5)
    self.addCleanup(Server.server_close)
    self.addCleanup(Server.shutdown)
    return f"http://127.0.0.1:{Server.server_address[1]}"

  def call(self, Base, Path, Body=None):
    Request = urllib.request.Request(
      Base + Path, data=None if Body is None else json.dumps(Body).encode("utf-8"),
      headers={"Content-Type": "application/json"}, method="GET" if Body is None else "POST",
    )
    try:
      with urllib.request.urlopen(Request, timeout=15) as Response:
        return Response.status, json.loads(Response.read().decode("utf-8")), Response.headers
    except urllib.error.HTTPError as Error:
      with Error:
        return Error.code, json.loads(Error.read().decode("utf-8")), Error.headers

  def test_get_meetings_and_post_progress_round_trip(self) -> None:
    Base = self.serve(self.app())
    Status, Body, _ = self.call(Base, "/meetings?viewer=%EA%B0%9C%EC%9D%B8%3A%ED%8C%80%EC%9B%90A")
    self.assertEqual(Status, 200)
    self.assertEqual(self.ids(Body), ["m0001", "m0003", "m0005", "m0007"])
    Status, Task, _ = self.call(Base, "/tasks/t0001/progress", {"viewer": "개인:팀원B", "text": "합성 진행 기록"})
    self.assertEqual(Status, 200)
    self.assertEqual(Task["progress"][-1]["author"], "팀원B")
    Status, Tasks, _ = self.call(Base, "/tasks?viewer=%EA%B0%9C%EC%9D%B8%3A%ED%8C%80%EC%9B%90B&meeting=m0001")
    self.assertEqual(len(next(T for T in Tasks["tasks"] if T["task_id"] == "t0001")["progress"]), 2)

  def test_create_and_errors_over_http(self) -> None:
    Base = self.serve(self.app())
    Status, Meeting, _ = self.call(Base, "/meetings", {
      "viewer": "개인:팀원A", "title": "합성 회의", "starts_at": "2026-11-01T10:00", "ends_at": "2026-11-01T11:00",
      "workspace": {"layer": "팀", "group": "팀1"}, "attendees": ["팀원A"],
    })
    self.assertEqual((Status, Meeting["meeting_id"]), (201, "m0008"))
    self.assertEqual(self.call(Base, "/meetings", {"title": "viewer 없음"})[0], 400)
    self.assertEqual(self.call(Base, "/meetings/m0006?viewer=%EA%B0%9C%EC%9D%B8%3A%ED%8C%80%EC%9B%90F")[0], 404)
    self.assertEqual(self.call(Base, "/meetings/m0001/progress", {"viewer": "전사"})[0], 404)

  def test_without_meetings_http_is_503(self) -> None:
    Base = self.serve(self.app(seeded=False))
    Status, Body, _ = self.call(Base, "/meetings?viewer=%EC%A0%84%EC%82%AC")
    self.assertEqual((Status, Body["error_type"]), (503, "MeetingsNotConfigured"))
    self.assertEqual(self.call(Base, "/tasks", {"viewer": "전사"})[0], 503)

  def test_cors_headers_are_kept(self) -> None:
    Base = self.serve(self.app(), Cors="http://127.0.0.1:5173")
    Status, _, Headers = self.call(Base, "/meetings?viewer=%EC%A0%84%EC%82%AC")
    self.assertEqual((Status, Headers.get("Access-Control-Allow-Origin")), (200, "http://127.0.0.1:5173"))
    Request = urllib.request.Request(Base + "/meetings", method="OPTIONS")
    with urllib.request.urlopen(Request, timeout=15) as Response:
      self.assertEqual(Response.status, 204)
      self.assertEqual(Response.headers.get("Access-Control-Allow-Methods"), "GET, POST, OPTIONS")

  def test_existing_routes_are_unchanged(self) -> None:
    Base = self.serve(self.app())
    self.assertEqual(self.call(Base, "/health")[0], 200)
    self.assertEqual(self.call(Base, "/viewers")[0], 200)
    self.assertEqual(self.call(Base, "/nope")[0], 404)
    self.assertEqual(self.call(Base, "/meetings/", {"viewer": "전사"})[0], 404)


class ArgsTest(MeetingsBase):
  BASE = ["--run-dir", "r", "--host", "h", "--port", "1"]

  def parse(self, *Extra):
    with contextlib.redirect_stderr(io.StringIO()):
      return D.parse_args(self.BASE + list(Extra))

  def test_seed_alone_exits(self) -> None:
    with self.assertRaises(SystemExit):
      self.parse("--meetings-seed", _SEED)

  def test_file_alone_or_both_or_neither_parse(self) -> None:
    self.assertEqual((self.parse().meetings_file, self.parse().meetings_seed), (None, None))
    self.assertEqual(self.parse("--meetings-file", "f.json").meetings_seed, None)
    Args = self.parse("--meetings-file", "f.json", "--meetings-seed", "s.json")
    self.assertEqual((Args.meetings_file, Args.meetings_seed), ("f.json", "s.json"))

  def test_no_meetings_file_means_no_store(self) -> None:
    self.assertIsNone(D.meetings_from_args(self.parse(), self.app(seeded=False)))

  def test_masked_run_refuses_meetings(self) -> None:
    App = self.app(RunDir=self.RunReal, seeded=False)
    self.assertFalse(App.show_names)
    with self.assertRaises(SystemExit) as Ctx:
      D.meetings_from_args(self.parse("--meetings-file", self.File), App)
    self.assertIn("합성 시연 실행", str(Ctx.exception))

  def test_path_inside_the_repository_is_refused(self) -> None:
    App = self.app(seeded=False)
    Inside = os.path.join(D.REPO_DIR, "demo_corpus", "meetings", "live.json")
    with self.assertRaises(SystemExit):
      D.meetings_from_args(self.parse("--meetings-file", Inside), App)
    self.assertFalse(os.path.exists(Inside))

  def test_path_outside_the_repository_builds_a_store(self) -> None:
    App = self.app(seeded=False)
    Store = D.meetings_from_args(self.parse("--meetings-file", self.File, "--meetings-seed", _SEED), App)
    self.assertIsInstance(Store, MeetingStore)
    self.assertEqual(len(Store.list_meetings(("개인", "팀원E"))), 7)


if __name__ == "__main__":
  unittest.main()
