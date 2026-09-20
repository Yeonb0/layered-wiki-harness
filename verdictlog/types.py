from dataclasses import dataclass
from typing import Any

from retrieval.search import Mode
from retrieval.types import Candidate
from runner.conditions import Condition
from vault.types import DownwardConditionalLink


@dataclass
class Verdict:
  layer: str
  upward_links: list[str]
  downward_conditional_links: list[DownwardConditionalLink]
  rationale: str


@dataclass
class VerdictLogEntry:
  entry_id: str
  wall_clock: str
  run_index: int
  doc_id: str
  doc_title: str
  doc_body: str
  condition: Condition
  mode: Mode
  k: int
  vault_size: int
  retrieved_candidates: list[Candidate]
  ok: Any
  errors: Any
  raw_verdict: Any
  verdict: Verdict | None
  validation_problems: list[str]
  selection_rationale: str
  model_raw_output: Any
  cold_start: bool
  retried: bool
  processing_time_seconds: float
  run_config_snapshot: dict[str, Any]
