import os
import unittest
from unittest import mock

from agent.llm_client import LLM_ENDPOINT_ENV, GenerationConfig, chat

# 픽스처일 뿐이며 규칙과 무관하다
_CONFIG = GenerationConfig(temperature=0.25, seed=123, max_tokens=77, enable_thinking=False)
_MESSAGES = [{"role": "user", "content": "합성 질문"}]
_SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
_URL = "http://127.0.0.1:0/v1/chat/completions"


def _body(Content="답", Reasoning=None, FinishReason="stop", Usage="default", Choices=None) -> dict:
  Message = {"role": "assistant", "content": Content}
  if Reasoning is not None:
    Message["reasoning_content"] = Reasoning
  Body = {"choices": [{"index": 0, "message": Message, "finish_reason": FinishReason}] if Choices is None else Choices}
  if Usage == "default":
    Body["usage"] = {"prompt_tokens": 11, "completion_tokens": 3}
  elif Usage is not None:
    Body["usage"] = Usage
  return Body


def _response(Body: dict) -> mock.Mock:
  Resp = mock.Mock()
  Resp.json.return_value = Body
  return Resp


def _call(Body: dict, Config=_CONFIG, Schema=_SCHEMA):
  # 네트워크 호출은 requests.post mock 으로 막는다 - 실제 서버를 부르지 않는다
  with mock.patch.dict(os.environ, {LLM_ENDPOINT_ENV: _URL}), mock.patch("requests.post", return_value=_response(Body)) as Post:
    Result = chat(_MESSAGES, "합성모델", Config, Schema, timeout_seconds=9)
  return Result, Post


class RequestBodyTest(unittest.TestCase):
  def test_config_values_go_into_request_body_as_is(self) -> None:
    Result, Post = _call(_body())
    Sent = Post.call_args.kwargs["json"]
    self.assertEqual(Sent["model"], "합성모델")
    self.assertEqual(Sent["messages"], _MESSAGES)
    self.assertEqual(Sent["temperature"], 0.25)
    self.assertEqual(Sent["seed"], 123)
    self.assertEqual(Sent["max_tokens"], 77)
    self.assertEqual(Sent["chat_template_kwargs"], {"enable_thinking": False})
    self.assertEqual(Post.call_args.args[0], _URL)
    self.assertEqual(Post.call_args.kwargs["timeout"], 9)
    self.assertEqual(Result.request_body, Sent)

  def test_response_schema_adds_response_format(self) -> None:
    _, Post = _call(_body())
    Sent = Post.call_args.kwargs["json"]
    self.assertEqual(Sent["response_format"], {"type": "json_schema", "json_schema": {"name": "output", "schema": _SCHEMA}})

  def test_no_schema_means_no_response_format_key(self) -> None:
    _, Post = _call(_body(), Schema=None)
    self.assertNotIn("response_format", Post.call_args.kwargs["json"])


class EndpointEnvTest(unittest.TestCase):
  def test_missing_env_raises_value_error_without_calling_post(self) -> None:
    Env = {Key: Value for Key, Value in os.environ.items() if Key != LLM_ENDPOINT_ENV}
    with mock.patch.dict(os.environ, Env, clear=True), mock.patch("requests.post") as Post:
      with self.assertRaises(ValueError):
        chat(_MESSAGES, "합성모델", _CONFIG, None, timeout_seconds=9)
      Post.assert_not_called()

  def test_empty_env_raises_value_error_without_calling_post(self) -> None:
    with mock.patch.dict(os.environ, {LLM_ENDPOINT_ENV: ""}), mock.patch("requests.post") as Post:
      with self.assertRaises(ValueError):
        chat(_MESSAGES, "합성모델", _CONFIG, None, timeout_seconds=9)
      Post.assert_not_called()


class ThinkingLeakTest(unittest.TestCase):
  def test_reasoning_content_with_thinking_off_raises(self) -> None:
    with self.assertRaises(ValueError):
      _call(_body(Reasoning="생각 내용"))

  def test_think_content_with_thinking_off_raises(self) -> None:
    with self.assertRaises(ValueError):
      _call(_body(Content="<think>내용"))

  def test_empty_think_block_passes(self) -> None:
    Result, _ = _call(_body(Content="<think>\n\n</think>답"))
    self.assertEqual(Result.text, "<think>\n\n</think>답")

  def test_empty_reasoning_content_passes(self) -> None:
    Result, _ = _call(_body(Reasoning=""))
    self.assertEqual(Result.text, "답")

  def test_thinking_on_does_not_check_leak(self) -> None:
    On = GenerationConfig(temperature=0.0, seed=1, max_tokens=8, enable_thinking=True)
    Result, _ = _call(_body(Reasoning="생각 내용"), Config=On)
    self.assertEqual(Result.text, "답")


class ResponseCheckTest(unittest.TestCase):
  def test_missing_usage_raises(self) -> None:
    with self.assertRaises(ValueError):
      _call(_body(Usage=None))

  def test_usage_without_completion_tokens_raises(self) -> None:
    with self.assertRaises(ValueError):
      _call(_body(Usage={"prompt_tokens": 11}))

  def test_two_choices_raises(self) -> None:
    Message = {"role": "assistant", "content": "답"}
    Two = [{"index": 0, "message": Message, "finish_reason": "stop"}, {"index": 1, "message": Message, "finish_reason": "stop"}]
    with self.assertRaises(ValueError):
      _call(_body(Choices=Two))

  def test_finish_reason_length_is_kept_and_fields_filled(self) -> None:
    Body = _body(FinishReason="length")
    Body["timings"] = {"predicted_per_second": 12.5}
    Result, _ = _call(Body)
    self.assertEqual(Result.finish_reason, "length")
    self.assertEqual(Result.prompt_tokens, 11)
    self.assertEqual(Result.completion_tokens, 3)
    self.assertEqual(Result.timings, {"predicted_per_second": 12.5})
    self.assertEqual(Result.response_body, Body)
    self.assertGreaterEqual(Result.elapsed_seconds, 0.0)

  def test_timings_none_when_absent(self) -> None:
    Result, _ = _call(_body())
    self.assertIsNone(Result.timings)


if __name__ == "__main__":
  unittest.main()
