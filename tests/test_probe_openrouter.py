import importlib.util
import os
import unittest
from unittest import mock

from agent.llm_client import ChatResult
from agent.types import SourceDoc, SourceSegment

# deploy/demo-cloudrun 은 하이픈이 있어 패키지로 가져올 수 없다 : 파일 경로로 불러온다
_PATH = os.path.join(os.path.dirname(__file__), "..", "deploy", "demo-cloudrun", "probe_openrouter.py")
_SPEC = importlib.util.spec_from_file_location("probe_openrouter", _PATH)
probe_openrouter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe_openrouter)


def _doc() -> SourceDoc:
  # 픽스처일 뿐이며 규칙과 무관하다
  Segs = [SourceSegment(segment_id="d1:1", seq=1, text="합성 문단 하나"), SourceSegment(segment_id="d1:2", seq=2, text="합성 문단 둘")]
  return SourceDoc(doc_id="d1", title="합성 문서", source_layer="팀", source_group="팀1", segments=Segs)


def _result(Text: str, Finish: str = "stop") -> ChatResult:
  return ChatResult(text=Text, finish_reason=Finish, prompt_tokens=40, completion_tokens=9, elapsed_seconds=1.5, timings=None, request_body={}, response_body={})


class ProbeTest(unittest.TestCase):
  def test_valid_assignment_is_ok(self) -> None:
    Chat = mock.Mock(return_value=_result('{"assign": {"S1": 1, "S2": 1}, "titles": ["합성 제목"]}'))
    Row = probe_openrouter.probe("x/y", _doc(), "층 정의", 777, chat_fn=Chat)
    self.assertEqual(Row, {"model": "x/y", "ok": True, "error": None, "finish_reason": "stop", "prompt_tokens": 40, "completion_tokens": 9, "elapsed_s": 1.5})
    Args, Kwargs = Chat.call_args
    Config = Args[2]
    self.assertEqual((Config.temperature, Config.seed, Config.max_tokens, Config.enable_thinking), (0, 20261127, 777, False))
    self.assertEqual(Args[3]["required"], ["assign", "titles"])
    self.assertIn("층 정의", Args[0][0]["content"])

  def test_truncated_output_is_not_ok(self) -> None:
    Chat = mock.Mock(return_value=_result('{"assign": {"S1"', Finish="length"))
    Row = probe_openrouter.probe("x/y", _doc(), "층 정의", 777, chat_fn=Chat)
    self.assertFalse(Row["ok"])
    self.assertEqual(Row["error"], "finish_reason:length")

  def test_bad_json_is_not_ok(self) -> None:
    Chat = mock.Mock(return_value=_result("not json"))
    Row = probe_openrouter.probe("x/y", _doc(), "층 정의", 777, chat_fn=Chat)
    self.assertFalse(Row["ok"])
    self.assertTrue(Row["error"].startswith("DecompositionOutputError"))

  def test_request_exception_is_reported_not_raised(self) -> None:
    Chat = mock.Mock(side_effect=ValueError("enable_thinking False 인데 reasoning_content 가 비어 있지 않다"))
    Row = probe_openrouter.probe("x/y", _doc(), "층 정의", 777, chat_fn=Chat)
    self.assertFalse(Row["ok"])
    self.assertEqual(Row["error"], "ValueError: enable_thinking False 인데 reasoning_content 가 비어 있지 않다")
    self.assertIsNone(Row["prompt_tokens"])

  def test_key_never_appears_in_error(self) -> None:
    Chat = mock.Mock(side_effect=RuntimeError("Bearer sekret-123 rejected"))
    with mock.patch.dict(os.environ, {"LAYERED_WIKI_LLM_API_KEY": "sekret-123"}):
      Row = probe_openrouter.probe("x/y", _doc(), "층 정의", 777, chat_fn=Chat)
    self.assertNotIn("sekret-123", Row["error"])


if __name__ == "__main__":
  unittest.main()
