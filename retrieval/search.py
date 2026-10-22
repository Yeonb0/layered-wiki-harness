import math
from typing import Literal

from labeling.gold import Membership, visible_pairs_for
from retrieval.embeddings import EmbedBackend, embed
from retrieval.types import Candidate
from vault.types import DocumentRecord

Mode = Literal["all_layers", "split_by_layer"]

# 층 값 리터럴을 여기서 처음 확정 - 용어 고정 절의 표기를 그대로 사용, 하위 -> 상위 순서
LAYER_ORDER = ["개인", "팀", "전사"]
EXCERPT_LENGTH = 200


class _UnknownGroup:
  # 그룹을 넘기지 않고 색인한 노트의 표지 - 전사 노트의 그룹은 None 이라 None 을 "모름" 으로 쓸 수 없다
  def __repr__(self) -> str:
    return "UNKNOWN_GROUP"


UNKNOWN_GROUP = _UnknownGroup()


class Retriever:
  def __init__(self, embed_backend: EmbedBackend | None = None) -> None:
    self.Index: list[tuple[DocumentRecord, list[float]]] = []
    # Index 와 같은 순서로 노트의 그룹을 따로 보관한다 - 기존 Index 형식을 쓰는 코드를 깨지 않는다
    self.Groups: list = []
    self.embed_backend = embed_backend

  def add(self, record: DocumentRecord, *, group=UNKNOWN_GROUP) -> None:
    Vector = embed(_embedding_text(record), backend=self.embed_backend)
    self.Index.append((record, Vector))
    self.Groups.append(group)

  # v1 전용 - 층만 본다. v2 는 search_visible 을 쓴다
  def search(self, query: str, k: int, mode: Mode, caller_layer: str | None) -> list[Candidate]:
    QueryVector = embed(query, backend=self.embed_backend)
    Pool = self.Index
    if mode == "split_by_layer":
      if caller_layer is None:
        raise ValueError("split_by_layer 모드는 caller_layer 가 필요하다")
      # 확정 결정 2026-09-23 - 자기 층 + 상위 층. LAYER_ORDER 는 하위 -> 상위 순서이므로 idx 부터 끝까지
      AllowedLayers = set(LAYER_ORDER[LAYER_ORDER.index(caller_layer) :])
      Pool = [Entry for Entry in Pool if Entry[0].layer in AllowedLayers]
      # TODO 개인 층은 본인 것만 봐야 하나 DocumentRecord 에 소유자 필드가 없어 구현 보류
    Scored = [(_cosine_similarity(QueryVector, Vector), Record) for Record, Vector in Pool]
    Scored.sort(key=lambda Pair: Pair[0], reverse=True)
    return [
      Candidate(id=Record.id, layer=Record.layer, title=Record.title, excerpt=_excerpt(Record.body))
      for _, Record in Scored[:k]
    ]

  def search_visible(
    self, query: str, k: int, mode: Mode, caller_layer: str, caller_group: str | None, owners: Membership
  ) -> list[Candidate]:
    # mode 는 두 값뿐 - 다른 값은 가시 범위를 알 수 없다
    if mode not in ("all_layers", "split_by_layer"):
      raise ValueError(f"알 수 없는 mode: {mode!r}")
    Pool = list(zip(self.Index, self.Groups))
    if mode == "split_by_layer":
      # 호출 층이 층 순서에 없으면 허용 쌍을 만들 수 없다
      if caller_layer not in LAYER_ORDER:
        raise ValueError(f"알 수 없는 caller_layer: {caller_layer!r}")
      # 사용자 결정 2026-10-16 (나-2) : 그룹을 모르는 노트가 조용히 보이거나 숨는 것을 막는다
      if any(Group is UNKNOWN_GROUP for Group in self.Groups):
        raise ValueError("split_by_layer 색인에 그룹을 모르는 노트가 있다")
      # 사용자 결정 2026-10-16 (나-2) : 허용 쌍은 정답 합성과 같은 그룹 규칙에서 나온다 - 규칙 복제 금지
      # 사용자 결정 2026-10-22 : 층별 분리 검색에서 개인은 자기가 속한 모든 팀의 팀 노트를 본다 - 기존 설정은 결과가 같다
      Allowed = visible_pairs_for(caller_layer, caller_group, owners)
      Pool = [Entry for Entry in Pool if (Entry[0][0].layer, Entry[1]) in Allowed]
    QueryVector = embed(query, backend=self.embed_backend)
    Scored = [(_cosine_similarity(QueryVector, Vector), Record) for (Record, Vector), _ in Pool]
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
