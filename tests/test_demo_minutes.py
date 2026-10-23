import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime

import serve.demo_api as D
from agent.layer_block import MARK
from agent.llm_client import ChatResult
from runner.v2_sequential import load_source_docs, run_v2
from segmentation.segment import process_doc
from serve.demo_api import DemoApp, make_server
from serve.meetings import MeetingStore
from serve.minutes import MinutesStore

# 픽스처일 뿐이며 규칙과 무관하다 - 이름 · 제목 · 본문은 전부 합성이다 ( 합성 시연 코퍼스 소속 표와 같은 모양 )
_TABLE = {"팀원A": ["팀1"], "팀원B": ["팀1"], "팀원C": ["팀2"], "팀원D": ["팀2"], "팀원E": ["팀1", "팀2"], "팀원F": ["팀1", "팀2"]}
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEED = os.path.join(_ROOT, "demo_corpus", "meetings", "seed_meetings.json")
_CRITERIA = f"## 가 {MARK}\n합성 본문\n## 나\n".encode("utf-8")
_CRITERIA_SHA = hashlib.sha256(_CRITERIA).hexdigest()
_NOW = datetime(2026, 10, 24, 9, 30)
_MINUTES = "# 합성 회의록\n\n## 안건 하나\n합성 내용 하나\n\n## 안건 둘\n합성 내용 둘\n\n## 안건 셋\n합성 내용 셋\n"
_HIDDEN_TITLE = "비공개노트제목QX"
_FIRST_DOC = "90100000000000000000000000000001"


def _result(Text, Finish="stop") -> ChatResult:
  return ChatResult(
    text=Text, finish_reason=Finish, prompt_tokens=1, completion_tokens=1, elapsed_seconds=0.1, timings=None,
    request_body={}, response_body={},
  )


def _chat(messages, model_id, config, response_schema, *, timeout_seconds):
  # 장면은 입력 글의 표지로 가른다 : [[분해실패]] 는 잘린 출력, [[배치실패]] 는 둘째 노트의 배치만 형식 오류
  Text = json.dumps(messages, ensure_ascii=False)
  Props = response_schema["properties"]
  if "assign" in Props:
    if "[[분해실패]]" in Text:
      return _result("", "length")
    Labels = list(Props["assign"]["required"])
    if "문서팀1" in Text:
      Titles = [_HIDDEN_TITLE]
    elif "문서전사" in Text:
      Titles = ["공개노트제목"]
    else:
      Titles = [f"회의록노트{Number}" for Number in range(1, min(3, len(Labels)) + 1)]
      if "[[배치실패]]" in Text and len(Titles) >= 2:
        Titles[1] = "회의록노트2배치실패제목"
    return _result(json.dumps({"assign": {Label: Index % len(Titles) + 1 for Index, Label in enumerate(Labels)}, "titles": Titles}, ensure_ascii=False))
  if "배치실패제목" in Text:
    return _result("not json")
  Up = Props["upward_links"]["items"].get("enum", [])
  Down = Props["downward_links"]["items"].get("enum", [])
  ChosenUp = [next((Id for Id in Up if Id.startswith("901")), Up[0])] if Up else []
  Layer = Props["layer"]["enum"][0]
  # 하향 링크 대상은 노트 층보다 아래여야 한다 - 전사 노트만 팀1 의 기본 노트로 내려 보낸다
  ChosenDown = [Id for Id in Down if Id.startswith("문서팀1#")][:1] if Layer == "전사" else []
  return _result(json.dumps({"layer": Layer, "upward_links": ChosenUp, "downward_links": ChosenDown, "rationale": "근거문장"}, ensure_ascii=False))


def _embed(Texts):
  return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


def _files(Root):
  Found = {}
  for Dir, _, Names in os.walk(Root):
    for Name in Names:
      Path = os.path.join(Dir, Name)
      with open(Path, "rb") as File:
        Found[Path] = hashlib.sha256(File.read()).hexdigest()
  return Found


