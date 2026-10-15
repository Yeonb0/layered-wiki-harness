import os
import re
import time
from dataclasses import dataclass

import requests

LLM_ENDPOINT_ENV = "LAYERED_WIKI_LLM_ENDPOINT"

# 빈 think 블록 ( "<think>\n\n</think>" ) 은 끈 상태의 정상 출력이다 - 그 밖의 내용이 이어지면 새는 것이다
_LEAKED_THINK = re.compile(r"<think>\s*(?!</think>)\S")


@dataclass
class GenerationConfig:
  temperature: float
  seed: int
  max_tokens: int
  enable_thinking: bool


@dataclass
class ChatResult:
  text: str
  finish_reason: str | None
  prompt_tokens: int
  completion_tokens: int
  elapsed_seconds: float
  timings: dict | None
  request_body: dict
  response_body: dict


def _llm_endpoint() -> str:
  # 생성 서버 주소를 상수로 두면 임베딩 서버와 뒤바뀐 요청이 조용히 간다 - 호출 시점에 환경 변수로만 받는다
  Endpoint = os.environ.get(LLM_ENDPOINT_ENV, "")
  if not Endpoint:
    raise ValueError(f"{LLM_ENDPOINT_ENV} 가 설정되지 않았다")
  return Endpoint


def _require_token_count(Usage: dict, key: str) -> int:
  # 처리 시간 · 토큰 기록이 평가 인프라라 없으면 멈춘다
  Value = Usage.get(key)
  if not isinstance(Value, int) or isinstance(Value, bool):
    raise ValueError(f"usage.{key} 가 없거나 정수가 아니다")
  return Value


def chat(messages: list, model_id: str, config: GenerationConfig, response_schema: dict | None, *, timeout_seconds: float) -> ChatResult:
  Endpoint = _llm_endpoint()
  RequestBody = {
    "model": model_id,
    "messages": messages,
    "temperature": config.temperature,
    "seed": config.seed,
    "max_tokens": config.max_tokens,
    "chat_template_kwargs": {"enable_thinking": config.enable_thinking},
  }
  if response_schema is not None:
    RequestBody["response_format"] = {"type": "json_schema", "json_schema": {"name": "output", "schema": response_schema}}

  # 재시도하지 않는다 - 재시도가 처리 시간 측정을 흐리므로 실패는 예외로 올린다
  Started = time.monotonic()
  Response = requests.post(Endpoint, json=RequestBody, timeout=timeout_seconds)
  Elapsed = time.monotonic() - Started
  Response.raise_for_status()
  ResponseBody = Response.json()

  Choices = ResponseBody.get("choices")
  # 후보가 정확히 1개여야 어느 출력을 쓸지 모호하지 않다
  if not isinstance(Choices, list) or len(Choices) != 1:
    raise ValueError(f"choices 가 정확히 1개가 아니다: {Choices if not isinstance(Choices, list) else len(Choices)}")
  Choice = Choices[0]
  Message = Choice.get("message")
  if not isinstance(Message, dict):
    raise ValueError("choices[0].message 가 객체가 아니다")
  Content = Message.get("content")
  # 본문이 문자열이 아니면 출력이 없는 것이다
  if not isinstance(Content, str):
    raise ValueError("message.content 가 문자열이 아니다")

  # 결정 : thinking 은 전 조건에서 끈다 - 새면 조건 등가성이 깨진다
  if not config.enable_thinking:
    if Message.get("reasoning_content") not in (None, ""):
      raise ValueError("enable_thinking False 인데 reasoning_content 가 비어 있지 않다")
    if _LEAKED_THINK.search(Content):
      raise ValueError("enable_thinking False 인데 content 에 think 내용이 있다")

  Usage = ResponseBody.get("usage")
  if not isinstance(Usage, dict):
    raise ValueError("usage 가 없다")
  PromptTokens = _require_token_count(Usage, "prompt_tokens")
  CompletionTokens = _require_token_count(Usage, "completion_tokens")

  return ChatResult(
    text=Content,
    # "length" 면 잘린 출력이다 - 판단은 러너가 하므로 그대로 담는다
    finish_reason=Choice.get("finish_reason"),
    prompt_tokens=PromptTokens,
    completion_tokens=CompletionTokens,
    elapsed_seconds=Elapsed,
    timings=ResponseBody.get("timings"),
    request_body=RequestBody,
    response_body=ResponseBody,
  )
