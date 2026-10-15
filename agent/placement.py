from dataclasses import dataclass, field

from agent.types import DownwardLink, NoteDraft, NoteRecord, PlacementVerdict, SourceDoc
from labeling.gold import group_for
from retrieval.search import LAYER_ORDER

MODES = ("all_layers", "split_by_layer")


@dataclass
class ValidationResult:
  valid: bool
  problems: list[str] = field(default_factory=list)
  verdict: PlacementVerdict | None = None


def _rank(layer: str) -> int:
  return LAYER_ORDER.index(layer)


def _check_links(Links, name: str, NoteLayer: str, ById: dict, want_upward: bool) -> list[str]:
  Problems = []
  # 링크 필드는 문자열 목록이어야 한다
  if not isinstance(Links, list) or not all(isinstance(L, str) for L in Links):
    Problems.append(f"{name}_not_string_list")
  else:
    for LinkId in Links:
      # 후보 밖 id 는 존재하지 않는 노트를 가리킨다
      if LinkId not in ById:
        Problems.append(f"{name}_unknown_id:{LinkId}")
      # 상향 링크는 같은 층 이상, 하향 링크는 더 낮은 층만 가리킨다 ( 방향 정의 )
      elif want_upward and _rank(ById[LinkId]) < _rank(NoteLayer):
        Problems.append(f"{name}_target_below_note:{LinkId}")
      elif not want_upward and _rank(ById[LinkId]) >= _rank(NoteLayer):
        Problems.append(f"{name}_target_not_below_note:{LinkId}")
  return Problems


def validate_placement(raw, mode: str, source_layer: str, Candidates: list) -> ValidationResult:
  # mode 는 두 값뿐 - 다른 값은 검색 필터 동작을 알 수 없다
  if mode not in MODES:
    raise ValueError(f"알 수 없는 mode: {mode!r}")
  # 출처 층이 층 순서에 없으면 비교할 수 없다
  if source_layer not in LAYER_ORDER:
    raise ValueError(f"알 수 없는 source_layer: {source_layer!r}")
  ById = {}
  for Cand in Candidates:
    # 후보 층이 층 순서에 없으면 링크 방향을 판정할 수 없다
    if Cand.layer not in LAYER_ORDER:
      raise ValueError(f"알 수 없는 후보 layer: {Cand.layer!r} ( {Cand.id} )")
    # 후보 id 가 겹치면 링크 대상 층이 모호하다
    if Cand.id in ById:
      raise ValueError(f"후보 id 중복: {Cand.id}")
    ById[Cand.id] = Cand.layer
  # 검색 필터 우회 - 층별 분리 모드에 출처보다 낮은 층 후보가 있으면 누출 하한선이 무너진다
  if mode == "split_by_layer" and any(_rank(L) < _rank(source_layer) for L in ById.values()):
    raise ValueError("split_by_layer 후보에 출처 층보다 낮은 층이 있다")

  # 판정은 객체여야 한다
  if not isinstance(raw, dict):
    return ValidationResult(valid=False, problems=["raw_not_object"])
  Problems = []
  Layer = raw.get("layer")
  LayerOk = isinstance(Layer, str) and Layer in LAYER_ORDER
  # 층이 층 순서 밖이면 이후 링크 방향을 판정할 수 없다
  if not LayerOk:
    Problems.append("layer_invalid")
  else:
    # 지침 3 절 : 층별 분리 모드에서 출처 층보다 위 새 노트 금지
    if mode == "split_by_layer" and _rank(Layer) > _rank(source_layer):
      raise ValueError(f"split_by_layer 에서 출처 층({source_layer}) 보다 위 판정: {Layer}")
    # 기준 §4 : 하향 배치 정답 없음
    if _rank(Layer) < _rank(source_layer):
      Problems.append("layer_below_source")
    Problems += _check_links(raw.get("upward_links"), "upward_links", Layer, ById, True)
    Problems += _check_links(raw.get("downward_links"), "downward_links", Layer, ById, False)
  # rationale 은 기록용 문자열이다
  if not isinstance(raw.get("rationale"), str):
    Problems.append("rationale_not_string")

  if Problems:
    return ValidationResult(valid=False, problems=Problems, verdict=None)
  Verdict = PlacementVerdict(
    layer=Layer,
    upward_links=list(raw["upward_links"]),
    downward_target_ids=list(raw["downward_links"]),
    rationale=raw["rationale"],
  )
  return ValidationResult(valid=True, problems=[], verdict=Verdict)


def build_note_record(
  draft: NoteDraft,
  verdict: PlacementVerdict,
  doc: SourceDoc,
  note_index: int,
  vault_size: int,
  LayerGroupById: dict,
  Owners,
) -> NoteRecord:
  NoteId = f"{doc.doc_id}#n{note_index}"
  # 노트 그룹 규칙은 정답 합성과 같은 함수를 그대로 쓴다 ( 규칙 복제 금지 )
  Group = group_for({"layer": doc.source_layer, "group": doc.source_group, "segment_id": NoteId}, verdict.layer, Owners)
  Links = []
  for TargetId in verdict.downward_target_ids:
    # 결정 D2 : 하니스가 대상 노트의 층 · 그룹으로 채운다 - 모르는 대상은 멈춘다
    if TargetId not in LayerGroupById:
      raise ValueError(f"하향 링크 대상이 볼트에 없다: {TargetId}")
    TargetLayer, TargetGroup = LayerGroupById[TargetId]
    Links.append(DownwardLink(target_id=TargetId, visibility_condition={"layer": TargetLayer, "group": TargetGroup}))
  return NoteRecord(
    note_id=NoteId,
    layer=verdict.layer,
    group=Group,
    title=draft.title,
    body=draft.body,
    source_doc_id=doc.doc_id,
    source_layer=doc.source_layer,
    source_group=doc.source_group,
    source_segment_ids=list(draft.source_segment_ids),
    upward_links=list(verdict.upward_links),
    downward_conditional_links=Links,
    inserted_at_vault_size=vault_size,
  )
