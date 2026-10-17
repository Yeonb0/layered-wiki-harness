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
from contextlib import redirect_stdout
from unittest import mock

import serve.demo_api as D
from agent.layer_block import MARK
from agent.llm_client import ChatResult
from retrieval.search import _embedding_text
from runner.v2_sequential import run_v2
from serve.demo_api import DemoApp, make_server, owner_labels

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다 ( 주인 이름도 합성 )
_OWNERS = ["샘플가", "샘플나"]
_CRITERIA = f"## 가 {MARK}\n합성 본문\n## 나\n".encode("utf-8")
_CRITERIA_SHA = hashlib.sha256(_CRITERIA).hexdigest()
# 문서 id 를 8자보다 길게 해서 요청 폴더 이름이 앞 8자로 잘리는지 본다
_DOCS = [
  ("합성문서번호0000", "개인", "샘플가"),
  ("합성문서번호0001", "개인", "샘플나"),
  ("합성문서번호0002", "팀", "1조"),
  ("합성문서번호0003", "팀", "1조"),
]


def _result(Obj) -> ChatResult:
  return ChatResult(
    text=json.dumps(Obj, ensure_ascii=False), finish_reason="stop", prompt_tokens=1, completion_tokens=1,
    elapsed_seconds=0.1, timings=None, request_body={}, response_body={},
  )


def fake_chat(messages, model_id, config, response_schema, *, timeout_seconds):
  # 스키마 모양으로 호출 종류를 알아보고, 노트 층은 스키마 enum 의 첫 값 ( 출처 층 ) 으로 낸다
  Props = response_schema["properties"]
  if "assign" in Props:
    return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["합성 제목"]})
  Down = Props["downward_links"].get("items", {}).get("enum", [])
  return _result({
    "layer": Props["layer"]["enum"][0], "upward_links": [], "downward_links": Down[:1], "rationale": "합성 근거",
  })


def fake_chat_above_source(messages, model_id, config, response_schema, *, timeout_seconds):
  # 층별 분리 모드에서 출처 위 층을 내는 가짜 출력 - 스키마 enum 을 무시한다
  Props = response_schema["properties"]
  if "assign" in Props:
    return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["합성 제목"]})
  return _result({"layer": "전사", "upward_links": [], "downward_links": [], "rationale": "합성 근거"})


class Backend:
  # 임베딩 호출을 세는 합성 백엔드 - 서버를 부르지 않는다
  def __init__(self) -> None:
    self.texts = []

  def __call__(self, Texts):
    self.texts.extend(Texts)
    return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


