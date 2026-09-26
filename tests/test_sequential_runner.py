import unittest

from client.fake_client import FakeDifyClient
from config.run_config import RunConfig
from retrieval.search import Retriever
from runner.cold_start import ColdStartDetector
from runner.conditions import Condition, ConditionCell
from runner.sequential_runner import run
from runner.types import ConditionCellState, InputDoc
from vault.types import DocumentRecord


def _fake_backend(Texts: list[str]) -> list[list[float]]:
  return [[1.0, 0.0] for _ in Texts]


class InMemoryVaultStore:
  def __init__(self) -> None:
    self.Records: list[DocumentRecord] = []

  def append(self, record: DocumentRecord) -> None:
    self.Records.append(record)

  def load_all(self) -> list[DocumentRecord]:
    return list(self.Records)

  def size(self) -> int:
    return len(self.Records)


class LogSpy:
  def __init__(self) -> None:
    self.Entries: list = []

  def append(self, entry) -> None:
    self.Entries.append(entry)


class SpyRetriever:
  def __init__(self) -> None:
    self.Calls: list[tuple[str, str | None]] = []

  def search(self, query: str, k: int, mode: str, caller_layer: str | None) -> list:
    self.Calls.append((mode, caller_layer))
    return []

  def add(self, record: DocumentRecord) -> None:
    pass


def _build_cell_state(condition: str, mode: str) -> ConditionCellState:
  return ConditionCellState(
    vault=InMemoryVaultStore(),
    retriever=Retriever(embed_backend=_fake_backend),
    run_config=RunConfig(condition=condition, mode=mode, k=4, model_id="fake"),
  )


class SequentialRunnerTest(unittest.TestCase):
  def test_fills_vaults_and_logs_every_insertion(self) -> None:
    # source_layer 값은 테스트 픽스처일 뿐이며 출처 층 부여 규칙과 무관하다
    Docs = [InputDoc(id=f"d{i}", title=f"제목{i}", body=f"본문{i}", source_layer="개인") for i in range(3)]
    CellA = ConditionCell(condition=Condition.B0, mode="all_layers", k=4)
    CellB = ConditionCell(condition=Condition.B1, mode="split_by_layer", k=4)
    States = {CellA: _build_cell_state("B0", "all_layers"), CellB: _build_cell_state("B1", "split_by_layer")}
    Log = LogSpy()

    run(
      Docs=Docs,
      ConditionCellStates=States,
      client=FakeDifyClient(),
      log_writer=Log,
      cold_start_detector=ColdStartDetector(threshold_seconds=999),
      schedule_seed=1,
    )

    self.assertEqual(len(Log.Entries), len(Docs) * len(States))
    self.assertEqual(States[CellA].vault.size(), len(Docs))
    self.assertEqual(States[CellB].vault.size(), len(Docs))

  def test_rejects_non_empty_vault(self) -> None:
    Docs = [InputDoc(id="d0", title="제목", body="본문")]
    Cell = ConditionCell(condition=Condition.B0, mode="all_layers", k=4)
    State = _build_cell_state("B0", "all_layers")
    State.vault.append(
      DocumentRecord(
        id="existing",
        layer="개인",
        title="기존",
        body="기존",
        upward_links=[],
        downward_conditional_links=[],
        inserted_at_vault_size=0,
      )
    )

    with self.assertRaises(ValueError):
      run(
        Docs=Docs,
        ConditionCellStates={Cell: State},
        client=FakeDifyClient(),
        log_writer=LogSpy(),
        cold_start_detector=ColdStartDetector(threshold_seconds=999),
        schedule_seed=1,
      )

  def test_split_by_layer_without_source_layer_raises(self) -> None:
    # 확정 결정 2026-09-26 - source_layer 없이 조용히 기본값을 쓰면 누출 0 하한 기준선이 무너진다
    Docs = [InputDoc(id="d0", title="제목", body="본문", source_layer=None)]
    Cell = ConditionCell(condition=Condition.B1, mode="split_by_layer", k=4)
    State = _build_cell_state("B1", "split_by_layer")

    with self.assertRaises(ValueError):
      run(
        Docs=Docs,
        ConditionCellStates={Cell: State},
        client=FakeDifyClient(),
        log_writer=LogSpy(),
        cold_start_detector=ColdStartDetector(threshold_seconds=999),
        schedule_seed=1,
      )

  def test_split_by_layer_passes_source_layer_as_caller_layer_to_search(self) -> None:
    # 러너가 출처 층을 검색에 넘기지 않으면 층별 분리 모드가 전 층 열람과 같아진다 - 개인 픽스처만으로는 이 회귀를 잡을 수 없다
    Doc = InputDoc(id="d0", title="제목", body="본문", source_layer="팀")

    SpyForSplit = SpyRetriever()
    CellSplit = ConditionCell(condition=Condition.B0, mode="split_by_layer", k=4)
    StateSplit = ConditionCellState(
      vault=InMemoryVaultStore(), retriever=SpyForSplit, run_config=RunConfig(condition="B0", mode="split_by_layer", k=4, model_id="fake")
    )
    run(
      Docs=[Doc],
      ConditionCellStates={CellSplit: StateSplit},
      client=FakeDifyClient(),
      log_writer=LogSpy(),
      cold_start_detector=ColdStartDetector(threshold_seconds=999),
      schedule_seed=1,
    )
    self.assertEqual(SpyForSplit.Calls[-1][0], "split_by_layer")
    self.assertEqual(SpyForSplit.Calls[-1][1], "팀")

    SpyForAll = SpyRetriever()
    CellAll = ConditionCell(condition=Condition.B0, mode="all_layers", k=4)
    StateAll = ConditionCellState(
      vault=InMemoryVaultStore(), retriever=SpyForAll, run_config=RunConfig(condition="B0", mode="all_layers", k=4, model_id="fake")
    )
    run(
      Docs=[Doc],
      ConditionCellStates={CellAll: StateAll},
      client=FakeDifyClient(),
      log_writer=LogSpy(),
      cold_start_detector=ColdStartDetector(threshold_seconds=999),
      schedule_seed=1,
    )
    self.assertEqual(SpyForAll.Calls[-1][0], "all_layers")
    self.assertIsNone(SpyForAll.Calls[-1][1])


if __name__ == "__main__":
  unittest.main()