class MinutesBase(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.Tmp = tempfile.TemporaryDirectory()
    cls.Data = os.path.join(cls.Tmp.name, "data")
    os.makedirs(cls.Data)
    Docs = [("문서전사", "전사", None), ("문서팀1", "팀", "팀1")]
    with open(os.path.join(cls.Data, "segments.jsonl"), "w", encoding="utf-8") as File:
      for Id, Layer, Group in Docs:
        File.write(json.dumps({"segment_id": f"{Id}-s1", "doc_id": Id, "seq": 1, "layer": Layer, "group": Group, "text": f"{Id} 합성 글"}, ensure_ascii=False) + "\n")
    with open(os.path.join(cls.Data, "docs.jsonl"), "w", encoding="utf-8") as File:
      for Index, (Id, Layer, Group) in enumerate(Docs):
        File.write(json.dumps({"doc_id": Id, "title": f"{Id} 제목", "layer": Layer, "group": Group, "raw_sha256": f"{Index:064d}"}, ensure_ascii=False) + "\n")
    with open(os.path.join(cls.Data, "ids.txt"), "w", encoding="utf-8") as File:
      File.write("".join(f"{Doc[0]}\n" for Doc in Docs))
    with open(os.path.join(cls.Data, "selection.json"), "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"ids": []}}, File)
    Layers = os.path.join(cls.Data, "source_layers.json")
    with open(Layers, "w", encoding="utf-8") as File:
      json.dump({"personal_owner_teams": _TABLE}, File, ensure_ascii=False)
    with open(os.path.join(cls.Data, "criteria.md"), "wb") as File:
      File.write(_CRITERIA)
    Work = os.path.join(cls.Tmp.name, "work")
    os.makedirs(Work)
    p = lambda Name: os.path.join(cls.Data, Name)
    cls.RunDemo = os.path.join(Work, "demo_run")
    cls.RunReal = os.path.join(Work, "real_run")
    for Out, Snapshot, Kind in ((cls.RunDemo, 900, "demo"), (cls.RunReal, 1, "synthetic")):
      run_v2(
        segments_path=p("segments.jsonl"), docs_path=p("docs.jsonl"), doc_ids_path=p("ids.txt"), split_doc_ids_path=p("ids.txt"),
        selection_path=p("selection.json"), source_layers_path=Layers, criteria_path=p("criteria.md"),
        criteria_sha256=_CRITERIA_SHA, conditions=["제안"], modes=["all_layers", "split_by_layer"], k=3, gen_seed=7, order_seed=11,
        decompose_max_tokens=100, place_max_tokens=50, b1_max_tokens=None, model_id="합성모델", timeout_seconds=9,
        snapshot=Snapshot, run_kind=Kind, out_dir=Out, chat_fn=_chat, embed_backend=_embed,
        commit_fn=lambda: "b" * 40, work_root=Work, print_fn=lambda Line: None,
      )

  @classmethod
  def tearDownClass(cls) -> None:
    cls.Tmp.cleanup()

  def setUp(self) -> None:
    self.Work = tempfile.TemporaryDirectory()
    self.addCleanup(self.Work.cleanup)
    self.File = os.path.join(self.Work.name, "meetings.json")
    self.MinutesDir = os.path.join(self.Work.name, "minutes")

  def app(self, RunDir=None, Seed=_SEED) -> DemoApp:
    App = DemoApp(
      RunDir or self.RunDemo, chat_fn=_chat, embed_backend=_embed, commit_fn=lambda: "d" * 40, work_root=self.Work.name,
      print_fn=lambda Line: None,
    )
    App.meetings = MeetingStore(self.File, Seed, App.membership, App.labels, now_fn=lambda: _NOW)
    App.attach_minutes(MinutesStore(self.MinutesDir))
    return App

  def post(self, App, Path, Viewer, **Body):
    return App.minutes_request("POST", Path, {}, {"viewer": Viewer, **Body})

  def get(self, App, Path, Viewer):
    return App.minutes_request("GET", Path, {"viewer": [Viewer]}, None)

  def submit(self, App, Viewer="개인:팀원A", Meeting="m0007", Mode="all_layers", Text=_MINUTES) -> str:
    Status, Body = self.post(App, "/minutes", Viewer, meeting_id=Meeting, mode=Mode, text=Text)
    self.assertEqual(Status, 202, Body)
    self.assertTrue(App.jobs[Body["job_id"]]["event"].wait(30))
    return Body["doc_id"]

  def decide(self, App, Viewer, DocId, Items):
    return self.post(App, f"/proposals/{DocId}/decide", Viewer, decisions=Items)

  def view_ids(self, App, Viewer="개인:팀원B", Mode="all_layers"):
    Status, Body = App.view(Mode, Viewer, None)
    self.assertEqual(Status, 200)
    return [Note["note_id"] for Note in Body["notes"]], Body


class SubmitTest(MinutesBase):
  def test_rejections_create_nothing(self) -> None:
    App = self.app()
    Cases = [
      ("개인:팀원C", "m0007"),   # 볼 수 없는 회의
      ("개인:팀원A", "m0002"),   # 다른 팀의 회의
      ("개인:팀원F", "m0004"),   # 볼 수 있지만 참석자가 아니다
      ("팀:팀1", "m0007"),       # 팀 보는 사람
      ("전사", "m0005"),         # 전사 보는 사람
    ]
    for Viewer, Meeting in Cases:
      Status, Body = self.post(App, "/minutes", Viewer, meeting_id=Meeting, mode="all_layers", text=_MINUTES)
      self.assertEqual((Status, Body["error_type"]), (400, "BadRequest"), (Viewer, Meeting))
    self.assertEqual(App.minutes.docs(), [])
    self.assertIsNone(App.meetings.get_meeting(("개인", "팀원A"), "m0007")["minutes_doc_id"])

  def test_personal_schedule_is_refused(self) -> None:
    App = self.app()
    Status, Body = self.post(App, "/minutes", "개인:팀원E", meeting_id="m0006", mode="all_layers", text=_MINUTES)
    self.assertEqual((Status, Body["error_type"]), (400, "BadRequest"))
    self.assertIn("개인 일정에는 회의록을 투입하지 않는다", Body["message"])
    self.assertEqual(App.minutes.docs(), [])

  def test_bad_text_mode_and_keys(self) -> None:
    App = self.app()
    Base = {"meeting_id": "m0007", "mode": "all_layers", "text": _MINUTES}
    for Name, Change in (
      ("빈 text", {"text": ""}), ("공백 text", {"text": "  \n "}), ("너무 긴 text", {"text": "가" * 20001}),
      ("알 수 없는 mode", {"mode": "없는모드"}), ("문자열이 아닌 text", {"text": 3}), ("세그먼트 0개", {"text": "-----"}),
      ("모르는 키", {"layer": "전사"}),
    ):
      Status, _ = self.post(App, "/minutes", "개인:팀원A", **{**Base, **Change})
      self.assertEqual(Status, 400, Name)
    Status, _ = self.post(App, "/minutes", "개인:팀원A", meeting_id="m0007", mode="all_layers")
    self.assertEqual(Status, 400)
    self.assertEqual(App.minutes.docs(), [])

  def test_already_linked_meeting_is_409(self) -> None:
    App = self.app()
    Status, Body = self.post(App, "/minutes", "개인:팀원A", meeting_id="m0001", mode="all_layers", text=_MINUTES)
    self.assertEqual((Status, Body["error_type"]), (409, "MinutesAlreadyLinked"))
    self.submit(App)
    Status, Body = self.post(App, "/minutes", "개인:팀원A", meeting_id="m0007", mode="all_layers", text=_MINUTES)
    self.assertEqual((Status, Body["error_type"]), (409, "MinutesAlreadyLinked"))
    self.assertEqual(len(App.minutes.docs()), 1)

  def test_busy_marks_doc_failed_and_unlinks(self) -> None:
    App = self.app()
    App.lock.acquire()
    try:
      Status, Body = self.post(App, "/minutes", "개인:팀원A", meeting_id="m0007", mode="all_layers", text=_MINUTES)
    finally:
      App.lock.release()
    self.assertEqual((Status, Body["error_type"]), (409, "Busy"))
    Doc = App.minutes.docs()[0]
    self.assertEqual((Doc["status"], Doc["error"]), ("failed", "Busy"))
    self.assertIsNone(App.meetings.get_meeting(("개인", "팀원A"), "m0007")["minutes_doc_id"])
    # 연결이 되돌려졌으니 다시 투입할 수 있다
    self.assertEqual(self.submit(App), "90100000000000000000000000000002")

  def test_segments_follow_rule_v1_1_and_doc_is_registered(self) -> None:
    App = self.app()
    DocId = self.submit(App)
    self.assertEqual(DocId, _FIRST_DOC)
    _, _, Segs = process_doc(_MINUTES, set(), Counter())
    self.assertEqual(len(Segs), 3)
    Record = App.minutes.get(DocId)
    self.assertEqual([S["text"] for S in Record["segments"]], ["\n".join(T for _, T in Seg) for Seg in Segs])
    self.assertEqual([S["segment_id"] for S in Record["segments"]], [f"{DocId}#s{N}" for N in (1, 2, 3)])
    self.assertEqual([S["seq"] for S in Record["segments"]], [1, 2, 3])
    Meeting = App.meetings.get_meeting(("개인", "팀원A"), "m0007")
    self.assertEqual((Record["snapshot"], Record["meeting_id"], Record["raw_text"], Record["title"]), (901, "m0007", _MINUTES, Meeting["title"]))
    self.assertEqual(Record["raw_sha256"], hashlib.sha256(_MINUTES.encode("utf-8")).hexdigest())
    self.assertEqual((Record["source_layer"], Record["source_group"], Record["submitted_by"]), ("팀", "팀1", "팀원A"))
    Doc = App.docs[DocId]
    self.assertEqual((Doc.source_layer, Doc.source_group, Doc.source_team), ("팀", "팀1", None))
    self.assertEqual([S.text for S in Doc.segments], [S["text"] for S in Record["segments"]])
    self.assertEqual(App.raw_sha[DocId], Record["raw_sha256"])
    self.assertEqual(App.meetings.get_meeting(("개인", "팀원A"), "m0007")["minutes_doc_id"], DocId)

  def test_whole_company_meeting_doc_has_no_group_or_team(self) -> None:
    App = self.app()
    DocId = self.submit(App, Meeting="m0005")
    Doc = App.docs[DocId]
    self.assertEqual((Doc.source_layer, Doc.source_group, Doc.source_team), ("전사", None, None))


class SourceDocShapeTest(MinutesBase):
  def test_source_team_is_none_and_loader_gives_the_same_source_doc(self) -> None:
    App = self.app()
    Ids = [self.submit(App, Meeting="m0007"), self.submit(App, Meeting="m0005")]
    Records = [App.minutes.get(Id) for Id in Ids]
    Docs = [App.docs[Id] for Id in Ids]
    self.assertEqual([(D.source_layer, D.source_group, D.source_team) for D in Docs], [("팀", "팀1", None), ("전사", None, None)])
    # 같은 필드 값으로 실험 경로의 docs · segments 레코드 ( team 키 없음 ) 를 만들어 load_source_docs 에 넣는다
    Paths = {Name: os.path.join(self.Work.name, Name) for Name in ("docs.jsonl", "segments.jsonl", "ids.txt", "selection.json")}
    with open(Paths["docs.jsonl"], "w", encoding="utf-8") as File:
      for Record in Records:
        File.write(json.dumps({
          "doc_id": Record["doc_id"], "title": Record["title"], "layer": Record["source_layer"], "group": Record["source_group"],
          "raw_sha256": Record["raw_sha256"],
        }, ensure_ascii=False) + "\n")
    with open(Paths["segments.jsonl"], "w", encoding="utf-8") as File:
      for Record in Records:
        for Seg in Record["segments"]:
          File.write(json.dumps({
            "segment_id": Seg["segment_id"], "doc_id": Record["doc_id"], "seq": Seg["seq"], "layer": Record["source_layer"],
            "group": Record["source_group"], "text": Seg["text"],
          }, ensure_ascii=False) + "\n")
    with open(Paths["ids.txt"], "w", encoding="utf-8") as File:
      File.write("".join(f"{Id}\n" for Id in Ids))
    with open(Paths["selection.json"], "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"ids": []}}, File)
    Loaded, RawSha = load_source_docs(Paths["segments.jsonl"], Paths["docs.jsonl"], Paths["ids.txt"], Paths["ids.txt"], Paths["selection.json"])
    self.assertEqual(sorted(Loaded, key=lambda Doc: Doc.doc_id), Docs)
    self.assertEqual(RawSha, {Record["doc_id"]: Record["raw_sha256"] for Record in Records})


class HttpTest(MinutesBase):
  def serve(self, App) -> str:
    Server = make_server(App, "127.0.0.1", 0)
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
        return Response.status, json.loads(Response.read().decode("utf-8"))
    except urllib.error.HTTPError as Error:
      with Error:
        return Error.code, json.loads(Error.read().decode("utf-8"))

  def test_long_text_and_proposal_routes_over_http(self) -> None:
    App = self.app()
    Base = self.serve(App)
    # 4096 바이트를 넘는 본문도 회의록 경로에서는 받는다
    Text = _MINUTES + "## 긴 안건\n" + "합성 문장입니다.\n" * 1500
    Status, Body = self.call(Base, "/minutes", {"viewer": "개인:팀원A", "meeting_id": "m0007", "mode": "all_layers", "text": Text})
    self.assertEqual(Status, 202, Body)
    self.assertTrue(App.jobs[Body["job_id"]]["event"].wait(30))
    Status, Listed = self.call(Base, "/proposals?viewer=%EA%B0%9C%EC%9D%B8%3A%ED%8C%80%EC%9B%90B")
    self.assertEqual(Status, 200)
    self.assertEqual([Item["doc_id"] for Item in Listed["proposals"]], [Body["doc_id"]])
    Status, _ = self.call(Base, f"/proposals/{Body['doc_id']}?viewer=%EA%B0%9C%EC%9D%B8%3A%ED%8C%80%EC%9B%90C")
    self.assertEqual(Status, 404)
    # 다른 경로의 본문 상한은 그대로다
    Status, _ = self.call(Base, "/jobs", {"doc_id": "문서전사", "mode": "all_layers", "pad": "가" * 5000})
    self.assertEqual(Status, 400)

  def test_routes_are_503_without_stores(self) -> None:
    App = self.app()
    App.minutes = None
    self.assertEqual(self.get(App, "/proposals", "개인:팀원A")[1]["error_type"], "MinutesNotConfigured")
    App.meetings = None
    self.assertEqual(self.get(App, "/proposals", "개인:팀원A")[1]["error_type"], "MeetingsNotConfigured")


class FlowTest(MinutesBase):
  def test_nothing_enters_view_until_all_notes_are_decided(self) -> None:
    App = self.app()
    DocId = self.submit(App)
    self.assertEqual(App.minutes.get(DocId)["status"], "awaiting_approval")
    Ids, Body = self.view_ids(App)
    self.assertFalse([Id for Id in Ids if Id.startswith("901")])
    self.assertEqual(Body["counts"]["minutes_notes_included"], 0)
    Status, Listed = self.get(App, "/proposals", "개인:팀원B")
    self.assertEqual(Listed["proposals"], [{
      "doc_id": DocId, "meeting_id": "m0007", "mode": "all_layers", "status": "awaiting_approval", "note_count": 3,
      "approved": 0, "rejected": 0, "pending": 3,
    }])
    Status, Detail = self.get(App, f"/proposals/{DocId}", "개인:팀원B")
    self.assertEqual([N["note_index"] for N in Detail["notes"]], [0, 1, 2])
    self.assertEqual([N["title"] for N in Detail["notes"]], ["회의록노트1", "회의록노트2", "회의록노트3"])
    self.assertTrue(all(N["decision"] is None and N["layer"] == "팀" and N["group_label"] == "팀1" for N in Detail["notes"]))
    # 일부만 결정해도 아직 보기에 없다
    Status, Body = self.decide(App, "개인:팀원B", DocId, [{"note_index": 0, "decision": "approve"}, {"note_index": 1, "decision": "reject"}])
    self.assertEqual((Status, Body["status"], Body["pending"]), (200, "awaiting_approval", 1))
    self.assertFalse([Id for Id in self.view_ids(App)[0] if Id.startswith("901")])
    Status, Body = self.decide(App, "개인:팀원E", DocId, [{"note_index": 2, "decision": "approve"}])
    self.assertEqual((Status, Body["status"], Body["approved"], Body["rejected"]), (200, "decided", 2, 1))
    Ids, Body = self.view_ids(App)
    self.assertEqual([Id for Id in Ids if Id.startswith("901")], [f"{DocId}#n0", f"{DocId}#n2"])
    self.assertEqual(Body["counts"]["minutes_notes_included"], 2)
    # 그 doc 의 mode 보기에만 겹친다
    Ids, Body = self.view_ids(App, Mode="split_by_layer")
    self.assertFalse([Id for Id in Ids if Id.startswith("901")])
    self.assertEqual(Body["counts"]["minutes_notes_included"], 0)
    Detail = self.get(App, f"/proposals/{DocId}", "개인:팀원B")[1]
    self.assertEqual([N["decision"]["decision"] for N in Detail["notes"]], ["approve", "reject", "approve"])
    self.assertEqual([N["decision"]["by"] for N in Detail["notes"]], ["팀원B", "팀원B", "팀원E"])

  def test_links_to_rejected_notes_are_dropped_and_counted(self) -> None:
    App = self.app()
    DocId = self.submit(App)
    Record = App.minutes.get(DocId)
    with open(os.path.join(Record["request_dir"], "new_notes.jsonl"), encoding="utf-8") as File:
      New = {Note["note_id"]: Note for Note in (json.loads(Line) for Line in File if Line.strip())}
    Targets = lambda Note: Note["upward_links"] + [Link["target_id"] for Link in Note["downward_conditional_links"]]
    Expected = sum(Targets(New[f"{DocId}#n{Index}"]).count(f"{DocId}#n0") for Index in (1, 2))
    # 반려한 노트를 가리키는 링크가 실제로 있어야 이 시험이 뜻을 갖는다
    self.assertGreater(Expected, 0)
    self.decide(App, "개인:팀원A", DocId, [
      {"note_index": 0, "decision": "reject"}, {"note_index": 1, "decision": "approve"}, {"note_index": 2, "decision": "approve"},
    ])
    Done = App.minutes.get(DocId)
    self.assertEqual(Done["approved_links_dropped"], Expected)
    for Note in Done["approved_notes"]:
      self.assertNotIn(f"{DocId}#n0", Note["upward_links"])
      self.assertNotIn(f"{DocId}#n0", [L["target_id"] for L in Note["downward_conditional_links"]])
    Ids, _ = self.view_ids(App)
    self.assertNotIn(f"{DocId}#n0", Ids)

  def test_partial_placement_failure_cannot_be_approved(self) -> None:
    App = self.app()
    DocId = self.submit(App, Text=_MINUTES + "[[배치실패]]\n")
    self.assertEqual(App.minutes.get(DocId)["status"], "awaiting_approval")
    Detail = self.get(App, f"/proposals/{DocId}", "개인:팀원A")[1]
    Failed = Detail["notes"][1]
    self.assertEqual((Failed["title"], Failed["layer"], Failed["problems"]), ("회의록노트2배치실패제목", None, ["not_json"]))
    Status, Body = self.decide(App, "개인:팀원A", DocId, [{"note_index": 1, "decision": "approve"}])
    self.assertEqual(Status, 400, Body)
    self.assertEqual(App.minutes.get(DocId)["decisions"], {})
    Status, Body = self.decide(App, "개인:팀원A", DocId, [
      {"note_index": 0, "decision": "approve"}, {"note_index": 1, "decision": "reject"}, {"note_index": 2, "decision": "approve"},
    ])
    self.assertEqual((Status, Body["status"]), (200, "decided"))

  def test_decompose_failure_makes_doc_failed(self) -> None:
    App = self.app()
    DocId = self.submit(App, Text=_MINUTES + "[[분해실패]]\n")
    Record = App.minutes.get(DocId)
    self.assertEqual(Record["status"], "failed")
    self.assertTrue(Record["error"].startswith("DecomposeFailed"))
    Status, Body = self.decide(App, "개인:팀원A", DocId, [{"note_index": 0, "decision": "approve"}])
    self.assertEqual((Status, Body["error_type"]), (409, "Conflict"))
    self.assertEqual(self.get(App, "/proposals", "개인:팀원A")[1]["proposals"][0]["status"], "failed")
    # 실패한 투입은 기록으로 남고 회의 연결은 풀린다
    self.assertIsNone(App.meetings.get_meeting(("개인", "팀원A"), "m0007")["minutes_doc_id"])
    self.assertEqual(App.minutes.get(DocId)["status"], "failed")
    # 같은 회의에 다시 투입할 수 있고 목록에는 실패 doc 와 새 doc 가 status 로 구분돼 나온다
    Status, Body = self.post(App, "/minutes", "개인:팀원A", meeting_id="m0007", mode="all_layers", text=_MINUTES)
    self.assertEqual(Status, 202, Body)
    self.assertTrue(App.jobs[Body["job_id"]]["event"].wait(30))
    Listed = self.get(App, "/proposals", "개인:팀원A")[1]["proposals"]
    self.assertEqual([(Item["doc_id"], Item["status"]) for Item in Listed], [(DocId, "failed"), (Body["doc_id"], "awaiting_approval")])
    self.assertEqual(App.meetings.get_meeting(("개인", "팀원A"), "m0007")["minutes_doc_id"], Body["doc_id"])

  def test_decide_rules(self) -> None:
    App = self.app()
    DocId = self.submit(App)
    Approve = lambda Index: {"note_index": Index, "decision": "approve"}
    Bad = [
      [{"note_index": 0, "decision": "approve", "layer": "전사"}],
      [{"note_index": 0, "decision": "approve", "group": "팀2"}],
      [{"note_index": 0, "decision": "approve", "upward_links": []}],
      [Approve(99)], [{"note_index": 0, "decision": "승인"}], [{"note_index": True, "decision": "approve"}],
      [Approve(0), Approve(0)], [Approve(0), Approve(99)], [], "approve",
    ]
    for Items in Bad:
      Status, _ = self.decide(App, "개인:팀원A", DocId, Items)
      self.assertEqual(Status, 400, Items)
    Status, _ = self.post(App, f"/proposals/{DocId}/decide", "개인:팀원A", decisions=[Approve(0)], layer="전사")
    self.assertEqual(Status, 400)
    self.assertEqual(App.minutes.get(DocId)["decisions"], {})
    # 팀 보는 사람은 볼 수 있어도 결정하지 못한다
    self.assertEqual(self.decide(App, "팀:팀1", DocId, [Approve(0)])[0], 400)
    self.assertEqual(self.decide(App, "개인:팀원A", DocId, [Approve(0)])[0], 200)
    # 이미 결정된 note_index 는 바꾸지 않는다
    Status, _ = self.decide(App, "개인:팀원A", DocId, [{"note_index": 0, "decision": "reject"}])
    self.assertEqual(Status, 400)
    self.assertEqual(App.minutes.get(DocId)["decisions"]["0"]["decision"], "approve")
    self.assertEqual(self.decide(App, "개인:팀원A", DocId, [Approve(1), Approve(2)])[1]["status"], "decided")
    Status, Body = self.decide(App, "개인:팀원A", DocId, [Approve(1)])
    self.assertEqual((Status, Body["error_type"]), (409, "Conflict"))

  def test_other_team_sees_nothing_of_the_proposal(self) -> None:
    App = self.app()
    DocId = self.submit(App)
    self.decide(App, "개인:팀원A", DocId, [{"note_index": I, "decision": "approve"} for I in (0, 1, 2)])
    # 같은 팀은 보인다 ( 대조군 )
    self.assertEqual(len(self.get(App, "/proposals", "개인:팀원B")[1]["proposals"]), 1)
    Texts = []
    Status, Body = self.get(App, "/proposals", "개인:팀원C")
    self.assertEqual((Status, Body), (200, {"proposals": []}))
    Texts.append(json.dumps(Body, ensure_ascii=False))
    for Path in (f"/proposals/{DocId}", f"/proposals/{DocId}/trace"):
      Status, Body = self.get(App, Path, "개인:팀원C")
      self.assertEqual(Status, 404)
      Texts.append(json.dumps(Body, ensure_ascii=False))
    Status, Body = self.decide(App, "개인:팀원C", DocId, [{"note_index": 0, "decision": "reject"}])
    self.assertEqual(Status, 404)
    Texts.append(json.dumps(Body, ensure_ascii=False))
    for Mode in ("all_layers", "split_by_layer"):
      Status, View = App.view(Mode, "개인:팀원C", None)
      self.assertEqual(Status, 200)
      Texts.append(json.dumps(View, ensure_ascii=False))
    for Text in Texts:
      self.assertNotIn(DocId, Text)
      self.assertNotIn("회의록노트", Text)
    self.assertEqual(App.minutes.get(DocId)["status"], "decided")

  def test_trace_hides_what_the_viewer_cannot_see(self) -> None:
    App = self.app()
    # 전사 회의록의 노트는 전사 층이고 후보에 팀1 의 노트가 섞인다 - 팀2 만 속한 팀원C 는 그 노트를 볼 수 없다
    DocId = self.submit(App, Meeting="m0005")
    Hidden = next(Note for Note in App.cells["all_layers"]["notes"] if Note.title == _HIDDEN_TITLE)
    Status, Trace = self.get(App, f"/proposals/{DocId}/trace", "개인:팀원C")
    self.assertEqual(Status, 200)
    Text = json.dumps(Trace, ensure_ascii=False)
    self.assertNotIn(_HIDDEN_TITLE, Text)
    self.assertNotIn(Hidden.note_id, Text)
    # 프롬프트와 원문은 내보내지 않는다
    self.assertNotIn("합성 내용 하나", Text)
    self.assertNotIn("raw_text", Text)
    self.assertEqual(len(Trace["places"]), 3)
    First = Trace["places"][0]
    self.assertEqual(First["hidden_candidates"], 1)
    self.assertIsNone(First["rationale"])
    self.assertTrue(First["rationale_hidden"])
    self.assertEqual(First["hidden_links"], 1)
    self.assertEqual(First["downward_links"], [])
    self.assertTrue(all(Cand["id"] != Hidden.note_id for Place in Trace["places"] for Cand in Place["candidates"]))
    self.assertEqual([N["title"] for N in Trace["decompose"]["notes"]], ["회의록노트1", "회의록노트2", "회의록노트3"])
    self.assertEqual(sorted(S for N in Trace["decompose"]["notes"] for S in N["segment_ids"]), [f"{DocId}#s{N}" for N in (1, 2, 3)])
    # 대조군 : 팀1 노트를 볼 수 있는 팀원A 에게는 후보와 근거가 그대로 보인다
    Seen = self.get(App, f"/proposals/{DocId}/trace", "개인:팀원A")[1]["places"][0]
    self.assertEqual(Seen["hidden_candidates"], 0)
    self.assertEqual(Seen["rationale"], "근거문장")
    self.assertIn(_HIDDEN_TITLE, [Cand["title"] for Cand in Seen["candidates"]])
    self.assertEqual(Seen["downward_links"], [Hidden.note_id])


class StorageTest(MinutesBase):
  def test_nothing_is_written_to_repository_or_corpus(self) -> None:
    Git = lambda: subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=_ROOT, capture_output=True, text=True, check=True).stdout
    Before, DataBefore, TmpBefore = Git(), _files(self.Data), set(_files(self.Tmp.name))
    App = self.app()
    DocId = self.submit(App)
    self.decide(App, "개인:팀원A", DocId, [{"note_index": I, "decision": "approve"} for I in (0, 1, 2)])
    self.assertEqual(Git(), Before)
    self.assertEqual(_files(self.Data), DataBefore)
    self.assertEqual(set(_files(self.Tmp.name)), TmpBefore)
    # 새로 생긴 파일은 회의록 폴더 · 회의 파일 · 시연 작업 폴더의 요청 산출물뿐이다
    Allowed = (self.MinutesDir, self.File, os.path.join(self.Work.name, D.REQUEST_SUBDIR))
    for Path in _files(self.Work.name):
      self.assertTrue(any(Path.startswith(Prefix) for Prefix in Allowed), Path)
    self.assertTrue(os.path.isfile(os.path.join(self.MinutesDir, "minutes_901.json")))

  def test_restart_keeps_docs_and_approved_notes(self) -> None:
    App = self.app()
    DocId = self.submit(App)
    self.decide(App, "개인:팀원A", DocId, [
      {"note_index": 0, "decision": "approve"}, {"note_index": 1, "decision": "reject"}, {"note_index": 2, "decision": "approve"},
    ])
    Before = self.view_ids(App)
    Again = self.app(Seed=None)
    self.assertIn(DocId, Again.docs)
    self.assertEqual(Again.raw_sha[DocId], App.raw_sha[DocId])
    self.assertEqual(self.view_ids(Again), Before)
    self.assertEqual(self.get(Again, "/proposals", "개인:팀원B"), self.get(App, "/proposals", "개인:팀원B"))
    self.assertEqual(Again.meetings.get_meeting(("개인", "팀원A"), "m0007")["minutes_doc_id"], DocId)

  def test_running_doc_found_at_start_is_marked_failed(self) -> None:
    Store = MinutesStore(self.MinutesDir)
    Store.create(
      {"meeting_id": "m0007", "title": "합성 회의", "workspace": {"layer": "팀", "group": "팀1"}}, "all_layers", _MINUTES, "팀원A", _NOW,
    )
    # 회의록 저장소를 붙이기 전에 연결부터 걸어 둔다 - 서버가 꺼질 때의 상태다
    Before = DemoApp(
      self.RunDemo, chat_fn=_chat, embed_backend=_embed, commit_fn=lambda: "d" * 40, work_root=self.Work.name, print_fn=lambda Line: None,
    )
    MeetingStore(self.File, _SEED, Before.membership, Before.labels, now_fn=lambda: _NOW).link_minutes("m0007", _FIRST_DOC)
    App = self.app(Seed=None)
    Record = App.minutes.get(_FIRST_DOC)
    self.assertEqual(Record["status"], "failed")
    self.assertTrue(Record["error"].startswith("Interrupted"))
    # 연결을 걸어 둔 채 멈춘 doc 도 시작 때 연결이 풀린다
    self.assertIsNone(App.meetings.get_meeting(("개인", "팀원A"), "m0007")["minutes_doc_id"])

  def test_broken_minutes_file_stops_start(self) -> None:
    os.makedirs(self.MinutesDir)
    with open(os.path.join(self.MinutesDir, "minutes_901.json"), "w", encoding="utf-8") as File:
      File.write("{깨짐")
    with self.assertRaises(ValueError):
      MinutesStore(self.MinutesDir)


class ArgsTest(MinutesBase):
  def test_minutes_dir_needs_meetings_file(self) -> None:
    Needed = ["--run-dir", "x", "--host", "127.0.0.1", "--port", "1"]
    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
      D.parse_args(Needed + ["--minutes-dir", "y"])
    self.assertEqual(D.parse_args(Needed).minutes_dir, None)
    self.assertEqual(D.parse_args(Needed + ["--meetings-file", "a", "--minutes-dir", "y"]).minutes_dir, "y")

  def test_masked_run_and_repository_path_are_refused(self) -> None:
    App = self.app()
    Args = argparse.Namespace(minutes_dir=os.path.join(self.Work.name, "ok_minutes"))
    self.assertIsNone(D.minutes_from_args(argparse.Namespace(minutes_dir=None), App))
    self.assertIsInstance(D.minutes_from_args(Args, App), MinutesStore)
    Real = DemoApp(
      self.RunReal, chat_fn=_chat, embed_backend=_embed, commit_fn=lambda: "d" * 40, work_root=self.Work.name, print_fn=lambda Line: None,
    )
    with self.assertRaises(SystemExit):
      D.minutes_from_args(Args, Real)
    Inside = argparse.Namespace(minutes_dir=os.path.join(self.Work.name, "inside", "minutes"))
    with self.assertRaises(SystemExit):
      D.minutes_from_args(Inside, App, repo_dir=self.Work.name)


if __name__ == "__main__":
  unittest.main()
