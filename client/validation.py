from dataclasses import dataclass

from client.types import WorkflowResult
from retrieval.search import LAYER_ORDER, Mode
from retrieval.types import Candidate
from vault.types import DownwardConditionalLink
from verdictlog.types import Verdict


@dataclass
class ValidationResult:
  valid: bool
  problems: list[str]
  verdict: Verdict | None


def validate_outputs(
  # candidates 필수 인자 추가 - 링크 대상의 층을 모르면 고정 결정 "링크 방향은 아래에서 위로만" 을 검사할 수 없다
  result: WorkflowResult, mode: Mode, caller_layer: str | None, candidates: list[Candidate], source_layer: str | None = None
) -> ValidationResult:
  if mode == "split_by_layer" and caller_layer is None:
    # retrieval.search 와 동일한 이유 - 검증기가 조용히 통과하면 누출 0 하한 기준선이 무너진다
    raise ValueError("split_by_layer 모드는 caller_layer 가 필요하다")

  if mode == "split_by_layer" and caller_layer != source_layer:
    # 확정 결정 2026-09-26 - 층별 분리 모드의 caller_layer 는 문서의 출처 층과 같아야 한다
    raise ValueError("split_by_layer 모드는 caller_layer 와 source_layer 가 같아야 한다")

  if mode == "split_by_layer":
    # 검색 필터가 깨졌거나 우회된 것이며, 층별 분리 모드가 전 층 열람과 같아져 누출 0 하한 기준선이 무너진다 - problem 이 아니라 예외로 멈춘다
    CallerLayerIndex = LAYER_ORDER.index(caller_layer)
    if any(LAYER_ORDER.index(C.layer) < CallerLayerIndex for C in candidates):
      raise ValueError("split_by_layer 모드의 candidates 에 caller_layer 보다 낮은 층의 후보가 있다")

  Problems: list[str] = []

  if not isinstance(result.ok, bool):
    Problems.append("ok_not_boolean")
    return ValidationResult(valid=False, problems=Problems, verdict=None)

  if not isinstance(result.errors, list) or not all(isinstance(X, str) for X in result.errors):
    Problems.append("errors_not_string_list")

  if not isinstance(result.log, str):
    Problems.append("log_not_string")

  if not result.ok:
    if Problems:
      return ValidationResult(valid=False, problems=Problems, verdict=None)
    return ValidationResult(valid=True, problems=[], verdict=None)

  RawVerdict = result.verdict
  if not isinstance(RawVerdict, dict):
    Problems.append("verdict_not_object")
    return ValidationResult(valid=False, problems=Problems, verdict=None)

  Layer = RawVerdict.get("layer")
  if not isinstance(Layer, str):
    Problems.append("layer_missing_or_not_string")
  elif Layer not in LAYER_ORDER:
    Problems.append("layer_not_recognized")
  else:
    if mode == "split_by_layer" and LAYER_ORDER.index(Layer) > LAYER_ORDER.index(caller_layer):
      # 확정 결정 2026-09-26 - 층별 분리 모드의 판정 층은 출처 층으로 제한
      Problems.append("layer_above_source_under_split_by_layer")
    if source_layer is not None and LAYER_ORDER.index(Layer) < LAYER_ORDER.index(source_layer):
      # 모드와 무관하다 - split_by_layer 에서는 caller_layer 가 source_layer 와 같으므로 위 caller_layer 비교와 겹치지 않는다
      Problems.append("layer_below_source")

  UpwardLinks = RawVerdict.get("upward_links")
  if not isinstance(UpwardLinks, list) or not all(isinstance(X, str) for X in UpwardLinks):
    Problems.append("upward_links_invalid")
    UpwardLinks = []

  DownwardLinks: list[DownwardConditionalLink] = []
  RawDownward = RawVerdict.get("downward_conditional_links")
  if not isinstance(RawDownward, list):
    Problems.append("downward_conditional_links_invalid")
  else:
    for Item in RawDownward:
      if (
        isinstance(Item, dict)
        and isinstance(Item.get("target_id"), str)
        and isinstance(Item.get("visibility_condition"), str)
      ):
        DownwardLinks.append(
          DownwardConditionalLink(target_id=Item["target_id"], visibility_condition=Item["visibility_condition"])
        )
      else:
        Problems.append("downward_conditional_link_item_invalid")

  # candidates 로 링크 대상의 층을 확인 - 후보 목록 밖 id 는 층을 알 수 없어 방향 검사보다 먼저 걸러야 한다
  CandidateLayerById = {C.id: C.layer for C in candidates}
  VerdictLayerValid = isinstance(Layer, str) and Layer in LAYER_ORDER

  for LinkId in UpwardLinks:
    if LinkId not in CandidateLayerById:
      Problems.append("upward_link_target_not_in_candidates")
    elif VerdictLayerValid:
      # 판정 층이 무효면 비교할 기준이 없으므로 층 비교는 건너뛴다
      TargetLayer = CandidateLayerById[LinkId]
      if LAYER_ORDER.index(TargetLayer) < LAYER_ORDER.index(Layer):
        # 고정 결정 - 링크 방향은 아래에서 위로만. 같은 층은 확정 결정 2026-09-26 에 따라 상향 링크로 허용
        Problems.append("upward_link_target_below_verdict_layer")

  for DownwardLink in DownwardLinks:
    if DownwardLink.target_id not in CandidateLayerById:
      # target_id 가 어느 쪽 끝인지 아직 확정되지 않아 층 방향 검사는 넣지 않는다
      Problems.append("downward_link_target_not_in_candidates")
    elif VerdictLayerValid and CandidateLayerById[DownwardLink.target_id] == Layer:
      # 확정 결정 2026-09-26 - 같은 층 링크는 상향 링크로 기록한다. 층이 다른 경우의 방향 검사는 넣지 않는다
      Problems.append("downward_link_target_same_layer")

  Rationale = RawVerdict.get("rationale")
  if not isinstance(Rationale, str):
    Problems.append("rationale_missing_or_not_string")
    Rationale = ""

  if Problems:
    return ValidationResult(valid=False, problems=Problems, verdict=None)

  ParsedVerdict = Verdict(
    layer=Layer,
    upward_links=UpwardLinks,
    downward_conditional_links=DownwardLinks,
    rationale=Rationale,
  )
  return ValidationResult(valid=True, problems=[], verdict=ParsedVerdict)
