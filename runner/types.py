from dataclasses import dataclass

from config.run_config import RunConfig
from retrieval.search import Retriever
from vault.store import VaultStore


@dataclass(frozen=True)
class InputDoc:
  id: str
  title: str
  body: str
  source_layer: str | None = None


@dataclass
class ConditionCellState:
  vault: VaultStore
  retriever: Retriever
  run_config: RunConfig
