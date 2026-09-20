import re
from typing import Any

from retrieval.search import LAYER_ORDER

TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
MIN_TOKEN_LENGTH = 2


def leakage_contrast(AllLayersEntries: list[dict[str, Any]], SplitByLayerEntries: list[dict[str, Any]]) -> dict[str, Any]:
  # 층별 분리 모드는 정의상 누출 0 하한 기준선 - 여기서 하드코딩하지 않고 동일 로직을 양쪽에 그대로 돌려서 확인한다
  return {
    "all_layers": _leakage_for_entries(AllLayersEntries),
    "split_by_layer": _leakage_for_entries(SplitByLayerEntries),
  }


def _leakage_for_entries(Entries: list[dict[str, Any]]) -> dict[str, Any]:
  UpperLayerPlacements = 0
  EntriesWithLeakage = 0
  TotalLeakedTerms = 0

  for Entry in Entries:
    Verdict = Entry.get("verdict")
    if not Verdict:
      continue
    TargetLayer = Verdict.get("layer")
    if TargetLayer not in LAYER_ORDER:
      continue
    TargetIndex = LAYER_ORDER.index(TargetLayer)
    if TargetIndex == 0:
      continue  # 개인 배치는 상위 항목이 아니므로 대상 아님

    UpperLayerPlacements += 1

    LowerTerms: set[str] = set()
    SameOrHigherTerms: set[str] = set()
    for Candidate in Entry.get("retrieved_candidates") or []:
      CandidateLayer = Candidate.get("layer")
      if CandidateLayer not in LAYER_ORDER:
        continue
      Terms = _tokenize(Candidate.get("excerpt") or "")
      if LAYER_ORDER.index(CandidateLayer) < TargetIndex:
        LowerTerms |= Terms
      else:
        SameOrHigherTerms |= Terms

    UniqueLowerTerms = LowerTerms - SameOrHigherTerms
    DocTerms = _tokenize((Entry.get("doc_title") or "") + " " + (Entry.get("doc_body") or ""))
    LeakedTerms = UniqueLowerTerms & DocTerms

    if LeakedTerms:
      EntriesWithLeakage += 1
      TotalLeakedTerms += len(LeakedTerms)

  return {
    "upper_layer_placements": UpperLayerPlacements,
    "entries_with_leakage": EntriesWithLeakage,
    "total_leaked_terms": TotalLeakedTerms,
  }


def _tokenize(text: str) -> set[str]:
  return {Token for Token in TOKEN_PATTERN.findall(text) if len(Token) >= MIN_TOKEN_LENGTH}
