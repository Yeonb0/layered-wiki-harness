from typing import Callable

import os

import requests

EMBEDDING_ENDPOINT_ENV = "LAYERED_WIKI_EMBED_ENDPOINT"
EMBEDDING_MODEL = "bge-m3"
DEFAULT_TIMEOUT_SECONDS = 30

EmbedBackend = Callable[[list[str]], list[list[float]]]


def embed(text: str, backend: EmbedBackend | None = None) -> list[float]:
  return embed_batch([text], backend=backend)[0]


def embed_batch(Texts: list[str], backend: EmbedBackend | None = None) -> list[list[float]]:
  Call = backend or _call_llama_server
  return Call(Texts)


def _embedding_endpoint() -> str:
  # 8081 은 이제 생성 모델 서버라 상수로 두면 임베딩 요청이 엉뚱한 서버로 간다 — 호출 시점에 환경 변수로만 받는다
  Endpoint = os.environ.get(EMBEDDING_ENDPOINT_ENV, "")
  if not Endpoint:
    raise ValueError(f"{EMBEDDING_ENDPOINT_ENV} 가 설정되지 않았다")
  return Endpoint


def _call_llama_server(Texts: list[str]) -> list[list[float]]:
  Response = requests.post(
    _embedding_endpoint(),
    json={"model": EMBEDDING_MODEL, "input": Texts},
    timeout=DEFAULT_TIMEOUT_SECONDS,
  )
  Response.raise_for_status()
  Items = sorted(Response.json()["data"], key=lambda Item: Item["index"])
  Vectors = [Item["embedding"] for Item in Items]
  # 빈 벡터가 조용히 검색에 쓰이지 않게 길이 0 이면 막는다
  if any(len(Vector) == 0 for Vector in Vectors):
    raise ValueError("응답 벡터 길이가 0 이다")
  return Vectors
