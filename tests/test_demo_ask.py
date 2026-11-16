import hashlib
import json
import os
import threading
import unittest
import urllib.error
import urllib.request

import serve.demo_api as D
from serve.demo_api import DemoApp, DifyError, make_server
from tests.test_demo_view import _MODES, _embed_backend, _vault, make_chat, ViewBase

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 노트 7개와 합성 소속 표 ( 샘플가 = 팀가, 샘플나 = 팀나, 샘플다 = 팀가 · 팀나 ) 를 그대로 쓴다
# 가짜 Dify 가 돌려주는 답 · 인용 id 도 픽스처일 뿐이다


class FakeChat:
  # 가짜 Dify chat 함수 - 받은 인자를 기록하고 정해 둔 답을 돌려준다
  def __init__(self, Answer="합성 답 [문서전사#n0]") -> None:
    self.Answer = Answer
    self.Calls = []

  def __call__(self, inputs, query, user):
    self.Calls.append((inputs, query, user))
    return {"answer": self.Answer, "message_id": "m1", "conversation_id": "c1"}


class AskBase(ViewBase):
  def app_with(self, Chat, RunDir=None) -> DemoApp:
    App = DemoApp(
      RunDir or self.Demo, chat_fn=make_chat(), embed_backend=_embed_backend, commit_fn=lambda: "d" * 40,
      work_root=self.DemoWork.name, print_fn=lambda Line: None, dify_chat_fn=Chat,
    )
    self.addCleanup(lambda: [Job["thread"].join(10) for Job in list(App.jobs.values())])
    return App

  def snapshot(self, *Roots) -> dict:
    Result = {}
    for Root in Roots:
      for Dir, _, Names in os.walk(Root):
        for Name in Names:
          Path = os.path.join(Dir, Name)
          with open(Path, "rb") as File:
            Result[Path] = hashlib.sha256(File.read()).hexdigest()
    return Result


class AskRuleTest(AskBase):
  def test_spy_out_of_view_citations_are_ids_only(self) -> None:
    Probe = self.app_with(FakeChat())
    Owners = [Item for Item in Probe.viewers()["viewers"] if Item["layer"] == "개인" and len(Item["teams"]) == 1]
    self.assertTrue(Owners, "픽스처에 팀 하나에만 속한 개인이 없다")
    for Owner in Owners:
      Hidden = [Row for Row in _vault() if Row["layer"] == "팀" and Row["group"] not in Owner["teams"]]
      self.assertTrue(Hidden, "보기 밖 노트가 픽스처에 없다")
      for Mode in _MODES:
        ViewIds = {Note["note_id"] for Note in Probe.view(Mode, Owner["viewer_id"], None)[1]["notes"]}
        Visible = sorted(ViewIds)[0]
        for Row in Hidden:
          self.assertNotIn(Row["note_id"], ViewIds)
          App = self.app_with(FakeChat(f"답 [{Row['note_id']}] 그리고 [{Visible}]"))
          Status, Body = App.ask(Mode, Owner["viewer_id"], "합성 질문")
          self.assertEqual(Status, 200)
          self.assertEqual([Item["note_id"] for Item in Body["sources"]], [Visible])
          self.assertEqual(Body["out_of_view_ids"], [Row["note_id"]])
          # 보기 밖 노트의 제목 · 본문이 응답 어디에도 없다
          Text = json.dumps(Body, ensure_ascii=False)
          self.assertNotIn(Row["title"], Text)
          self.assertNotIn(Row["body"], Text)

  def test_cited_ids_are_unique_and_in_order_of_appearance(self) -> None:
    App = self.app_with(FakeChat("[문서팀가#n0] 먼저, [문서전사#n0] 다음, 다시 [문서팀가#n0], 없는 [없는노트#n9]"))
    Status, Body = App.ask("all_layers", "전사", "합성 질문")
    self.assertEqual(Status, 200)
    self.assertEqual(Body["cited_ids"], ["문서팀가#n0", "문서전사#n0", "없는노트#n9"])
    self.assertEqual([Item["note_id"] for Item in Body["sources"]], ["문서전사#n0"])
    self.assertEqual(Body["out_of_view_ids"], ["문서팀가#n0", "없는노트#n9"])

  def test_chat_function_receives_viewer_mode_and_query_unchanged(self) -> None:
    Chat = FakeChat()
    App = self.app_with(Chat)
    for Mode in _MODES:
      Chat.Calls.clear()
      Status, Body = App.ask(Mode, "개인:샘플다", "  합성 질문 그대로  ")
      self.assertEqual(Status, 200)
      self.assertEqual(len(Chat.Calls), 1)
      Inputs, Query, User = Chat.Calls[0]
      self.assertEqual(Inputs, {"viewer": "개인:샘플다", "mode": Mode})
      self.assertEqual(Query, "  합성 질문 그대로  ")
      self.assertEqual(User, D.LIVE_USER)
      self.assertEqual(
        set(Body),
        {"mode", "viewer_id", "query", "answer", "cited_ids", "sources", "out_of_view_ids", "message_id", "conversation_id", "elapsed_seconds"},
      )
      self.assertEqual((Body["message_id"], Body["conversation_id"]), ("m1", "c1"))

  def test_bad_mode_viewer_and_query_are_400(self) -> None:
    Chat = FakeChat()
    App = self.app_with(Chat)
    for Mode, Viewer, Query in (
      ("없는모드", "전사", "질문"), ("all_layers", "없는사람", "질문"), ("all_layers", "전사", ""),
      ("all_layers", "전사", "가" * (D.MAX_QUERY_CHARS + 1)),
    ):
      self.assertEqual(App.ask(Mode, Viewer, Query)[0], 400, (Mode, Viewer, len(Query)))
    self.assertEqual(Chat.Calls, [])
    self.assertEqual(App.ask("all_layers", "전사", "가" * D.MAX_QUERY_CHARS)[0], 200)

  def test_not_configured_dify_error_and_busy(self) -> None:
    self.assertEqual(self.app_with(None).ask("all_layers", "전사", "질문")[0], 503)

    def Broken(inputs, query, user):
      raise DifyError("Dify HTTP 500 : code=x message=y")

    Status, Body = self.app_with(Broken).ask("all_layers", "전사", "질문")
    self.assertEqual((Status, Body["error_type"]), (502, "DifyError"))

    def Odd(inputs, query, user):
      raise ValueError("합성 오류")

    self.assertEqual(self.app_with(Odd).ask("all_layers", "전사", "질문")[0], 502)

    Entered, Release = threading.Event(), threading.Event()

    def Slow(inputs, query, user):
      Entered.set()
      if not Release.wait(10):
        raise DifyError("합성 게이트가 풀리지 않았다")
      return {"answer": "답"}

    App = self.app_with(Slow)
    Result = []
    Thread = threading.Thread(target=lambda: Result.append(App.ask("all_layers", "전사", "질문")))
    Thread.start()
    self.assertTrue(Entered.wait(10))
    self.assertEqual(App.ask("all_layers", "전사", "다른 질문")[0], 409)
    Release.set()
    Thread.join(10)
    self.assertEqual(Result[0][0], 200)
    # 끝난 뒤에는 다시 받는다
    Release.set()
    self.assertEqual(App.ask("all_layers", "전사", "질문")[0], 200)

  def test_ask_does_not_change_any_file(self) -> None:
    for RunDir in (self.Demo, self.Real):
      App = self.app_with(FakeChat(), RunDir)
      Before = self.snapshot(RunDir, self.DemoWork.name)
      for Mode in _MODES:
        self.assertEqual(App.ask(Mode, "전사", "합성 질문")[0], 200)
      self.assertEqual(self.snapshot(RunDir, self.DemoWork.name), Before)