class DemoBase(unittest.TestCase):
  def setUp(self) -> None:
    self.Tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.Tmp.cleanup)
    self.Data = os.path.join(self.Tmp.name, "data")
    self.Work = os.path.join(self.Tmp.name, "work")
    self.DemoWork = os.path.join(self.Tmp.name, "demo_work")
    for Path in (self.Data, self.Work, self.DemoWork):
      os.makedirs(Path)
    self.write_corpus()
    self.Lines = []
    self.RunDir = os.path.join(self.Work, "base_run")
    run_v2(
      segments_path=self.p("segments.jsonl"), docs_path=self.p("docs.jsonl"), doc_ids_path=self.p("ids.txt"),
      split_doc_ids_path=self.p("ids.txt"), selection_path=self.p("selection.json"),
      source_layers_path=self.p("source_layers.json"), criteria_path=self.p("criteria.md"),
      criteria_sha256=_CRITERIA_SHA, conditions=["제안"], modes=["all_layers", "split_by_layer"], k=3, gen_seed=7,
      order_seed=11, decompose_max_tokens=100, place_max_tokens=50, b1_max_tokens=None, model_id="합성모델",
      timeout_seconds=9, snapshot=1, run_kind="synthetic", out_dir=self.RunDir, chat_fn=fake_chat,
      embed_backend=Backend(), commit_fn=lambda: "b" * 40, work_root=self.Work, print_fn=lambda Line: None,
    )

  def p(self, Name: str) -> str:
    return os.path.join(self.Data, Name)

  def write_corpus(self) -> None:
    Ids = [Doc[0] for Doc in _DOCS]
    with open(self.p("segments.jsonl"), "w", encoding="utf-8") as File:
      for Id, Layer, Group in _DOCS:
        for Seq in (1, 2):
          File.write(json.dumps({
            "segment_id": f"{Id}-s{Seq}", "doc_id": Id, "seq": Seq, "layer": Layer, "group": Group,
            "text": f"{Id} 합성 글 {Seq}",
          }, ensure_ascii=False) + "\n")
    with open(self.p("docs.jsonl"), "w", encoding="utf-8") as File:
      for Index, (Id, Layer, Group) in enumerate(_DOCS):
        File.write(json.dumps(
          {"doc_id": Id, "title": f"{Id} 제목", "layer": Layer, "group": Group, "raw_sha256": f"{Index:064d}"},
          ensure_ascii=False,
        ) + "\n")
    with open(self.p("ids.txt"), "w", encoding="utf-8") as File:
      File.write("".join(f"{Id}\n" for Id in Ids))
    with open(self.p("selection.json"), "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"ids": []}}, File)
    with open(self.p("source_layers.json"), "w", encoding="utf-8") as File:
      json.dump({"team_1jo_personal_owners": _OWNERS}, File, ensure_ascii=False)
    with open(self.p("criteria.md"), "wb") as File:
      File.write(_CRITERIA)

  def app(self, Chat=fake_chat, Backend_=None, RunDir=None) -> DemoApp:
    return DemoApp(
      RunDir or self.RunDir, chat_fn=Chat, embed_backend=Backend_ or Backend(), commit_fn=lambda: "d" * 40,
      work_root=self.DemoWork, print_fn=self.Lines.append,
    )

  def edit_manifest(self, **Over) -> str:
    # 원본 실행 폴더를 건드리지 않고 manifest 만 바꾼 복사본을 만든다
    import shutil

    Copy = os.path.join(self.Work, "edited_run")
    shutil.copytree(self.RunDir, Copy)
    Path = os.path.join(Copy, "manifest.json")
    with open(Path, encoding="utf-8") as File:
      Manifest = json.load(File)
    for Key, Value in Over.items():
      if Key == "conditions":
        Manifest["args"]["conditions"] = Value
      else:
        Manifest[Key] = Value
    with open(Path, "w", encoding="utf-8") as File:
      json.dump(Manifest, File, ensure_ascii=False)
    return Copy


class StartupTest(DemoBase):
  def test_incomplete_run_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      self.app(RunDir=self.edit_manifest(status="aborted"))

  def test_non_propose_conditions_raise_value_error(self) -> None:
    with self.assertRaises(ValueError):
      self.app(RunDir=self.edit_manifest(conditions=["제안", "B1"]))
    import shutil

    shutil.rmtree(os.path.join(self.Work, "edited_run"))
    with self.assertRaises(ValueError):
      self.app(RunDir=self.edit_manifest(conditions=["B1"]))

  def test_embeds_each_base_note_once_at_start(self) -> None:
    Counter = Backend()
    App = self.app(Backend_=Counter)
    Total = sum(len(Cell["notes"]) for Cell in App.cells.values())
    self.assertGreater(Total, 0)
    self.assertEqual(len(Counter.texts), Total)

  def test_startup_screen_has_numbers_only(self) -> None:
    self.app()
    Joined = "\n".join(self.Lines)
    self.assertIn("embedded=", Joined)
    for Word in ("합성 제목", "샘플가", "샘플나"):
      self.assertNotIn(Word, Joined)

  def test_health_and_docs(self) -> None:
    App = self.app()
    Health = App.health()
    self.assertEqual(Health["status"], "ok")
    self.assertEqual(sorted(Health["modes"]), ["all_layers", "split_by_layer"])
    self.assertEqual(Health["base_run"], "base_run")
    self.assertEqual(Health["base_notes"], {Mode: len(Cell["notes"]) for Mode, Cell in App.cells.items()})
    Docs = App.doc_list()
    self.assertEqual({Doc["doc_id"] for Doc in Docs}, {Doc[0] for Doc in _DOCS})
    for Doc in Docs:
      self.assertEqual(sorted(Doc), ["chars", "doc_id", "layer", "segments"])
    self.assertNotIn("제목", json.dumps(Docs, ensure_ascii=False))
    self.assertNotIn("샘플가", json.dumps(Docs, ensure_ascii=False))


class RequestStateTest(DemoBase):
  def test_own_notes_are_removed_and_other_notes_can_be_candidates(self) -> None:
    App = self.app()
    DocId = _DOCS[2][0]
    Status, Response = App.run({"doc_id": DocId, "mode": "all_layers"})
    self.assertEqual(Status, 200)
    OwnIds = {Note.note_id for Note in App.cells["all_layers"]["notes"] if Note.source_doc_id == DocId}
    self.assertTrue(OwnIds)
    Seen = {Cand["id"] for Note in Response["notes"] for Cand in Note["candidates"]}
    self.assertFalse(Seen & OwnIds)
    OtherIds = {Note.note_id for Note in App.cells["all_layers"]["notes"] if Note.source_doc_id != DocId}
    self.assertTrue(Seen)
    self.assertTrue(Seen <= OtherIds)

  def test_base_state_is_unchanged_and_repeated_requests_do_not_collide(self) -> None:
    App = self.app()
    Before = {Mode: (len(Cell["notes"]), len(Cell["retriever"].Index), len(Cell["retriever"].Groups)) for Mode, Cell in App.cells.items()}
    DocId = _DOCS[2][0]
    First = App.run({"doc_id": DocId, "mode": "all_layers"})[1]
    Second = App.run({"doc_id": DocId, "mode": "all_layers"})[1]
    After = {Mode: (len(Cell["notes"]), len(Cell["retriever"].Index), len(Cell["retriever"].Groups)) for Mode, Cell in App.cells.items()}
    self.assertEqual(Before, After)
    self.assertNotEqual(First["request_dir"], Second["request_dir"])
    for Response in (First, Second):
      Ids = [Note["note_id"] for Note in Response["notes"]]
      self.assertEqual(len(Ids), len(set(Ids)))
    self.assertEqual(
      [Note["note_id"] for Note in First["notes"]], [Note["note_id"] for Note in Second["notes"]]
    )

  def test_embedding_calls_during_request_cover_only_new_work(self) -> None:
    Counter = Backend()
    App = self.app(Backend_=Counter)
    Start = len(Counter.texts)
    DocId = _DOCS[2][0]
    Response = App.run({"doc_id": DocId, "mode": "all_layers"})[1]
    Made = Counter.texts[Start:]
    # 검색 질의 ( 노트 하나당 한 번 ) + 새 노트 색인 ( 노트 하나당 한 번 ) 뿐이다
    self.assertEqual(len(Made), 2 * len(Response["notes"]))
    BaseTexts = {
      _embedding_text(Rec) for Rec, _ in App.cells["all_layers"]["retriever"].Index if not Rec.id.startswith(DocId)
    }
    # 요청 문서가 아닌 기본 노트는 다시 임베딩하지 않았다
    self.assertFalse(BaseTexts & set(Made))

  def test_request_files_are_written(self) -> None:
    App = self.app()
    DocId = _DOCS[2][0]
    Response = App.run({"doc_id": DocId, "mode": "split_by_layer"})[1]
    Dir = Response["request_dir"]
    self.assertTrue(os.path.basename(Dir).endswith(f"_{DocId[:8]}_split_by_layer"))
    self.assertTrue(Dir.startswith(os.path.join(self.DemoWork, "demo_api")))
    for Name in ("request_manifest.json", "log.jsonl", "new_notes.jsonl"):
      self.assertTrue(os.path.isfile(os.path.join(Dir, Name)))
    with open(os.path.join(Dir, "request_manifest.json"), encoding="utf-8") as File:
      Manifest = json.load(File)
    self.assertEqual(Manifest["status"], "completed")
    with open(os.path.join(Dir, "log.jsonl"), encoding="utf-8") as File:
      Entries = [json.loads(Line) for Line in File]
    for Key, Value in (
      ("run_kind", "demo_api"), ("base_run", "base_run"), ("base_harness_commit", "b" * 40), ("harness_commit", "d" * 40),
      ("condition", "제안"), ("mode", "split_by_layer"), ("k", 3), ("gen_seed", 7),
    ):
      self.assertEqual(Entries[0][Key], Value)
    self.assertEqual(Entries[0]["trial_id"], Manifest["trial_id"])
    self.assertEqual(Entries[0]["base_trial_id"], App.base_trial_id)
    self.assertEqual(len(Entries[0]["raw_sha256"]), 64)
    with open(os.path.join(Dir, "new_notes.jsonl"), encoding="utf-8") as File:
      self.assertEqual(len([Line for Line in File if Line.strip()]), len(Response["notes"]))


class SettingsTest(DemoBase):
  def test_manifest_settings_reach_run_propose_doc(self) -> None:
    App = self.app()
    Calls = []
    Real = D.run_propose_doc

    def Spy(*Args, **Kwargs):
      Calls.append(Args)
      return Real(*Args, **Kwargs)

    with mock.patch.object(D, "run_propose_doc", Spy):
      App.run({"doc_id": _DOCS[2][0], "mode": "all_layers"})
    (Args,) = Calls
    Doc, Mode, K = Args[0], Args[1], Args[2]
    DecomposeConfig, PlaceConfig = Args[8], Args[9]
    self.assertEqual((Doc.doc_id, Mode, K), (_DOCS[2][0], "all_layers", 3))
    self.assertEqual(Args[7], "합성모델")
    self.assertEqual((DecomposeConfig.seed, DecomposeConfig.max_tokens), (7, 100))
    self.assertEqual((PlaceConfig.seed, PlaceConfig.max_tokens), (7, 50))
    self.assertEqual((DecomposeConfig.temperature, DecomposeConfig.enable_thinking), (D.TEMPERATURE, D.ENABLE_THINKING))
    self.assertEqual(Args[13], 9)

  def test_no_cli_option_for_model_or_search_settings(self) -> None:
    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
      D.parse_args(["--run-dir", "r", "--host", "h", "--port", "1", "--k", "3"])


class MaskingTest(DemoBase):
  def test_labels_are_sorted_owner_order(self) -> None:
    self.assertEqual(owner_labels({"샘플나", "샘플가"}), {"샘플가": "주인A", "샘플나": "주인B"})

  def test_response_and_screen_have_no_owner_names(self) -> None:
    App = self.app()
    Seen = []
    for DocId, _, _ in _DOCS:
      for Mode in ("all_layers", "split_by_layer"):
        Seen.append(App.run({"doc_id": DocId, "mode": Mode})[1])
    Text = json.dumps(Seen, ensure_ascii=False) + "\n".join(self.Lines)
    for Name in _OWNERS:
      self.assertNotIn(Name, Text)
    Labels = {Note["group_label"] for Response in Seen for Note in Response["notes"]}
    self.assertTrue({"주인A", "주인B"} <= Labels)
    self.assertTrue(Labels <= {"주인A", "주인B", "1조", None})

  def test_owner_name_in_model_title_is_masked(self) -> None:
    def Chat(messages, model_id, config, response_schema, *, timeout_seconds):
      Props = response_schema["properties"]
      if "assign" in Props:
        return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["샘플가 의 노트"]})
      return fake_chat(messages, model_id, config, response_schema, timeout_seconds=timeout_seconds)

    Status, Response = self.app(Chat=Chat).run({"doc_id": _DOCS[0][0], "mode": "all_layers"})
    self.assertEqual(Status, 200)
    self.assertNotIn("샘플가", json.dumps(Response, ensure_ascii=False))
    self.assertIn("주인A 의 노트", Response["summary_text"])

  def test_summary_text_has_no_body(self) -> None:
    Response = self.app().run({"doc_id": _DOCS[2][0], "mode": "all_layers"})[1]
    self.assertIn("합성 제목", Response["summary_text"])
    self.assertNotIn("합성 글", Response["summary_text"])


