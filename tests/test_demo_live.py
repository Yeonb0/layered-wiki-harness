import contextlib
import email.message
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest import mock

import serve.demo_api as D
from agent.layer_block import MARK
from agent.llm_client import ChatResult
from runner.v2_sequential import run_v2
from serve.demo_api import DemoApp, make_dify_fn, make_server

# 픽스처일 뿐이며 규칙과 무관하다 - 이름 · 키는 전부 합성이다 ( 실제 네트워크는 쓰지 않는다 )
_KEY = "test-key-픽스처"
_OWNERS = ["샘플가", "샘플나"]
_CRITERIA = f"## 가 {MARK}\n합성 본문\n## 나\n".encode("utf-8")
_CRITERIA_SHA = hashlib.sha256(_CRITERIA).hexdigest()
_DOCS = [
  ("합성문서번호0000", "개인", "샘플가"),
  ("합성문서번호0001", "개인", "샘플나"),
  ("합성문서번호0002", "팀", "1조"),
  ("합성문서번호0003", "팀", "1조"),
]
DOC_A, DOC_B = _DOCS[2][0], _DOCS[3][0]


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


def started(RunId="run-픽스처-0001"):
  return {"event": "workflow_started", "data": {"workflow_run_id": RunId}}


def finished(Status="succeeded"):
  return {"event": "workflow_finished", "data": {"status": Status, "outputs": {"결과": "합성 출력"}}}


