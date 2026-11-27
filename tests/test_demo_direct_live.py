import threading
import unittest
from unittest import mock

import serve.demo_api as D
from serve.direct_front import make_direct_live_fn
from tests.test_demo_live import DOC_A, LiveBase


class DirectLiveTest(LiveBase):
  # 공개 시연 서버 (설계 9.7) : Dify 워크플로가 하던 일 (작업 제출 → 끝날 때까지 대기) 을 서버 안에서 하고 같은 모양의 이벤트를 낸다
  def direct_app(self, wait_seconds=10):
    App = self.app()
    App.dify_fn = make_direct_live_fn(App, wait_seconds)
    return App

  def test_success_completes_with_direct_run_id(self) -> None:
    App = self.direct_app()
    Status, _ = App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    self.assertEqual(Status, 202)
    Record = self.wait_done(App)
    self.assertEqual(Record["status"], "completed")
    self.assertRegex(Record["workflow_run_id"], r"^direct-[0-9a-f]{32}$")
    self.assertRegex(Record["job_id"], r"^[0-9a-f]{32}$")
    self.assertEqual(Record["dify_status"], "succeeded")
    self.assertEqual(Record["dify_outputs"], {"job_id": Record["job_id"], "job_status": "completed"})
    self.assertEqual(App.view("all_layers", "전사", Record["job_id"])[0], 200)

  def test_events_are_started_then_finished(self) -> None:
    App = self.app()
    Fn = make_direct_live_fn(App, 10)
    Events = list(Fn({"doc_id": DOC_A, "mode": "all_layers"}, "layered-wiki-demo-ui"))
    self.assertEqual([E["event"] for E in Events], ["workflow_started", "workflow_finished"])
    self.assertEqual(Events[1]["data"]["status"], "succeeded")
    for Job in App.jobs.values():
      Job["thread"].join(10)

  def test_submit_refused_makes_live_failed(self) -> None:
    # Review Focus 1 : 제출이 거절되면 (409 · 재시작 뒤 잠금 등) running 으로 남지 않고 실패로 끝난다
    App = self.direct_app()
    Refused = (409, {"ok": False, "error_type": "Busy", "message": "다른 요청을 처리 중이다"})
    with mock.patch.object(App, "submit", return_value=Refused):
      self.assertEqual(App.live_start({"doc_id": DOC_A, "mode": "all_layers"})[0], 202)
      Record = self.wait_done(App)
    self.assertEqual(Record["status"], "failed")
    self.assertEqual(Record["error"]["error_type"], "DifyWorkflowFailed")
    self.assertEqual(Record["dify_status"], "failed")
    self.assertEqual(Record["dify_outputs"]["error"], Refused[1])

  def test_failed_job_makes_workflow_failed(self) -> None:
    def broken_chat(*Args, **Kwargs):
      raise RuntimeError("합성 모델 실패")
    App = self.direct_app()
    App.chat_fn = broken_chat
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    Record = self.wait_done(App)
    self.assertEqual(Record["status"], "failed")
    self.assertEqual(Record["dify_outputs"]["job_status"], "failed")

  def test_timeout_makes_workflow_failed_not_running(self) -> None:
    Gate = threading.Event()
    App = self.direct_app(wait_seconds=0.2)
    Original = App._run_locked

    def slow(*Args):
      Gate.wait(10)
      return Original(*Args)
    App._run_locked = slow
    App.live_start({"doc_id": DOC_A, "mode": "all_layers"})
    try:
      Record = self.wait_done(App)
    finally:
      Gate.set()
    self.assertEqual(Record["status"], "failed")
    self.assertEqual(Record["dify_outputs"]["job_status"], "running")


class DirectWiringTest(LiveBase):
  def test_attach_direct_front_sets_live_fn_with_900s(self) -> None:
    App = self.app()
    with mock.patch.object(D, "make_direct_live_fn", wraps=make_direct_live_fn) as Spy:
      D.attach_direct_front(App)
    Spy.assert_called_once_with(App, 900)
    self.assertIsNotNone(App.dify_fn)

  def test_attach_direct_front_sets_chat_fn_with_app_model(self) -> None:
    App = self.app()
    App.model_id = "x/y"
    with mock.patch.object(D, "make_direct_chat_fn") as Spy:
      D.attach_direct_front(App)
    Spy.assert_called_once_with(App, D.chat, "x/y")
    self.assertIs(App.dify_chat_fn, Spy.return_value)

  def test_main_attaches_only_for_direct(self) -> None:
    for Front, Extra, Expected in (("direct", ["--model-id", "x/y", "--daily-job-limit", "3"], 1), ("dify", [], 0)):
      with mock.patch.object(D, "DemoApp") as FakeApp, mock.patch.object(D, "make_server") as FakeServer, \
          mock.patch.object(D, "attach_direct_front") as Attach, mock.patch.object(D, "_print_flush"):
        FakeApp.return_value.show_names = True
        FakeApp.return_value.cells = {}
        FakeApp.return_value.docs = {}
        D.main(["--run-dir", self.RunDir, "--host", "h", "--port", "1", "--front", Front, *Extra])
        self.assertEqual(Attach.call_count, Expected, Front)
        FakeServer.return_value.serve_forever.assert_called_once()


if __name__ == "__main__":
  unittest.main()
