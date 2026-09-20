class ColdStartDetector:
  def __init__(self, threshold_seconds: float) -> None:
    self.threshold_seconds = threshold_seconds
    self.last_call_ended_at: float | None = None

  def check(self, now: float) -> bool:
    # 직전 호출이 끝난 시점부터 잰다 - 시작 시점 기준이면 긴 생성 시간이 경과 시간에 그대로 얹혀 오판된다
    return self.last_call_ended_at is None or (now - self.last_call_ended_at) > self.threshold_seconds

  def record_call_end(self, ended_at: float) -> None:
    self.last_call_ended_at = ended_at