class ErrorStatusTest(DemoBase):
  def test_404_400_for_bad_requests(self) -> None:
    App = self.app()
    self.assertEqual(App.run({"doc_id": "없는문서", "mode": "all_layers"})[0], 404)
    self.assertEqual(App.run({"doc_id": _DOCS[0][0], "mode": "없는모드"})[0], 400)
    self.assertEqual(App.run({"doc_id": _DOCS[0][0]})[0], 400)
    self.assertEqual(App.run([])[0], 400)
    self.assertEqual(len(os.listdir(self.DemoWork)), 0)

  def test_409_when_another_request_is_running(self) -> None:
    App = self.app()
    Entered = threading.Event()
    Release = threading.Event()

    def SlowChat(*Args, **Kwargs):
      Entered.set()
      Release.wait(5)
      return fake_chat(*Args, **Kwargs)

    App.chat_fn = SlowChat
    Out = []
    Thread = threading.Thread(target=lambda: Out.append(App.run({"doc_id": _DOCS[2][0], "mode": "all_layers"})))
    Thread.start()
    self.assertTrue(Entered.wait(5))
    Status, Body = App.run({"doc_id": _DOCS[3][0], "mode": "all_layers"})
    Release.set()
    Thread.join(5)
    self.assertEqual(Status, 409)
    self.assertFalse(Body["ok"])
    self.assertEqual(Out[0][0], 200)
    # 끝난 뒤에는 다시 받는다
    self.assertEqual(App.run({"doc_id": _DOCS[3][0], "mode": "all_layers"})[0], 200)

  def test_rule_violation_is_500_and_manifest_aborted(self) -> None:
    App = self.app(Chat=fake_chat_above_source)
    Status, Body = App.run({"doc_id": _DOCS[2][0], "mode": "split_by_layer"})
    self.assertEqual(Status, 500)
    self.assertFalse(Body["ok"])
    self.assertEqual(Body["error_type"], "ValueError")
    Root = os.path.join(self.DemoWork, "demo_api")
    (Name,) = os.listdir(Root)
    with open(os.path.join(Root, Name, "request_manifest.json"), encoding="utf-8") as File:
      Manifest = json.load(File)
    self.assertEqual(Manifest["status"], "aborted")
    self.assertEqual(Manifest["error"]["type"], "ValueError")
    # 실패한 요청이 기본 상태를 바꾸지 않았다
    self.assertEqual(App.health()["base_notes"], {Mode: len(Cell["notes"]) for Mode, Cell in App.cells.items()})
    self.assertEqual(App.run({"doc_id": _DOCS[2][0], "mode": "all_layers"})[0], 200)

  def test_other_exception_is_500_and_aborted_too(self) -> None:
    def Boom(*Args, **Kwargs):
      raise RuntimeError("합성 실패")

    App = self.app(Chat=Boom)
    Status, Body = App.run({"doc_id": _DOCS[2][0], "mode": "all_layers"})
    self.assertEqual((Status, Body["error_type"]), (500, "RuntimeError"))
    Root = os.path.join(self.DemoWork, "demo_api")
    (Name,) = os.listdir(Root)
    with open(os.path.join(Root, Name, "request_manifest.json"), encoding="utf-8") as File:
      self.assertEqual(json.load(File)["status"], "aborted")


