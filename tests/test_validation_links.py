import unittest

from client.types import WorkflowResult
from client.validation import validate_outputs
from retrieval.types import Candidate

# 후보 픽스처 - 개인 · 팀 · 전사 하나씩 둔다. 값 자체는 픽스처일 뿐이며 규칙과 무관하다
CANDIDATE_PERSONAL = Candidate(id="cand-personal", layer="개인", title="개인 후보", excerpt="개인 발췌")
CANDIDATE_TEAM = Candidate(id="cand-team", layer="팀", title="팀 후보", excerpt="팀 발췌")
CANDIDATE_ORG = Candidate(id="cand-org", layer="전사", title="전사 후보", excerpt="전사 발췌")
CANDIDATES_ALL = [CANDIDATE_PERSONAL, CANDIDATE_TEAM, CANDIDATE_ORG]
# split_by_layer 는 caller_layer(팀) 보다 낮은 층의 후보가 있으면 ValueError 이므로 개인 후보를 빼둔다
CANDIDATES_SPLIT = [CANDIDATE_TEAM, CANDIDATE_ORG]


def _result(upward_links: list[str] | None = None, downward_conditional_links: list[dict] | None = None) -> WorkflowResult:
  return WorkflowResult(
    ok=True,
    errors=[],
    verdict={
      # 판정 층은 팀으로 고정한다 - 개인이면 더 낮은 층이 없어 상향 링크 방향 버그가 드러나지 않는다
      "layer": "팀",
      "upward_links": upward_links or [],
      "downward_conditional_links": downward_conditional_links or [],
      "rationale": "근거",
    },
    log="raw output",
  )


class ValidationLinksTest(unittest.TestCase):
  def _assert_same_under_both_modes(
    self,
    upward_links: list[str] | None = None,
    downward_conditional_links: list[dict] | None = None,
    expected_problem: str | None = None,
    expect_valid: bool | None = None,
  ) -> None:
    # all_layers 와 split_by_layer 모두에서 방향 검사가 같게 동작하는지 같은 자리에서 확인한다
    for Mode, CallerLayer, SourceLayer, Candidates in (
      ("all_layers", None, None, CANDIDATES_ALL),
      ("split_by_layer", "팀", "팀", CANDIDATES_SPLIT),
    ):
      with self.subTest(mode=Mode):
        Result = validate_outputs(
          _result(upward_links=upward_links, downward_conditional_links=downward_conditional_links),
          mode=Mode,
          caller_layer=CallerLayer,
          candidates=Candidates,
          source_layer=SourceLayer,
        )
        if expect_valid is not None:
          self.assertEqual(Result.valid, expect_valid)
        if expected_problem is not None:
          self.assertIn(expected_problem, Result.problems)
        else:
          self.assertEqual(Result.problems, [])

  def test_upward_link_to_lower_layer_candidate_is_invalid(self) -> None:
    # split_by_layer 는 candidates 가 caller_layer 이상 층만 담으므로 더 낮은 층 후보가 존재할 수 없다 - all_layers 에서만 돈다
    Result = validate_outputs(
      _result(upward_links=[CANDIDATE_PERSONAL.id]),
      mode="all_layers",
      caller_layer=None,
      candidates=CANDIDATES_ALL,
      source_layer=None,
    )
    self.assertFalse(Result.valid)
    self.assertIn("upward_link_target_below_verdict_layer", Result.problems)

  def test_split_by_layer_with_lower_layer_candidate_raises(self) -> None:
    # 회귀 - 검색 필터가 깨지거나 우회되면 candidates 에 caller_layer 아래 층이 섞여 들어올 수 있다
    with self.assertRaises(ValueError):
      validate_outputs(
        _result(),
        mode="split_by_layer",
        caller_layer="팀",
        candidates=[CANDIDATE_PERSONAL, CANDIDATE_TEAM],
        source_layer="팀",
      )

  def test_upward_link_to_same_layer_candidate_is_valid(self) -> None:
    # 확정 결정 2026-09-26 - 같은 층 링크는 상향 링크로 허용
    self._assert_same_under_both_modes(upward_links=[CANDIDATE_TEAM.id], expect_valid=True)

  def test_upward_link_to_higher_layer_candidate_is_valid(self) -> None:
    self._assert_same_under_both_modes(upward_links=[CANDIDATE_ORG.id], expect_valid=True)

  def test_upward_link_to_id_not_in_candidates_is_invalid(self) -> None:
    self._assert_same_under_both_modes(
      upward_links=["없는-id"],
      expected_problem="upward_link_target_not_in_candidates",
      expect_valid=False,
    )

  def test_downward_link_to_target_id_not_in_candidates_is_invalid(self) -> None:
    self._assert_same_under_both_modes(
      downward_conditional_links=[{"target_id": "없는-id", "visibility_condition": "조건"}],
      expected_problem="downward_link_target_not_in_candidates",
      expect_valid=False,
    )


if __name__ == "__main__":
  unittest.main()
