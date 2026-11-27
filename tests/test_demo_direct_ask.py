import unittest

from agent.llm_client import ChatResult
from serve.direct_front import QA_SYSTEM_PROMPT, format_answer, make_direct_chat_fn
from tests.test_demo_ask import AskBase

# 픽스처일 뿐이며 규칙과 무관하다 - 노트 id · 답은 합성이다


class LlmSpy:
  # agent.llm_client.chat 과 같은 모양의 가짜 : 받은 인자를 기록하고 정해 둔 글을 돌려준다
  def __init__(self, Text="합성 답", Error=None) -> None:
    self.Text = Text
    self.Error = Error
    self.Calls = []

  def __call__(self, messages, model_id, config, response_schema, *, timeout_seconds):
    self.Calls.append({"messages": messages, "model_id": model_id, "config": config, "schema": response_schema, "timeout": timeout_seconds})
    if self.Error is not None:
      raise self.Error
    return ChatResult(text=self.Text, finish_reason="stop", prompt_tokens=10, completion_tokens=5, elapsed_seconds=0.1, timings=None, request_body={}, response_body={})


class FormatAnswerTest(unittest.TestCase):
  def test_valid_and_invalid_citations(self) -> None:
    Out = format_answer("A 이다 [n1] B [x9]", ["n1"])
    self.assertEqual(Out["answer"], "A 이다 [n1] B [x9]\n\n근거 노트 : n1\n검색 결과에 없는 인용 (무효) : x9")
    self.assertEqual((Out["valid_count"], Out["invalid_count"]), (1, 1))

  def test_think_block_removed_and_no_citation(self) -> None:
    Out = format_answer("<think>\n속생각\n</think>\n찾을 수 없습니다.", ["n1"])
    self.assertEqual(Out["answer"], "찾을 수 없습니다.\n\n근거 노트 : 없음")
    self.assertEqual((Out["valid_count"], Out["invalid_count"]), (0, 0))

  def test_prompt_matches_chatflow_with_context_slot(self) -> None:
    # demo_dify/layered_qa_chatflow.yml 의 시스템 프롬프트와 글자 그대로 (노트 자리만 {context})
    self.assertTrue(QA_SYSTEM_PROMPT.startswith("너는 가상 게임 스튜디오의 사내 노트만 근거로 답하는 도우미다.\n규칙\n1. "))
    self.assertTrue(QA_SYSTEM_PROMPT.endswith("<노트>\n{context}\n</노트>"))
    self.assertEqual(QA_SYSTEM_PROMPT.count("{context}"), 1)


class DirectAskTest(AskBase):
  def direct(self, Spy):
    App = self.app_with(None)
    App.dify_chat_fn = make_direct_chat_fn(App, Spy, "x/y")
    return App

  def test_ask_returns_sources_in_view_only(self) -> None:
    Probe = self.direct(LlmSpy())
    Results = Probe.search("all_layers", "전사", "합성 질문", 4)[1]["results"]
    self.assertTrue(Results, "픽스처 검색 결과가 비었다")
    Inside = Results[0]["note_id"]
    Spy = LlmSpy(f"답 [{Inside}] 그리고 [없는노트#n9]")
    App = self.direct(Spy)
    Status, Body = App.ask("all_layers", "전사", "합성 질문")
    self.assertEqual(Status, 200)
    self.assertEqual([S["note_id"] for S in Body["sources"]], [Inside])
    self.assertIn("검색 결과에 없는 인용 (무효) : 없는노트#n9", Body["answer"])
    self.assertIsNone(Body["message_id"])
    Call = Spy.Calls[0]
    self.assertEqual(Call["model_id"], "x/y")
    self.assertIsNone(Call["schema"])
    self.assertEqual((Call["config"].temperature, Call["config"].seed, Call["config"].max_tokens, Call["config"].enable_thinking), (0, App.gen_seed, 1024, False))
    self.assertEqual(Call["messages"][1], {"role": "user", "content": "합성 질문"})
    self.assertIn(f"[{Inside}]", Call["messages"][0]["content"])

  def test_chat_exception_is_502_dify_error(self) -> None:
    App = self.direct(LlmSpy(Error=RuntimeError("402 Payment Required")))
    Status, Body = App.ask("all_layers", "전사", "합성 질문")
    self.assertEqual((Status, Body["error_type"]), (502, "DifyError"))

  def test_empty_search_still_calls_chat_with_empty_notes(self) -> None:
    Spy = LlmSpy("주어진 노트에서 찾을 수 없습니다.")
    App = self.direct(Spy)
    Empty = (200, {"results": [], "context": "", "considered": 0})
    App.search = lambda mode, viewer_id, query, k: Empty
    Status, Body = App.ask("all_layers", "전사", "합성 질문")
    self.assertEqual(Status, 200)
    self.assertEqual(len(Spy.Calls), 1)
    self.assertTrue(Spy.Calls[0]["messages"][0]["content"].endswith("<노트>\n\n</노트>"))
    self.assertIn("근거 노트 : 없음", Body["answer"])

  def test_search_uses_k4_and_viewer(self) -> None:
    Seen = []
    App = self.direct(LlmSpy())
    Original = App.search
    def spy(mode, viewer_id, query, k):
      Seen.append((mode, viewer_id, query, k))
      return Original(mode, viewer_id, query, k)
    App.search = spy
    App.ask("split_by_layer", "전사", "합성 질문")
    self.assertEqual(Seen, [("split_by_layer", "전사", "합성 질문", 4)])

  def test_search_failure_becomes_answer_like_chatflow(self) -> None:
    Spy = LlmSpy()
    App = self.direct(Spy)
    App.search = lambda mode, viewer_id, query, k: (500, {"ok": False, "error_type": "X", "message": "합성 실패"})
    Status, Body = App.ask("all_layers", "전사", "합성 질문")
    self.assertEqual(Status, 200)
    self.assertTrue(Body["answer"].startswith("검색 실패 (500) : "))
    self.assertEqual(Spy.Calls, [])


if __name__ == "__main__":
  unittest.main()