class HttpTest(DemoBase):
  def test_health_docs_run_over_real_http(self) -> None:
    App = self.app()
    Server = make_server(App, "127.0.0.1", 0)
    Thread = threading.Thread(target=Server.serve_forever, daemon=True)
    Thread.start()
    self.addCleanup(Thread.join, 5)
    self.addCleanup(Server.server_close)
    self.addCleanup(Server.shutdown)
    Base = f"http://127.0.0.1:{Server.server_address[1]}"

    def Call(Path, Body=None):
      Request = urllib.request.Request(
        Base + Path, data=None if Body is None else json.dumps(Body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="GET" if Body is None else "POST",
      )
      try:
        with urllib.request.urlopen(Request, timeout=10) as Response:
          return Response.status, json.loads(Response.read().decode("utf-8"))
      except urllib.error.HTTPError as Error:
        with Error:
          return Error.code, json.loads(Error.read().decode("utf-8"))

    Status, Health = Call("/health")
    self.assertEqual((Status, Health["status"], Health["base_run"]), (200, "ok", "base_run"))
    Status, Docs = Call("/docs")
    self.assertEqual((Status, len(Docs)), (200, len(_DOCS)))
    Status, Run = Call("/run", {"doc_id": _DOCS[2][0], "mode": "all_layers"})
    self.assertEqual(Status, 200)
    self.assertTrue(Run["ok"])
    self.assertIn("summary_text", Run)
    self.assertEqual(Call("/run", {"doc_id": "없는문서", "mode": "all_layers"})[0], 404)
    self.assertEqual(Call("/nope")[0], 404)


class Gate:
  # 생성 함수를 Event 로 막아 두는 합성 chat_fn - 서버를 부르지 않는다
  def __init__(self) -> None:
    self.entered = threading.Event()
    self.release = threading.Event()

  def __call__(self, *Args, **Kwargs):
    self.entered.set()
    if not self.release.wait(10):
      raise RuntimeError("합성 게이트가 풀리지 않았다")
    return fake_chat(*Args, **Kwargs)


class JobsBase(DemoBase):
  def start(self, Chat=fake_chat) -> DemoApp:
    App = self.app(Chat=Chat)
    # 어떤 테스트든 끝날 때 작업 스레드를 join 해 스레드가 남지 않게 한다
    self.addCleanup(self.join_jobs, App)
    return App

  def join_jobs(self, App: DemoApp) -> None:
    for Job in list(App.jobs.values()):
      Job["thread"].join(10)
      self.assertFalse(Job["thread"].is_alive())

  def manifest_statuses(self) -> list[str]:
    Root = os.path.join(self.DemoWork, "demo_api")
    Result = []
    for Name in sorted(os.listdir(Root)):
      with open(os.path.join(Root, Name, "request_manifest.json"), encoding="utf-8") as File:
        Result.append(json.load(File)["status"])
    return Result

  def finish(self, App: DemoApp, Body: dict) -> dict:
    Status, Submitted = App.submit(Body)
    self.assertEqual(Status, 202)
    return App.job_status(Submitted["job_id"], 10)[1]


class JobsFlowTest(JobsBase):
  def test_submit_poll_conflict_complete_and_resubmit(self) -> None:
    Gate_ = Gate()
    App = self.start(Chat=Gate_)
    # 정리 순서는 나중에 등록한 것부터라 게이트를 먼저 풀고 join 한다
    self.addCleanup(Gate_.release.set)
    Status, Submitted = App.submit({"doc_id": _DOCS[2][0], "mode": "all_layers"})
    self.assertEqual(Status, 202)
    self.assertEqual(sorted(Submitted), ["job_id", "ok", "status"])
    self.assertEqual((Submitted["ok"], Submitted["status"]), (True, "running"))
    JobId = Submitted["job_id"]
    self.assertRegex(JobId, r"^[0-9a-f]{32}$")
    self.assertTrue(Gate_.entered.wait(5))
    Status, Running = App.job_status(JobId, 0)
    self.assertEqual(Status, 200)
    self.assertEqual(sorted(Running), ["doc_id", "elapsed_s", "job_id", "mode", "status"])
    self.assertEqual(Running["status"], "running")
    Status, Busy = App.submit({"doc_id": _DOCS[3][0], "mode": "all_layers"})
    self.assertEqual(Status, 409)
    self.assertEqual(Busy["running_job_id"], JobId)
    self.assertEqual(App.job_status(Busy["running_job_id"], 0)[0], 200)
    self.assertEqual(App.run({"doc_id": _DOCS[3][0], "mode": "all_layers"})[0], 409)
    Gate_.release.set()
    Status, Done = App.job_status(JobId, 10)
    self.assertEqual(Status, 200)
    self.assertEqual(sorted(Done), ["doc_id", "http_status", "job_id", "mode", "result", "status"])
    self.assertEqual((Done["status"], Done["http_status"]), ("completed", 200))
    Direct = App.run({"doc_id": _DOCS[2][0], "mode": "all_layers"})[1]
    self.assertEqual(sorted(Done["result"]), sorted(Direct))
    self.assertEqual(sorted(Done["result"]["notes"][0]), sorted(Direct["notes"][0]))
    self.assertTrue(Done["result"]["ok"])
    Again = self.finish(App, {"doc_id": _DOCS[3][0], "mode": "all_layers"})
    self.assertEqual(Again["status"], "completed")

  def test_exception_makes_job_failed_with_500_and_aborted_manifest(self) -> None:
    def Boom(*Args, **Kwargs):
      raise RuntimeError("합성 실패")

    App = self.start(Chat=Boom)
    Failed = self.finish(App, {"doc_id": _DOCS[2][0], "mode": "all_layers"})
    self.assertEqual((Failed["status"], Failed["http_status"]), ("failed", 500))
    self.assertEqual(Failed["result"]["error_type"], "RuntimeError")
    self.assertEqual(self.manifest_statuses(), ["aborted"])
    App.chat_fn = fake_chat
    Next = self.finish(App, {"doc_id": _DOCS[3][0], "mode": "all_layers"})
    self.assertEqual(Next["status"], "completed")

  def test_keyboard_interrupt_makes_job_failed_and_releases_lock(self) -> None:
    def Interrupt(*Args, **Kwargs):
      raise KeyboardInterrupt()

    Seen = []
    # 작업 스레드에서 다시 올라온 종료 신호가 stderr 로 새지 않게 훅으로 받는다
    with mock.patch.object(threading, "excepthook", lambda Args: Seen.append(Args.exc_type)):
      App = self.start(Chat=Interrupt)
      Failed = self.finish(App, {"doc_id": _DOCS[2][0], "mode": "all_layers"})
      for Job in list(App.jobs.values()):
        Job["thread"].join(10)
    self.assertEqual(Failed["status"], "failed")
    self.assertEqual(Failed["result"]["error_type"], "KeyboardInterrupt")
    self.assertEqual(Seen, [KeyboardInterrupt])
    self.assertEqual(self.manifest_statuses(), ["aborted"])
    self.assertIsNone(App.current_job_id)
    App.chat_fn = fake_chat
    Next = self.finish(App, {"doc_id": _DOCS[3][0], "mode": "all_layers"})
    self.assertEqual(Next["status"], "completed")


class JobsValidationTest(JobsBase):
  def test_submit_validation_errors_match_run(self) -> None:
    App = self.start()
    for Body in (
      {"doc_id": "없는문서", "mode": "all_layers"}, {"doc_id": _DOCS[0][0], "mode": "없는모드"}, {"doc_id": _DOCS[0][0]}, [],
    ):
      self.assertEqual(App.submit(Body), App.run(Body))
    self.assertEqual(App.jobs, {})
    self.assertFalse(os.path.exists(os.path.join(self.DemoWork, "demo_api")))

  def test_unknown_job_id_is_404_and_bad_wait_raises_value_error(self) -> None:
    App = self.start()
    self.assertEqual(App.job_status("0" * 32, 0)[0], 404)
    for Wait in (-1, 61, "abc", True):
      with self.assertRaises(ValueError):
        App.job_status("0" * 32, Wait)

  def test_status_response_has_no_owner_names(self) -> None:
    def Chat(messages, model_id, config, response_schema, *, timeout_seconds):
      Props = response_schema["properties"]
      if "assign" in Props:
        return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["샘플가 의 노트"]})
      return fake_chat(messages, model_id, config, response_schema, timeout_seconds=timeout_seconds)

    App = self.start(Chat=Chat)
    Done = self.finish(App, {"doc_id": _DOCS[0][0], "mode": "all_layers"})
    self.assertEqual(Done["status"], "completed")
    Text = json.dumps(Done, ensure_ascii=False)
    for Name in _OWNERS:
      self.assertNotIn(Name, Text)
    self.assertIn("주인A", Text)


