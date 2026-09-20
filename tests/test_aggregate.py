import unittest

from analysis.aggregate import describe_by, processing_time_stats, variance_by_condition


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


if __name__ == "__main__":
  unittest.main()
