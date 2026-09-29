import argparse
import hashlib
import os
from itertools import product

from client.dify_client import DifyClient
from client.fake_client import FakeDifyClient
from config.run_config import RunConfig
from retrieval.search import Retriever
from runner.cold_start import ColdStartDetector
from runner.conditions import Condition, ConditionCell
from runner.doc_loader import load_docs
from runner.sequential_runner import run
from runner.types import ConditionCellState
from vault.jsonl_backend import JsonlVaultStore
from verdictlog.writer import VerdictLogWriter

# 조건/모드/k 전체 집합은 CLAUDE.md 가 이미 고정한 값 - 여기서 지어낸 게 아니라 그대로 옮긴 기본값이다
DEFAULT_CONDITIONS = "B0,B1,B2,제안"
DEFAULT_MODES = "all_layers,split_by_layer"
DEFAULT_KS = "4,8,16"


def parse_args() -> argparse.Namespace:
  Parser = argparse.ArgumentParser(description="계층형 기관 위키 파일럿 하니스 진입점")
  Parser.add_argument("--docs", required=True, help="입력 문서 JSONL 경로, 필드는 {id, title, body}")
  Parser.add_argument("--model-id", required=True, help="판정 LLM 식별자 - 실행 시점에 실제 로컬 빌드/양자화본을 적어라")
  Parser.add_argument("--threads", required=True, type=int, help="물리 코어 - 2, 실행 머신에서 직접 계산해서 전달")
  Parser.add_argument("--cold-start-threshold-seconds", required=True, type=float)
  Parser.add_argument("--vault-dir", required=True, help="조건-셀별 볼트 JSONL 파일을 생성할 디렉터리")
  Parser.add_argument("--log-path", required=True, help="볼트 밖 판정 로그 JSONL 경로")
  Parser.add_argument("--conditions", default=DEFAULT_CONDITIONS)
  Parser.add_argument("--modes", default=DEFAULT_MODES)
  Parser.add_argument("--ks", default=DEFAULT_KS)
  Parser.add_argument("--schedule-seed", type=int, required=True, help="투입 순서 시드 - 명시해야 사후에 순서를 재현할 수 있다")
  Parser.add_argument("--client", choices=["real", "fake"], default="real")
  Parser.add_argument("--criteria-path", required=True, help="라벨링 기준 v1 파일 경로 - SHA-256 을 RunConfig.criteria_sha256 에 기록한다")
  # 기본값으로 null 이 들어가면 본실험에서 라벨 해시가 조용히 빠진다
  LabelsGroup = Parser.add_mutually_exclusive_group(required=True)
  LabelsGroup.add_argument("--labels-path", help="라벨 파일 경로 - SHA-256 을 RunConfig.labels_sha256 에 기록한다")
  LabelsGroup.add_argument("--no-labels", action="store_true", help="라벨 없음 - RunConfig.labels_sha256 = None")
  return Parser.parse_args()


def _sha256_file(path: str) -> str:
  with open(path, "rb") as File:
    return hashlib.sha256(File.read()).hexdigest()


def build_condition_cell_states(
  Conditions: list[str],
  Modes: list[str],
  Ks: list[int],
  VaultDir: str,
  ModelId: str,
  Threads: int,
  CriteriaSha256: str,
  LabelsSha256: str | None,
) -> dict[ConditionCell, ConditionCellState]:
  States: dict[ConditionCell, ConditionCellState] = {}
  for ConditionValue, ModeValue, KValue in product(Conditions, Modes, Ks):
    Cell = ConditionCell(condition=Condition(ConditionValue), mode=ModeValue, k=KValue)
    VaultPath = os.path.join(VaultDir, f"{ConditionValue}_{ModeValue}_{KValue}.jsonl")
    States[Cell] = ConditionCellState(
      vault=JsonlVaultStore(VaultPath),
      retriever=Retriever(),
      run_config=RunConfig(
        condition=ConditionValue,
        mode=ModeValue,
        k=KValue,
        model_id=ModelId,
        criteria_sha256=CriteriaSha256,
        labels_sha256=LabelsSha256,
        threads=Threads,
      ),
    )
  return States


def main() -> None:
  Args = parse_args()

  Docs = load_docs(Args.docs)
  os.makedirs(Args.vault_dir, exist_ok=True)
  LogDir = os.path.dirname(Args.log_path)
  if LogDir:
    os.makedirs(LogDir, exist_ok=True)

  CriteriaSha256 = _sha256_file(Args.criteria_path)
  LabelsSha256 = None if Args.no_labels else _sha256_file(Args.labels_path)

  States = build_condition_cell_states(
    Conditions=Args.conditions.split(","),
    Modes=Args.modes.split(","),
    Ks=[int(K) for K in Args.ks.split(",")],
    VaultDir=Args.vault_dir,
    ModelId=Args.model_id,
    Threads=Args.threads,
    CriteriaSha256=CriteriaSha256,
    LabelsSha256=LabelsSha256,
  )

  Client = DifyClient.from_env() if Args.client == "real" else FakeDifyClient.from_env()

  run(
    Docs=Docs,
    ConditionCellStates=States,
    client=Client,
    log_writer=VerdictLogWriter(Args.log_path),
    cold_start_detector=ColdStartDetector(threshold_seconds=Args.cold_start_threshold_seconds),
    schedule_seed=Args.schedule_seed,
  )


if __name__ == "__main__":
  main()
