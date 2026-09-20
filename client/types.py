from dataclasses import dataclass
from typing import Any


@dataclass
class WorkflowResult:
  ok: bool
  errors: list[str]
  verdict: dict[str, Any]
  log: str
