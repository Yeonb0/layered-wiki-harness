import math
from typing import Literal

from retrieval.embeddings import EmbedBackend, embed
from retrieval.types import Candidate
from vault.types import DocumentRecord

Mode = Literal["all_layers", "split_by_layer"]

# 층 값 리터럴을 여기서 처음 확정 - 용어 고정 절의 표기를 그대로 사용, 하위 -> 상위 순서
LAYER_ORDER = ["개인", "팀", "전사"]
EXCERPT_LENGTH = 200


class Retriever:
  def __init__(self, embed_backend: EmbedBackend | None = None) -> None:
    self.Index: list[tuple[DocumentRecord, list[float]]] = []
    self.embed_backend = embed_backend

  def add(self, record: DocumentRecord) -> None:
    Vector = embed(_embedding_text(record), backend=self.embed_backend)
    self.Index.append((record, Vector))

  def search(self, query: str, k: int, mode: Mode, caller_layer: str | None) -> list[Candidate]:
    QueryVector = embed(query, backend=self.embed_backend)
    Pool = self.Index
    if mode == "split_by_layer":
      if caller_layer is None:
        raise ValueError("split_by_layer 모드는 caller_layer 가 필요하다")
      AllowedLayers = set(LAYER_ORDER[: LAYER_ORDER.index(caller_layer) + 1])
      Pool = [Entry for Entry in Pool if Entry[0].layer in AllowedLayers]
    Scored = [(_cosine_similarity(QueryVector, Vector), Record) for Record, Vector in Pool]
    Scored.sort(key=lambda Pair: Pair[0], reverse=True)
    return [
      Candidate(id=Record.id, layer=Record.layer, title=Record.title, excerpt=_excerpt(Record.body))
      for _, Record in Scored[:k]
    ]


# 확장 지점 - 검색 전략(하이브리드 등) 세부는 미결정, Retriever.search 내부 구현만 나중에 교체한다


def _embedding_text(record: DocumentRecord) -> str:
  return record.title + "\n" + record.body


def _excerpt(body: str) -> str:
  return body[:EXCERPT_LENGTH]


def _cosine_similarity(A: list[float], B: list[float]) -> float:
  Dot = sum(X * Y for X, Y in zip(A, B))
  NormA = math.sqrt(sum(X * X for X in A))
  NormB = math.sqrt(sum(Y * Y for Y in B))
  if NormA == 0 or NormB == 0:
    return 0.0
  return Dot / (NormA * NormB)