class AskHttpTest(AskBase):
  def serve(self, App) -> str:
    Server = make_server(App, "127.0.0.1", 0)
    Thread = threading.Thread(target=Server.serve_forever, daemon=True)
    Thread.start()
    self.addCleanup(Thread.join, 5)
    self.addCleanup(Server.server_close)
    self.addCleanup(Server.shutdown)
    return f"http://127.0.0.1:{Server.server_address[1]}"

  def post(self, Base, Body):
    Data = json.dumps(Body, ensure_ascii=False).encode("utf-8")
    Request = urllib.request.Request(Base + "/ask", data=Data, method="POST", headers={"Content-Type": "application/json"})
    try:
      with urllib.request.urlopen(Request, timeout=15) as Response:
        return Response.status, json.loads(Response.read().decode("utf-8"))
    except urllib.error.HTTPError as Error:
      with Error:
        return Error.code, json.loads(Error.read().decode("utf-8"))

  def test_ask_over_http_and_bad_bodies(self) -> None:
    Chat = FakeChat()
    Base = self.serve(self.app_with(Chat))
    Good = {"mode": "all_layers", "viewer": "전사", "query": "합성 질문"}
    Status, Body = self.post(Base, Good)
    self.assertEqual(Status, 200)
    self.assertEqual(Body["cited_ids"], ["문서전사#n0"])
    Cases = []
    for Key in Good:
      Cases.append({Name: Value for Name, Value in Good.items() if Name != Key})
      Cases.append({**Good, Key: ""})
      Cases.append({**Good, Key: 3})
      Cases.append({**Good, Key: None})
    Cases += [[], "문자열", None, {**Good, "viewer": "없는사람"}, {**Good, "mode": "없는모드"}]
    Cases.append({**Good, "query": "가" * (D.MAX_QUERY_CHARS + 1)})
    for Case in Cases:
      self.assertEqual(self.post(Base, Case)[0], 400, Case)
    self.assertEqual(len(Chat.Calls), 1)

  def test_ask_without_chat_function_is_503_over_http(self) -> None:
    Base = self.serve(self.app_with(None))
    self.assertEqual(self.post(Base, {"mode": "all_layers", "viewer": "전사", "query": "질문"})[0], 503)


class AskArgsTest(unittest.TestCase):
  def test_qa_key_env_needs_dify_url(self) -> None:
    Base = ["--run-dir", "r", "--host", "h", "--port", "1"]
    with self.assertRaises(SystemExit):
      D.parse_args(Base + ["--dify-qa-key-env", "X"])
    Args = D.parse_args(Base + ["--dify-url", "http://x", "--dify-key-env", "K", "--dify-qa-key-env", "X"])
    self.assertEqual(Args.dify_qa_key_env, "X")
    self.assertIsNone(D.parse_args(Base).dify_qa_key_env)

  def test_chat_fn_from_args(self) -> None:
    Base = ["--run-dir", "r", "--host", "h", "--port", "1", "--dify-url", "http://x", "--dify-key-env", "K"]
    self.assertIsNone(D.dify_chat_fn_from_args(D.parse_args(Base), environ={}))
    Args = D.parse_args(Base + ["--dify-qa-key-env", "X"])
    with self.assertRaises(SystemExit):
      D.dify_chat_fn_from_args(Args, environ={"X": ""})
    self.assertTrue(callable(D.dify_chat_fn_from_args(Args, environ={"X": "합성키"})))


if __name__ == "__main__":
  unittest.main()