class LiveBase(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.Tmp = tempfile.TemporaryDirectory()
    Data = os.path.join(cls.Tmp.name, "data")
    os.makedirs(Data)
    with open(os.path.join(Data, "segments.jsonl"), "w", encoding="utf-8") as File:
      for Id, Layer, Group in _DOCS:
        for Seq in (1, 2):
          File.write(json.dumps({
            "segment_id": f"{Id}-s{Seq}", "doc_id": Id, "seq": Seq, "layer": Layer, "group": Group, "text": f"{Id} 합성 글 {Seq}",
          }, ensure_ascii=False) + "\n")
    with open(os.path.join(Data, "docs.jsonl"), "w", encoding="utf-8") as File:
      for Index, (Id, Layer, Group) in enumerate(_DOCS):
        File.write(json.dumps(
          {"doc_id": Id, "title": f"{Id} 제목", "layer": Layer, "group": Group, "raw_sha256": f"{Index:064d}"}, ensure_ascii=False
        ) + "\n")
    with open(os.path.join(Data, "ids.txt"), "w", encoding="utf-8") as File:
      File.write("".join(f"{Doc[0]}\n" for Doc in _DOCS))
    with open(os.path.join(Data, "selection.json"), "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"ids": []}}, File)
    Layers = os.path.join(Data, "source_layers.json")
    with open(Layers, "w", encoding="utf-8") as File:
      json.dump({"team_1jo_personal_owners": _OWNERS}, File, ensure_ascii=False)
    with open(os.path.join(Data, "criteria.md"), "wb") as File:
      File.write(_CRITERIA)
    Work = os.path.join(cls.Tmp.name, "work")
    os.makedirs(Work)
    cls.RunDir = os.path.join(Work, "base_run")
    p = lambda Name: os.path.join(Data, Name)
    run_v2(
      segments_path=p("segments.jsonl"), docs_path=p("docs.jsonl"), doc_ids_path=p("ids.txt"), split_doc_ids_path=p("ids.txt"),
      selection_path=p("selection.json"), source_layers_path=Layers, criteria_path=p("criteria.md"),
      criteria_sha256=_CRITERIA_SHA, conditions=["제안"], modes=["all_layers", "split_by_layer"], k=3, gen_seed=7, order_seed=11,
      decompose_max_tokens=100, place_max_tokens=50, b1_max_tokens=None, model_id="합성모델", timeout_seconds=9,
      snapshot=1, run_kind="synthetic", out_dir=cls.RunDir, chat_fn=fake_chat, embed_backend=_embed,
      commit_fn=lambda: "b" * 40, work_root=Work, print_fn=lambda Line: None,
    )

  @classmethod
  def tearDownClass(cls) -> None:
    cls.Tmp.cleanup()

  def setUp(self) -> None:
    self.DemoWork = tempfile.TemporaryDirectory()
    self.addCleanup(self.DemoWork.cleanup)
    self.Lines = []

  def app(self, dify_fn=None) -> DemoApp:
    App = DemoApp(
      self.RunDir, chat_fn=fake_chat, embed_backend=_embed, commit_fn=lambda: "d" * 40, work_root=self.DemoWork.name,
      print_fn=self.Lines.append, dify_fn=dify_fn,
    )
    # 어떤 테스트든 끝날 때 작업 · 라이브 스레드를 join 해 스레드가 남지 않게 한다
    def join():
      for Job in list(App.jobs.values()):
        Job["thread"].join(10)
      if App.live is not None:
        App.live["thread"].join(10)

    self.addCleanup(join)
    return App

  def fake_dify(self, Holder, Behaviors, Calls, Gate=None, GateStarted=None):
    # 가짜 Dify : 이벤트를 내고, 정상이면 App.submit 으로 작업을 만들어 끝날 때까지 기다린 뒤 종료 이벤트를 낸다
    def fake(inputs, user):
      Calls.append((dict(inputs), user))
      Behavior = Behaviors.pop(0) if isinstance(Behaviors, list) else Behaviors
      yield started()
      if GateStarted is not None:
        GateStarted.set()
      if Gate is not None:
        Gate.wait(10)
      if Behavior == "raise":
        raise RuntimeError("합성 Dify 실패")
      if Behavior == "finished_failed":
        yield finished("failed")
        return
      if Behavior == "no_finish":
        return
      if Behavior == "ok":
        Status, Submitted = Holder["app"].submit(inputs)
        assert Status == 202, Status
        Holder["app"].job_status(Submitted["job_id"], 10)
      yield finished("succeeded")

    return fake

  def live_app(self, Behaviors="ok", Gate=None, GateStarted=None):
    Holder, Calls = {}, []
    App = self.app(self.fake_dify(Holder, Behaviors, Calls, Gate, GateStarted))
    Holder["app"] = App
    return App, Calls

  def wait_done(self, App, Timeout=20):
    End = time.monotonic() + Timeout
    while time.monotonic() < End:
      Record = App.live_status()[1]
      if Record["status"] != "running":
        return Record
      time.sleep(0.02)
    self.fail("라이브가 끝나지 않았다")


class LiveStartTest(LiveBase):
  def test_without_dify_fn_is_503(self) -> None:
    Status, Body = self.app().live_start({"doc_id": DOC_A, "mode": "all_layers"})
    self.assertEqual((Status, Body["error_type"]), (503, "DifyNotConfigured"))
    self.assertEqual(self.app().live_status(), (200, {"status": "idle"}))

  def test_bad_body_400_and_unknown_doc_404_do_not_call_dify(self) -> None:
    App, Calls = self.live_app()
    self.assertEqual(App.live_start([])[0], 400)
    self.assertEqual(App.live_start({"doc_id": DOC_A})[0], 400)
    self.assertEqual(App.live_start({"doc_id": DOC_A, "mode": "없는모드"})[0], 400)
    self.assertEqual(App.live_start({"doc_id": "없는문서", "mode": "all_layers"})[0], 404)
    self.assertEqual(Calls, [])
    self.assertEqual(App.live_status()[1], {"status": "idle"})

  def test_normal_run_completes_and_job_view_works(self) -> None:
    App, Calls = self.live_app()
    Status, Body = App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    self.assertEqual(Status, 202)
    self.assertRegex(Body["live_id"], r"^[0-9a-f]{32}$")
    Record = self.wait_done(App)
    self.assertEqual(Record["status"], "completed")
    self.assertEqual(Record["live_id"], Body["live_id"])
    self.assertEqual(Record["workflow_run_id"], "run-픽스처-0001")
    self.assertEqual(Record["dify_status"], "succeeded")
    self.assertEqual(Record["dify_outputs"], {"결과": "합성 출력"})
    self.assertRegex(Record["job_id"], r"^[0-9a-f]{32}$")
    self.assertIsNone(Record["error"])
    self.assertIsNotNone(Record["finished_at_utc"])
    self.assertEqual(sorted(Record), sorted([
      "live_id", "doc_id", "mode", "status", "started_at_utc", "finished_at_utc", "elapsed_seconds", "workflow_run_id",
      "dify_status", "dify_outputs", "job_id", "error",
    ]))
    self.assertEqual(Calls, [({"doc_id": DOC_A, "mode": "all_layers"}, "layered-wiki-demo-ui")])
    self.assertEqual(App.view("all_layers", "전사", Record["job_id"])[0], 200)

  def test_second_start_while_running_is_409(self) -> None:
    Gate, GateStarted = threading.Event(), threading.Event()
    App, _ = self.live_app(Gate=Gate, GateStarted=GateStarted)
    self.addCleanup(Gate.set)
    self.assertEqual(App.live_start({"doc_id": DOC_A, "mode": "all_layers"})[0], 202)
    self.assertTrue(GateStarted.wait(5))
    self.assertEqual(App.live_status()[1]["status"], "running")
    Status, Body = App.live_start({"doc_id": DOC_B, "mode": "all_layers"})
    self.assertEqual((Status, Body["error_type"]), (409, "Busy"))
    Gate.set()
    self.assertEqual(self.wait_done(App)["status"], "completed")

  def test_busy_job_lock_makes_live_409(self) -> None:
    Gate = threading.Event()

    def slow_chat(*Args, **Kwargs):
      Gate.wait(10)
      return fake_chat(*Args, **Kwargs)

    App, _ = self.live_app()
    App.chat_fn = slow_chat
    self.addCleanup(Gate.set)
    Status, Submitted = App.submit({"doc_id": DOC_B, "mode": "all_layers"})
    self.assertEqual(Status, 202)
    self.assertEqual(App.live_start({"doc_id": DOC_A, "mode": "all_layers"})[0], 409)
    Gate.set()
    App.job_status(Submitted["job_id"], 10)


class LiveFailureTest(LiveBase):
  def test_workflow_finished_failed_is_failed(self) -> None:
    App, _ = self.live_app("finished_failed")
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    Record = self.wait_done(App)
    self.assertEqual((Record["status"], Record["dify_status"]), ("failed", "failed"))
    self.assertIsNone(Record["job_id"])
    self.assertEqual(Record["error"]["error_type"], "DifyWorkflowFailed")

  def test_succeeded_without_job_is_no_job_submitted(self) -> None:
    App, _ = self.live_app("no_job")
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    Record = self.wait_done(App)
    self.assertEqual(Record["status"], "failed")
    self.assertEqual(Record["error"]["error_type"], "NoJobSubmitted")

  def test_stream_without_finish_event_is_failed(self) -> None:
    App, _ = self.live_app("no_finish")
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    Record = self.wait_done(App)
    self.assertEqual((Record["status"], Record["error"]["error_type"]), ("failed", "NoFinishEvent"))

  def test_exception_is_failed_never_running_and_next_start_is_202(self) -> None:
    App, _ = self.live_app(["raise", "ok"])
    self.assertEqual(App.live_start({"doc_id": DOC_A, "mode": "all_layers"})[0], 202)
    Record = self.wait_done(App)
    self.assertEqual((Record["status"], Record["error"]["error_type"]), ("failed", "RuntimeError"))
    self.assertNotEqual(App.live_status()[1]["status"], "running")
    self.assertIsNotNone(Record["elapsed_seconds"])
    self.assertEqual(App.live_start({"doc_id": DOC_A, "mode": "all_layers"})[0], 202)
    self.assertEqual(self.wait_done(App)["status"], "completed")


class LiveJobAttachTest(LiveBase):
  def test_job_for_a_different_doc_does_not_attach(self) -> None:
    Gate, GateStarted = threading.Event(), threading.Event()
    App, _ = self.live_app(Gate=Gate, GateStarted=GateStarted)
    self.addCleanup(Gate.set)
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    self.assertTrue(GateStarted.wait(5))
    Status, Other = App.submit({"doc_id": DOC_B, "mode": "all_layers"})
    self.assertEqual(Status, 202)
    App.job_status(Other["job_id"], 10)
    self.assertIsNone(App.live_status()[1]["job_id"])
    # 모드가 다른 작업도 붙지 않는다
    Status, OtherMode = App.submit({"doc_id": DOC_A, "mode": "split_by_layer"})
    self.assertEqual(Status, 202)
    App.job_status(OtherMode["job_id"], 10)
    self.assertIsNone(App.live_status()[1]["job_id"])
    Gate.set()
    Record = self.wait_done(App)
    self.assertEqual(Record["status"], "completed")
    self.assertNotIn(Record["job_id"], (Other["job_id"], OtherMode["job_id"]))
    self.assertEqual((App.jobs[Record["job_id"]]["doc_id"], App.jobs[Record["job_id"]]["mode"]), (DOC_A, "all_layers"))


class FakeResponse:
  def __init__(self, Lines):
    self.Lines = Lines

  def __iter__(self):
    return iter(self.Lines() if callable(self.Lines) else self.Lines)

  def __enter__(self):
    return self

  def __exit__(self, *Args):
    return False


class FakeOpener:
  def __init__(self, Handlers, Respond):
    self.Handlers = Handlers
    self.Respond = Respond
    self.Requests = []
    self.Timeouts = []

  def open(self, request, timeout=None):
    self.Requests.append(request)
    self.Timeouts.append(timeout)
    return self.Respond(request)


def patched_opener(Respond):
  Made = []

  def build(*Handlers):
    Opener = FakeOpener(Handlers, Respond)
    Made.append(Opener)
    return Opener

  return mock.patch.object(D.urllib.request, "build_opener", side_effect=build), Made


def data_line(Event):
  return ("data: " + json.dumps(Event, ensure_ascii=False) + "\n").encode("utf-8")


class MakeDifyFnTest(unittest.TestCase):
  def run_fn(self, Lines, Url="http://dify.test/v1/"):
    Patch, Made = patched_opener(lambda request: FakeResponse(Lines))
    with Patch:
      Fn = make_dify_fn(Url, _KEY)
      Events = list(Fn({"doc_id": "문서", "mode": "all_layers"}, "사용자"))
    return Events, Made[0]

  def test_request_has_bearer_header_body_and_600s_timeout(self) -> None:
    Events, Opener = self.run_fn([data_line(started())])
    self.assertEqual(Events, [started()])
    (Request,) = Opener.Requests
    self.assertEqual(Request.full_url, "http://dify.test/v1/workflows/run")
    self.assertEqual(Request.get_method(), "POST")
    self.assertEqual(Request.get_header("Authorization"), f"Bearer {_KEY}")
    self.assertEqual(Request.get_header("Content-type"), "application/json")
    self.assertEqual(
      json.loads(Request.data.decode("utf-8")),
      {"inputs": {"doc_id": "문서", "mode": "all_layers"}, "response_mode": "streaming", "user": "사용자"},
    )
    self.assertEqual(Opener.Timeouts, [600])

  def test_environment_proxies_are_not_used(self) -> None:
    _, Opener = self.run_fn([])
    Proxies = [H for H in Opener.Handlers if isinstance(H, urllib.request.ProxyHandler)]
    self.assertEqual(len(Proxies), 1)
    self.assertEqual(Proxies[0].proxies, {})

  def test_only_data_lines_are_parsed(self) -> None:
    Lines = [b"\n", b"event: ping\n", b": comment\n", data_line(started()), b"\n", b"ping\n", data_line(finished())]
    Events, _ = self.run_fn(Lines)
    self.assertEqual(Events, [started(), finished()])

  def test_http_error_carries_only_status_code_and_message(self) -> None:
    Headers = email.message.Message()
    Headers["Authorization"] = f"Bearer {_KEY}"
    Body = json.dumps({"code": "unauthorized", "message": "Access token is invalid"}).encode("utf-8")

    def respond(request):
      raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", Headers, io.BytesIO(Body))

    Patch, _ = patched_opener(respond)
    with Patch:
      Fn = make_dify_fn("http://dify.test/v1", _KEY)
      with self.assertRaises(D.DifyError) as Ctx:
        list(Fn({}, "사용자"))
    Message = str(Ctx.exception)
    self.assertIn("401", Message)
    self.assertIn("unauthorized", Message)
    self.assertIn("Access token is invalid", Message)
    self.assertNotIn(_KEY, Message)
    self.assertNotIn("Bearer", Message)


class SecretSpyTest(LiveBase):
  def test_key_never_appears_in_output_or_responses(self) -> None:
    Holder = {}

    def respond(request):
      def lines():
        yield b"event: ping\n"
        yield data_line(started("run-스파이"))
        Status, Submitted = Holder["app"].submit(json.loads(request.data.decode("utf-8"))["inputs"])
        assert Status == 202
        Holder["app"].job_status(Submitted["job_id"], 10)
        yield data_line(finished())

      return FakeResponse(lines)

    Patch, Made = patched_opener(respond)
    with Patch:
      App = self.app(make_dify_fn("http://dify.test/v1", _KEY))
    Holder["app"] = App
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    Record = self.wait_done(App)
    self.assertEqual(Record["status"], "completed")
    self.assertEqual(Made[0].Requests[0].get_header("Authorization"), f"Bearer {_KEY}")
    Texts = [json.dumps(App.live_status()[1], ensure_ascii=False), json.dumps(App.docs and App.doc_list(), ensure_ascii=False)]
    Texts += [json.dumps(App.job_status(Id, 0)[1], ensure_ascii=False) for Id in App.jobs]
    Texts += [json.dumps(App.health(), ensure_ascii=False), json.dumps(App.viewers(), ensure_ascii=False)]
    Texts += self.Lines
    for Text in Texts:
      self.assertNotIn(_KEY, Text)
      self.assertNotIn("Authorization", Text)
      self.assertNotIn("Bearer", Text)
    # 로그에는 live_id · doc_id · mode · 상태 · 시간만 한 줄씩 찍힌다
    LiveLines = [Line for Line in self.Lines if Line.startswith("live ")]
    self.assertEqual(len(LiveLines), 2)
    for Line in LiveLines:
      self.assertRegex(Line, r"^live [0-9a-f]{32} doc=\S+ mode=\S+ status=\w+ elapsed_s=[0-9.]+$")

  def test_dify_http_error_is_failed_without_key(self) -> None:
    Headers = email.message.Message()
    Headers["Authorization"] = f"Bearer {_KEY}"

    def respond(request):
      raise urllib.error.HTTPError(
        request.full_url, 401, "Unauthorized", Headers,
        io.BytesIO(json.dumps({"code": "unauthorized", "message": "Access token is invalid"}).encode("utf-8")),
      )

    Patch, _ = patched_opener(respond)
    with Patch:
      App = self.app(make_dify_fn("http://dify.test/v1", _KEY))
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    Record = self.wait_done(App)
    self.assertEqual((Record["status"], Record["error"]["error_type"]), ("failed", "DifyError"))
    Text = json.dumps(Record, ensure_ascii=False) + "\n".join(self.Lines)
    self.assertIn("401", Text)
    self.assertNotIn(_KEY, Text)

  def test_owner_names_in_workflow_outputs_are_masked(self) -> None:
    def fake(inputs, user):
      yield started()
      yield {"event": "workflow_finished", "data": {"status": "failed", "outputs": {"결과": "샘플가 의 메모"}}}

    App = self.app(fake)
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    Text = json.dumps(self.wait_done(App), ensure_ascii=False)
    self.assertNotIn("샘플가", Text)
    self.assertIn("주인A 의 메모", Text)


class ArgsTest(unittest.TestCase):
  BASE = ["--run-dir", "r", "--host", "h", "--port", "1"]

  def parse(self, *Extra):
    with contextlib.redirect_stderr(io.StringIO()):
      return D.parse_args(self.BASE + list(Extra))

  def test_only_one_of_url_and_key_env_exits(self) -> None:
    with self.assertRaises(SystemExit):
      self.parse("--dify-url", "http://x/v1")
    with self.assertRaises(SystemExit):
      self.parse("--dify-key-env", "ANY_NAME")

  def test_both_or_neither_parse(self) -> None:
    Args = self.parse()
    self.assertEqual((Args.dify_url, Args.dify_key_env), (None, None))
    Args = self.parse("--dify-url", "http://x/v1", "--dify-key-env", "ANY_NAME")
    self.assertEqual((Args.dify_url, Args.dify_key_env), ("http://x/v1", "ANY_NAME"))

  def test_missing_or_empty_key_env_exits_with_name_only(self) -> None:
    Args = self.parse("--dify-url", "http://x/v1", "--dify-key-env", "DEMO_KEY_VAR")
    for Environ in ({}, {"DEMO_KEY_VAR": ""}):
      with self.assertRaises(SystemExit) as Ctx:
        D.dify_fn_from_args(Args, Environ)
      self.assertIn("DEMO_KEY_VAR", str(Ctx.exception))
    self.assertTrue(callable(D.dify_fn_from_args(Args, {"DEMO_KEY_VAR": _KEY})))

  def test_no_dify_args_means_no_dify_fn(self) -> None:
    self.assertIsNone(D.dify_fn_from_args(self.parse(), {}))

  def test_secret_value_is_not_in_the_exit_message(self) -> None:
    Args = self.parse("--dify-url", "http://x/v1", "--dify-key-env", "DEMO_KEY_VAR")
    with self.assertRaises(SystemExit) as Ctx:
      D.dify_fn_from_args(Args, {"OTHER": _KEY})
    self.assertNotIn(_KEY, str(Ctx.exception))


class LiveHttpTest(LiveBase):
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

  def test_post_and_get_live_over_http(self) -> None:
    App, _ = self.live_app()
    Base = self.serve(App)
    self.assertEqual(self.call(Base, "/live"), (200, {"status": "idle"}))
    self.assertEqual(self.call(Base, "/live", [])[0], 400)
    self.assertEqual(self.call(Base, "/live", {"doc_id": "없는문서", "mode": "all_layers"})[0], 404)
    Status, Body = self.call(Base, "/live", {"doc_id": DOC_A, "mode": "all_layers"})
    self.assertEqual(Status, 202)
    Record = self.wait_done(App)
    Status, Got = self.call(Base, "/live")
    self.assertEqual((Status, Got["status"], Got["live_id"]), (200, "completed", Body["live_id"]))
    self.assertEqual(Got["job_id"], Record["job_id"])
    self.assertEqual(self.call(Base, "/view?mode=all_layers&viewer=%EC%A0%84%EC%82%AC&job=" + Record["job_id"])[0], 200)

  def test_post_live_without_dify_is_503_over_http(self) -> None:
    Base = self.serve(self.app())
    Status, Body = self.call(Base, "/live", {"doc_id": DOC_A, "mode": "all_layers"})
    self.assertEqual((Status, Body["error_type"]), (503, "DifyNotConfigured"))


if __name__ == "__main__":
  unittest.main()
