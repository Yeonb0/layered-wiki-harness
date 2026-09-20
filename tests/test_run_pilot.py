import json
import os
import tempfile
import unittest
from unittest.mock import patch

import run_pilot
from analysis.aggregate import load_log
from runner.conditions import Condition, ConditionCell


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
        for Index in range(2):
          File.write(json.dumps({"id": f"d{Index}", "title": f"제목{Index}", "body": f"본문{Index}"}) + "\n")

      VaultDir = os.path.join(TempDir, "vault")
      LogPath = os.path.join(TempDir, "logs", "verdict_log.jsonl")

      import sys

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
        "--client", "fake",
      ]
      try:
        # run_pilot 은 실제 임베딩 서버용 백엔드 주입구를 일부러 노출하지 않는다 - 여기서만 patch 로 대체한다
        with patch("retrieval.embeddings._call_llama_server", side_effect=lambda Texts: [[1.0, 0.0] for _ in Texts]):
          run_pilot.main()
      finally:
        sys.argv = OldArgv

      Entries = load_log(LogPath)
      self.assertEqual(len(Entries), 2 * 2 * 2)  # 2 docs x (2 conditions x 2 modes x 1 k)


if __name__ == "__main__":
  unittest.main()
