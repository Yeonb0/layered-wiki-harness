import datetime
import threading
import unittest

from serve.limits import DailyCounter


class DailyCounterTest(unittest.TestCase):
  # 픽스처일 뿐이며 규칙과 무관하다 - 날짜는 바꿔 끼우는 합성 시계
  def setUp(self) -> None:
    self.Today = datetime.date(2026, 12, 16)
    self.C = DailyCounter(30, lambda: self.Today)

  def test_thirty_then_refuse(self) -> None:
    for _ in range(30):
      self.assertTrue(self.C.take())
    self.assertFalse(self.C.take())
    self.assertEqual(self.C.used(), 30)

  def test_give_back_frees_one(self) -> None:
    for _ in range(30):
      self.C.take()
    self.C.give_back()
    self.assertEqual(self.C.used(), 29)
    self.assertTrue(self.C.take())
    self.assertFalse(self.C.take())

  def test_new_day_resets(self) -> None:
    for _ in range(30):
      self.C.take()
    self.Today = datetime.date(2026, 12, 17)
    self.assertEqual(self.C.used(), 0)
    self.assertTrue(self.C.take())

  def test_give_back_after_midnight_does_not_go_negative(self) -> None:
    self.C.take()
    self.Today = datetime.date(2026, 12, 17)
    self.C.give_back()
    self.assertEqual(self.C.used(), 0)

  def test_limit_must_be_positive(self) -> None:
    for Bad in (0, -1):
      with self.assertRaises(ValueError):
        DailyCounter(Bad, lambda: self.Today)

  def test_thread_safe(self) -> None:
    C = DailyCounter(500, lambda: self.Today)
    Taken = []
    def worker() -> None:
      for _ in range(100):
        if C.take():
          Taken.append(1)
    Threads = [threading.Thread(target=worker) for _ in range(8)]
    for T in Threads:
      T.start()
    for T in Threads:
      T.join()
    self.assertEqual(len(Taken), 500)
    self.assertEqual(C.used(), 500)


if __name__ == "__main__":
  unittest.main()
