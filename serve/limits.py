import datetime
import threading
from collections.abc import Callable


# 공개 시연 서버 (설계 9.6) : LLM 을 부르는 모든 경로가 함께 쓰는 하루 상한. 날짜가 바뀌면 0 으로
class DailyCounter:
  def __init__(self, limit: int, today_fn: Callable[[], datetime.date]) -> None:
    # 상한이 0 이하면 아무 요청도 받을 수 없다 : 설정 실수를 조용히 넘기지 않는다
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
      raise ValueError(f"limit 은 양의 정수여야 한다: {limit!r}")
    self.limit = limit
    self.today_fn = today_fn
    self._lock = threading.Lock()
    self._day = None
    self._used = 0

  def _roll(self) -> None:
    # 잠금 안에서만 부른다
    Today = self.today_fn()
    if Today != self._day:
      self._day = Today
      self._used = 0

  def take(self) -> bool:
    with self._lock:
      self._roll()
      if self._used >= self.limit:
        return False
      self._used += 1
      return True

  def give_back(self) -> None:
    # 자정을 넘겨 되돌리면 새 날의 카운트를 깎지 않는다 (0 아래로 가지 않는다)
    with self._lock:
      self._roll()
      if self._used > 0:
        self._used -= 1

  def used(self) -> int:
    with self._lock:
      self._roll()
      return self._used
