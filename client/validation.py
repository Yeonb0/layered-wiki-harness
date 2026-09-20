from dataclasses import dataclass

from client.types import WorkflowResult
from retrieval.search import LAYER_ORDER, Mode
from vault.types import DownwardConditionalLink
from verdictlog.types import Verdict


@dataclass
class ValidationResult:
  valid: bool
  problems: list[str]
  verdict: Verdict | None


def validate_outputs(result: WorkflowResult, mode: Mode, caller_layer: str | None) -> ValidationResult:
  if mode == "split_by_layer" and caller_layer is None:
    # retrieval.search 와 동일한 이유 - 검증기가 조용히 통과하면 누출 0 하한 기준선이 무너진다
    raise ValueError("split_by_layer 모드는 caller_layer 가 필요하다")

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
  elif mode == "split_by_layer" and Layer != caller_layer:
    # 층별 인스턴스는 자기 층 밖에 새 항목을 만들 권한이 없다 - 이게 누출 0 하한 기준선의 근거
    Problems.append("layer_exceeds_caller_scope_under_split_by_layer")

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
