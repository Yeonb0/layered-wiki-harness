import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_pilot
from analysis.aggregate import load_log
from runner.conditions import Condition, ConditionCell


# RunConfig.criteria_sha256 픽스처 값 - 픽스처일 뿐이며 규칙과 무관하다
FIXTURE_CRITERIA_SHA256 = "0" * 64


class BuildConditionCellStatesTest(unittest.TestCase):
  def test_builds_full_cross_product(self) -> None:
    with tempfile.TemporaryDirectory() as VaultDir:
      States = run_pilot.build_condition_cell_states(
        Conditions=["B0", "제안"],
        Modes=["all_layers", "split_by_layer"],
        Ks=[4, 8],
        VaultDir=VaultDir,
        ModelId="fake-model",
        Threads=2,
        CriteriaSha256=FIXTURE_CRITERIA_SHA256,
        LabelsSha256=None,
      )

      self.assertEqual(len(States), 2 * 2 * 2)
      SomeCell = ConditionCell(condition=Condition.PROPOSAL, mode="split_by_layer", k=8)
      self.assertIn(SomeCell, States)
      self.assertEqual(States[SomeCell].vault.size(), 0)
      self.assertEqual(States[SomeCell].run_config.model_id, "fake-model")
      self.assertEqual(States[SomeCell].run_config.threads, 2)


class MainSmokeTest(unittest.TestCase):
  def test_end_to_end_with_fake_client(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      DocsPath = os.path.join(TempDir, "docs.jsonl")
      with open(DocsPath, "w", encoding="utf-8") as File:
        # source_layer 값은 테스트 픽스처일 뿐이며 출처 층 부여 규칙과 무관하다
        for Index in range(2):
          File.write(
            json.dumps({"id": f"d{Index}", "title": f"제목{Index}", "body": f"본문{Index}", "source_layer": "개인"})
            + "\n"
          )

      VaultDir = os.path.join(TempDir, "vault")
      LogPath = os.path.join(TempDir, "logs", "verdict_log.jsonl")
      # 라벨링 기준 v1 파일 경로 - 픽스처일 뿐이며 규칙과 무관하다
      CriteriaPath = os.path.join(TempDir, "criteria.md")
      with open(CriteriaPath, "w", encoding="utf-8") as File:
        File.write("픽스처 기준 텍스트")

      OldArgv = sys.argv
      sys.argv = [
        "run_pilot.py",
        "--docs", DocsPath,
        "--model-id", "fake-model",
        "--threads", "2",
        "--cold-start-threshold-seconds", "999",
        "--vault-dir", VaultDir,
        "--log-path", LogPath,
        "--conditions", "B0,B1",
        "--modes", "all_layers,split_by_layer",
        "--ks", "4",
        "--schedule-seed", "1",  # 값은 테스트 픽스처일 뿐이다
        "--client", "fake",
        "--criteria-path", CriteriaPath,
        "--no-labels",
      ]
      try:
        # run_pilot 은 실제 임베딩 서버용 백엔드 주입구를 일부러 노출하지 않는다 - 여기서만 patch 로 대체한다
        with patch("retrieval.embeddings._call_llama_server", side_effect=lambda Texts: [[1.0, 0.0] for _ in Texts]):
          run_pilot.main()
      finally:
        sys.argv = OldArgv

      Entries = load_log(LogPath)
      self.assertEqual(len(Entries), 2 * 2 * 2)  # 2 docs x (2 conditions x 2 modes x 1 k)

      ExpectedCriteriaSha256 = hashlib.sha256(open(CriteriaPath, "rb").read()).hexdigest()
      for Entry in Entries:
        Snapshot = Entry["run_config_snapshot"]
        self.assertIn("criteria_sha256", Snapshot)
        self.assertIn("labels_sha256", Snapshot)
        self.assertEqual(Snapshot["criteria_sha256"], ExpectedCriteriaSha256)
        self.assertIsNone(Snapshot["labels_sha256"])


class ParseArgsLabelsMutualExclusionTest(unittest.TestCase):
  # v1 §5 무관 - argparse 인자 배선 확인용 픽스처
  def _base_argv(self) -> list[str]:
    return [
      "run_pilot.py",
      "--docs", "docs.jsonl",
      "--model-id", "fake-model",
      "--threads", "2",
      "--cold-start-threshold-seconds", "999",
      "--vault-dir", "vault",
      "--log-path", "log.jsonl",
      "--schedule-seed", "1",
      "--criteria-path", "criteria.md",
    ]

  def test_neither_labels_path_nor_no_labels_errors(self) -> None:
    OldArgv = sys.argv
    sys.argv = self._base_argv()
    try:
      with self.assertRaises(SystemExit):
        run_pilot.parse_args()
    finally:
      sys.argv = OldArgv

  def test_both_labels_path_and_no_labels_errors(self) -> None:
    OldArgv = sys.argv
    sys.argv = self._base_argv() + ["--labels-path", "labels.jsonl", "--no-labels"]
    try:
      with self.assertRaises(SystemExit):
        run_pilot.parse_args()
    finally:
      sys.argv = OldArgv


if __name__ == "__main__":
  unittest.main()
