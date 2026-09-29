import json
import unittest

from analysis.aggregate import describe_by, processing_time_stats, validation_breakdown, variance_by_condition


class DescribeByTest(unittest.TestCase):
  def test_groups_and_computes_variance_and_mean(self) -> None:
    Entries = [
      {"condition": "B0", "processing_time_seconds": 1.0},
      {"condition": "B0", "processing_time_seconds": 3.0},
      {"condition": "B1", "processing_time_seconds": 5.0},
    ]
    Grouped = describe_by(Entries, ("condition",), "processing_time_seconds")
    self.assertEqual(Grouped[("B0",)]["mean"], 2.0)
    self.assertEqual(Grouped[("B0",)]["variance"], 2.0)
    self.assertEqual(Grouped[("B1",)]["n"], 1)

  def test_variance_key_precedes_mean_key(self) -> None:
    Stats = describe_by([{"condition": "B0", "x": 1.0}], ("condition",), "x")[("B0",)]
    self.assertEqual(list(Stats.keys())[0], "variance")


class ProcessingTimeStatsTest(unittest.TestCase):
  def test_excludes_cold_start_and_retried_entries(self) -> None:
    Entries = [
      {"processing_time_seconds": 1.0, "cold_start": False, "retried": False},
      {"processing_time_seconds": 100.0, "cold_start": True, "retried": False},
      {"processing_time_seconds": 200.0, "cold_start": False, "retried": True},
      {"processing_time_seconds": 3.0, "cold_start": False, "retried": False},
    ]
    Stats = processing_time_stats(Entries)
    self.assertEqual(Stats["all"]["n"], 2)
    self.assertEqual(Stats["all"]["mean"], 2.0)


class VarianceByConditionTest(unittest.TestCase):
  def test_returns_variance_only(self) -> None:
    Entries = [
      {"condition": "B0", "x": 1.0},
      {"condition": "B0", "x": 3.0},
    ]
    self.assertEqual(variance_by_condition(Entries, "x")["B0"], 2.0)


class ValidationBreakdownTest(unittest.TestCase):
  def _cell(self, Entries: list[dict]) -> dict:
    return validation_breakdown(Entries)["cells"]["B0|split_by_layer|4"]

  def test_three_classifications_do_not_mix(self) -> None:
    Entries = [
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["layer_missing_or_not_string"],
      },
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["layer_above_source_under_split_by_layer"],
      },
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["layer_below_source"],
      },
    ]
    Trial = self._cell(Entries)["trials"]["t1"]
    self.assertEqual(Trial["schema_error"], {"numerator": 1, "denominator": 3})
    self.assertEqual(Trial["mode_rule_rejection"], {"numerator": 1, "denominator": 3})
    self.assertEqual(Trial["decision_violation"], {"numerator": 1, "denominator": 3})

  def test_entry_with_both_schema_error_and_decision_violation_counts_in_both(self) -> None:
    Entries = [
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["layer_missing_or_not_string", "layer_below_source"],
      }
    ]
    Trial = self._cell(Entries)["trials"]["t1"]
    self.assertEqual(Trial["schema_error"]["numerator"], 1)
    self.assertEqual(Trial["decision_violation"]["numerator"], 1)
    self.assertEqual(Trial["mode_rule_rejection"]["numerator"], 0)

  def test_variance_key_precedes_mean_key_in_cell_output(self) -> None:
    Entries = [
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": []},
    ]
    Cell = self._cell(Entries)
    self.assertEqual(list(Cell["schema_error_rate"].keys())[0], "variance")

  def test_variance_is_none_when_only_one_trial(self) -> None:
    Entries = [
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": []},
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": []},
    ]
    Cell = self._cell(Entries)
    self.assertIsNone(Cell["schema_error_rate"]["variance"])
    self.assertEqual(Cell["schema_error_rate"]["n_trials"], 1)

  def test_variance_matches_hand_computed_value_for_two_trials(self) -> None:
    Entries = [
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["layer_missing_or_not_string"],
      },
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": []},
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t2", "validation_problems": []},
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t2", "validation_problems": []},
    ]
    # t1 스키마 오류율 = 0.5, t2 스키마 오류율 = 0.0 - 평균 0.25, 분산(표본) = ((0.5-0.25)^2+(0-0.25)^2)/(2-1) = 0.125
    Cell = self._cell(Entries)
    self.assertEqual(Cell["schema_error_rate"]["mean"], 0.25)
    self.assertEqual(Cell["schema_error_rate"]["variance"], 0.125)
    self.assertEqual(Cell["schema_error_rate"]["n_trials"], 2)

  def test_entries_without_trial_id_are_excluded_and_counted(self) -> None:
    Entries = [
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": []},
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "validation_problems": []},
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": None, "validation_problems": []},
    ]
    Result = validation_breakdown(Entries)
    self.assertEqual(Result["excluded_without_trial_id"], 2)
    self.assertEqual(Result["cells"]["B0|split_by_layer|4"]["schema_error_rate"]["n_trials"], 1)

  def test_entries_without_cell_key_are_excluded_and_counted(self) -> None:
    Entries = [
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": []},
      {"condition": "B0", "mode": "split_by_layer", "trial_id": "t1", "validation_problems": []},
      {"mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": []},
    ]
    Result = validation_breakdown(Entries)
    self.assertEqual(Result["excluded_without_cell_key"], 2)
    self.assertEqual(Result["cells"]["B0|split_by_layer|4"]["schema_error_rate"]["n_trials"], 1)

  def test_result_is_json_serializable(self) -> None:
    Entries = [
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": [], "ok": True},
    ]
    json.dumps(validation_breakdown(Entries))

  def test_workflow_failure_is_counted_in_same_shape_as_other_classifications(self) -> None:
    Entries = [
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": [], "ok": False},
      {"condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1", "validation_problems": [], "ok": True},
    ]
    Cell = self._cell(Entries)
    self.assertEqual(Cell["trials"]["t1"]["workflow_failure"], {"numerator": 1, "denominator": 2})
    self.assertEqual(list(Cell["workflow_failure_rate"].keys())[0], "variance")
    self.assertEqual(Cell["workflow_failure_rate"]["mean"], 0.5)
    self.assertEqual(Cell["workflow_failure_rate"]["n_trials"], 1)

  def test_unregistered_problem_code_raises(self) -> None:
    # 등록되지 않은 코드가 스키마 오류로 조용히 떨어지면 결정 위반이 스키마 오류에 섞인다
    Entries = [
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["no_such_code"],
      },
    ]
    with self.assertRaises(ValueError):
      validation_breakdown(Entries)

  def test_link_decision_violation_codes_count_as_decision_violation(self) -> None:
    Entries = [
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["upward_link_target_below_verdict_layer"],
      },
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["downward_link_target_same_layer"],
      },
    ]
    Trial = self._cell(Entries)["trials"]["t1"]
    self.assertEqual(Trial["decision_violation"], {"numerator": 2, "denominator": 2})
    self.assertEqual(Trial["schema_error"]["numerator"], 0)

  def test_link_not_in_candidates_code_counts_as_schema_error(self) -> None:
    Entries = [
      {
        "condition": "B0", "mode": "split_by_layer", "k": 4, "trial_id": "t1",
        "validation_problems": ["upward_link_target_not_in_candidates"],
      },
    ]
    Trial = self._cell(Entries)["trials"]["t1"]
    self.assertEqual(Trial["schema_error"], {"numerator": 1, "denominator": 1})
    self.assertEqual(Trial["decision_violation"]["numerator"], 0)


if __name__ == "__main__":
  unittest.main()