class JobsHttpTest(JobsBase):
  def serve(self, App: DemoApp) -> str:
    Server = make_server(App, "127.0.0.1", 0)
    Thread = threading.Thread(target=Server.serve_forever, daemon=True)
    Thread.start()
    self.addCleanup(Thread.join, 5)
    self.addCleanup(Server.server_close)
    self.addCleanup(Server.shutdown)
    return f"http://127.0.0.1:{Server.server_address[1]}"

  def call(self, Base: str, Path: str, Body=None):
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

  def test_post_jobs_then_get_until_completed(self) -> None:
    App = self.start()
    Base = self.serve(App)
    Status, Submitted = self.call(Base, "/jobs", {"doc_id": _DOCS[2][0], "mode": "all_layers"})
    self.assertEqual((Status, Submitted["status"]), (202, "running"))
    Status, Done = self.call(Base, f"/jobs/{Submitted['job_id']}?wait=10")
    self.assertEqual((Status, Done["status"], Done["http_status"]), (200, "completed", 200))
    self.assertTrue(Done["result"]["ok"])
    self.assertEqual(self.call(Base, "/jobs", {"doc_id": "없는문서", "mode": "all_layers"})[0], 404)

  def test_wait_query_and_path_rules(self) -> None:
    App = self.start()
    Base = self.serve(App)
    Status, Submitted = self.call(Base, "/jobs", {"doc_id": _DOCS[2][0], "mode": "all_layers"})
    Path = f"/jobs/{Submitted['job_id']}"
    for Query in ("?wait=-1", "?wait=61", "?wait=abc", "?wait=1&wait=2", "?wait=", "?wait=1.5"):
      self.assertEqual(self.call(Base, Path + Query)[0], 400, Query)
    self.assertEqual(self.call(Base, Path + "?wait=0")[0], 200)
    self.assertEqual(self.call(Base, Path)[0], 200)
    self.assertEqual(self.call(Base, f"/jobs/{'0' * 32}?wait=0")[0], 404)
    for Bad in ("/jobs/", "/jobs", f"/jobs/{Submitted['job_id'].upper()}", f"/jobs/{Submitted['job_id']}/", "/jobs/abc"):
      self.assertEqual(self.call(Base, Bad)[0], 404, Bad)
    self.assertEqual(self.call(Base, "/health")[0], 200)
    self.call(Base, Path + "?wait=10")


class CliTest(DemoBase):
  def test_help_exits_zero(self) -> None:
    with redirect_stdout(io.StringIO()):
      with self.assertRaises(SystemExit) as Ctx:
        D.parse_args(["--help"])
    self.assertEqual(Ctx.exception.code, 0)


if __name__ == "__main__":
  unittest.main()
