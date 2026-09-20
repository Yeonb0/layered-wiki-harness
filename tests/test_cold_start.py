import unittest

from runner.cold_start import ColdStartDetector


class ColdStartDetectorTest(unittest.TestCase):
  def test_first_check_is_cold_start(self) -> None:
    Detector = ColdStartDetector(threshold_seconds=5.0)
    self.assertTrue(Detector.check(now=0.0))

  def test_long_call_duration_does_not_trigger_false_cold_start(self) -> None:
    Detector = ColdStartDetector(threshold_seconds=5.0)
    Detector.record_call_end(ended_at=20.0)  # 호출 자체가 20 초 걸려 끝났다
    self.assertFalse(Detector.check(now=20.5))  # 끝난 직후 다음 호출 - 콜드 스타트 아니다

  def test_idle_gap_after_call_end_exceeding_threshold_is_cold_start(self) -> None:
    Detector = ColdStartDetector(threshold_seconds=5.0)
    Detector.record_call_end(ended_at=0.0)
    self.assertTrue(Detector.check(now=10.0))


if __name__ == "__main__":
  unittest.main()
