import unittest

from client.fake_client import FakeDifyClient
from client.types import WorkflowResult
from client.validation import validate_outputs


def _ok_result(layer: str) -> WorkflowResult:
  return WorkflowResult(
    ok=True,
    errors=[],
    verdict={
      "layer": layer,
      "upward_links": [],
      "downward_conditional_links": [],
      "rationale": "근거",
    },
    log="raw output",
  )


# 이 파일의 _ok_result 픽스처는 링크를 두지 않으므로 candidates=[] 를 넘긴다 - 링크가 없으면 빈 리스트를 넘긴다는 규칙에 따른 것이며 값 자체는 픽스처일 뿐이고 규칙과 무관하다
class ValidateOutputsTest(unittest.TestCase):
  def test_valid_under_all_layers(self) -> None:
    Result = validate_outputs(_ok_result("팀"), mode="all_layers", caller_layer=None, candidates=[])
    self.assertTrue(Result.valid)
    self.assertEqual(Result.verdict.layer, "팀")

  def test_valid_under_split_by_layer_when_layer_matches_caller(self) -> None:
    Result = validate_outputs(
      _ok_result("개인"), mode="split_by_layer", caller_layer="개인", candidates=[], source_layer="개인"
    )
    self.assertTrue(Result.valid)

  def test_invalid_under_split_by_layer_when_layer_above_source(self) -> None:
    Result = validate_outputs(
      _ok_result("팀"), mode="split_by_layer", caller_layer="개인", candidates=[], source_layer="개인"
    )
    self.assertFalse(Result.valid)
    self.assertIn("layer_above_source_under_split_by_layer", Result.problems)

  def test_invalid_under_split_by_layer_when_layer_below_source(self) -> None:
    Result = validate_outputs(
      _ok_result("개인"), mode="split_by_layer", caller_layer="팀", candidates=[], source_layer="팀"
    )
    self.assertFalse(Result.valid)
    self.assertIn("layer_below_source", Result.problems)

  def test_invalid_under_all_layers_when_layer_below_source(self) -> None:
    Result = validate_outputs(_ok_result("개인"), mode="all_layers", caller_layer=None, candidates=[], source_layer="팀")
    self.assertFalse(Result.valid)
    self.assertIn("layer_below_source", Result.problems)

  def test_missing_caller_layer_under_split_by_layer_raises(self) -> None:
    with self.assertRaises(ValueError):
      validate_outputs(_ok_result("개인"), mode="split_by_layer", caller_layer=None, candidates=[])

  def test_ok_false_short_circuits_without_verdict(self) -> None:
    Result = validate_outputs(
      WorkflowResult(ok=False, errors=["workflow_status_not_succeeded"], verdict={}, log=""),
      mode="all_layers",
      caller_layer=None,
      candidates=[],
    )
    self.assertTrue(Result.valid)
    self.assertIsNone(Result.verdict)


class FakeDifyClientValidationTest(unittest.TestCase):
  def test_fake_client_output_passes_validation_under_split_by_layer(self) -> None:
    # FIXED_VERDICT 는 upward_links · downward_conditional_links 가 모두 빈 리스트라 candidates 와 겹칠 id 자체가 없다
    Client = FakeDifyClient()
    WorkflowResultValue, Retried = Client.run_workflow(
      doc="본문", candidates_json="[]", vault_size=0, mode="split_by_layer", run_config_json="{}"
    )
    Result = validate_outputs(
      WorkflowResultValue, mode="split_by_layer", caller_layer="개인", candidates=[], source_layer="개인"
    )
    self.assertFalse(Retried)
    self.assertTrue(Result.valid)
    self.assertEqual(Result.verdict.layer, "개인")


if __name__ == "__main__":
  unittest.main()
