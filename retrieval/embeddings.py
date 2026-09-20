from typing import Callable

import requests

EMBEDDING_ENDPOINT = "http://localhost:8081/v1/embeddings"
EMBEDDING_MODEL = "bge-m3"
DEFAULT_TIMEOUT_SECONDS = 30

EmbedBackend = Callable[[list[str]], list[list[float]]]


def embed(text: str, backend: EmbedBackend | None = None) -> list[float]:
  return embed_batch([text], backend=backend)[0]


def embed_batch(Texts: list[str], backend: EmbedBackend | None = None) -> list[list[float]]:
  Call = backend or _call_llama_server
  return Call(Texts)


def _call_llama_server(Texts: list[str]) -> list[list[float]]:
  Response = requests.post(
    EMBEDDING_ENDPOINT,
    json={"model": EMBEDDING_MODEL, "input": Texts},
    timeout=DEFAULT_TIMEOUT_SECONDS,
  )
  Response.raise_for_status()
  Items = sorted(Response.json()["data"], key=lambda Item: Item["index"])
  return [Item["embedding"] for Item in Items]
