import unittest

from runner.conditions import Condition, ConditionCell, build_interleaved_schedule
from runner.types import InputDoc


class BuildInterleavedScheduleTest(unittest.TestCase):
  def test_never_blocks_by_condition(self) -> None:
    Docs = [InputDoc(id=f"d{i}", title="제목", body="본문") for i in range(4)]
    Cells = [
      ConditionCell(condition=Condition.B0, mode="all_layers", k=4),
      ConditionCell(condition=Condition.B1, mode="all_layers", k=4),
      ConditionCell(condition=Condition.B2, mode="all_layers", k=4),
    ]

    Schedule = build_interleaved_schedule(Docs, Cells, seed=7)

    self.assertEqual(len(Schedule), len(Docs) * len(Cells))
    for BlockStart in range(0, len(Schedule), len(Cells)):
      Block = Schedule[BlockStart : BlockStart + len(Cells)]
      BlockDocIds = {Doc.id for Doc, _ in Block}
      BlockConditions = {Cell.condition for _, Cell in Block}
      # 조건마다 문서 1건씩만 처리한 뒤 다음 조건으로 넘어간다 - 블록으로 몰리지 않는다
      self.assertEqual(len(BlockDocIds), 1)
      self.assertEqual(BlockConditions, {Condition.B0, Condition.B1, Condition.B2})


if __name__ == "__main__":
  unittest.main()
