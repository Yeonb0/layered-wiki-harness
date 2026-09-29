import re
from dataclasses import dataclass

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class RunConfig:
  condition: str
  mode: str
  k: int
  model_id: str
  # 라벨링 기준 v1 §0 - 판정 로그는 RunConfig 스냅샷으로 기준 · 라벨 버전을 담는다. 파일럿은 labels_sha256 = null
  criteria_sha256: str
  labels_sha256: str | None
  num_ctx: int = 8192
  num_predict: int = 1024
  temperature: float = 0
  seed: int = 42
  threads: int = 0

  def __post_init__(self) -> None:
    # re 의 $ 는 끝 줄바꿈 앞에서도 일치한다 - 해시 뒤 개행이 조용히 통과하지 않게 fullmatch
    if not _SHA256_HEX_RE.fullmatch(self.criteria_sha256):
      raise ValueError(f"criteria_sha256 은 소문자 16진수 64자여야 한다: {self.criteria_sha256!r}")
    if self.labels_sha256 is not None and not _SHA256_HEX_RE.fullmatch(self.labels_sha256):
      raise ValueError(f"labels_sha256 은 소문자 16진수 64자거나 None 이어야 한다: {self.labels_sha256!r}")
