from dataclasses import dataclass


@dataclass
class RunConfig:
  condition: str
  mode: str
  k: int
  model_id: str
  num_ctx: int = 8192
  num_predict: int = 1024
  temperature: float = 0
  seed: int = 42
  threads: int = 0
