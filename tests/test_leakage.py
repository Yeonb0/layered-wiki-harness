import unittest

from analysis.leakage import leakage_contrast


def _candidate(layer: str, excerpt: str) -> dict:
  return {"layer": layer, "excerpt": excerpt, "id": "c", "title": "t"}


class LeakageContrastTest(unittest.TestCase):
  def test_split_by_layer_is_zero_by_construction(self) -> None:
    # split_by_layer 는 caller_layer=개인 고정이라 verdict.layer 도 항상 개인 - 상위 배치 자체가 없다
    Entries = [
      {
        "verdict": {"layer": "개인"},
        "retrieved_candidates": [_candidate("개인", "프로젝트오로라 비밀수치42")],
        "doc_title": "새 문서",
        "doc_body": "프로젝트오로라 관련 내용",
      }
    ]
    Result = leakage_contrast(AllLayersEntries=[], SplitByLayerEntries=Entries)
    self.assertEqual(Result["split_by_layer"]["upper_layer_placements"], 0)
    self.assertEqual(Result["split_by_layer"]["entries_with_leakage"], 0)

  def test_detects_lower_layer_unique_term_appearing_in_upper_placement(self) -> None:
    Entries = [
      {
        "verdict": {"layer": "전사"},
        "retrieved_candidates": [
          _candidate("개인", "프로젝트오로라 내부코드"),
          _candidate("전사", "공개된 일반 내용"),
        ],
        "doc_title": "새 문서",
        "doc_body": "프로젝트오로라 관련 발표자료",
      }
    ]
    Stats = leakage_contrast(AllLayersEntries=Entries, SplitByLayerEntries=[])["all_layers"]
    self.assertEqual(Stats["upper_layer_placements"], 1)
    self.assertEqual(Stats["entries_with_leakage"], 1)
    self.assertGreaterEqual(Stats["total_leaked_terms"], 1)

  def test_term_present_in_same_or_higher_candidate_is_not_counted_as_leak(self) -> None:
    Entries = [
      {
        "verdict": {"layer": "전사"},
        "retrieved_candidates": [
          _candidate("개인", "프로젝트오로라 세부 사항"),
          _candidate("전사", "프로젝트오로라 공개 자료"),
        ],
        "doc_title": "새 문서",
        "doc_body": "프로젝트오로라 관련 내용",
      }
    ]
    Stats = leakage_contrast(AllLayersEntries=Entries, SplitByLayerEntries=[])["all_layers"]
    self.assertEqual(Stats["entries_with_leakage"], 0)


if __name__ == "__main__":
  unittest.main()
