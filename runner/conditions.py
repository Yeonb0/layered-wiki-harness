import random
from dataclasses import dataclass
from enum import Enum

from retrieval.search import Mode
from runner.types import InputDoc


class Condition(str, Enum):
  B0 = "B0"
  B1 = "B1"
  B2 = "B2"
  PROPOSAL = "제안"


@dataclass(frozen=True)
class ConditionCell:
  # 조건 x 권한 모드 x k 조합 하나 - 밴딧 용어(Arm) 대신 실험 설계 용어(cell)를 쓴다
  condition: Condition
  mode: Mode
  k: int


def build_interleaved_schedule(
  Docs: list[InputDoc], Cells: list[ConditionCell], seed: int
) -> list[tuple[InputDoc, ConditionCell]]:
  # 조건을 블록으로 몰지 않고 건 단위로 섞는다 - doc 마다 cell 순서를 다시 섞는다
  Rng = random.Random(seed)
  ShuffledDocs = list(Docs)
  Rng.shuffle(ShuffledDocs)
  Schedule: list[tuple[InputDoc, ConditionCell]] = []
  for Doc in ShuffledDocs:
    CellOrder = list(Cells)
    Rng.shuffle(CellOrder)
    for SelectedCell in CellOrder:
      Schedule.append((Doc, SelectedCell))
  return Schedule
