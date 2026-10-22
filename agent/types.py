from dataclasses import dataclass


@dataclass
class SourceSegment:
  segment_id: str
  seq: int
  text: str


@dataclass
class SourceDoc:
  doc_id: str
  title: str
  source_layer: str
  source_group: str | None
  segments: list[SourceSegment]
  # 사용자 결정 2026-10-22 : 개인 문서의 팀 워크스페이스 - 기존 형식 코퍼스에는 없다
  source_team: str | None = None


@dataclass
class NoteDraft:
  title: str
  body: str
  source_segment_ids: list[str]


@dataclass
class DownwardLink:
  target_id: str
  # 키는 layer · group - 하니스가 대상 노트의 층 · 그룹으로 채운다 ( 결정 D2 )
  visibility_condition: dict


@dataclass
class PlacementVerdict:
  layer: str
  upward_links: list[str]
  downward_target_ids: list[str]
  rationale: str


@dataclass
class NoteRecord:
  note_id: str
  layer: str
  group: str | None
  title: str
  body: str
  source_doc_id: str
  source_layer: str
  source_group: str | None
  source_segment_ids: list[str]
  upward_links: list[str]
  downward_conditional_links: list[DownwardLink]
  inserted_at_vault_size: int
