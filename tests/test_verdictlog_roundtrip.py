import os
import tempfile
import unittest

from analysis.aggregate import load_log
from retrieval.types import Candidate
from runner.conditions import Condition
from vault.types import DownwardConditionalLink
from verdictlog.types import Verdict, VerdictLogEntry
from verdictlog.writer import VerdictLogWriter


class VerdictLogRoundtripTest(unittest.TestCase):
  def test_write_then_read_back(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      LogPath = os.path.join(TempDir, "verdict_log.jsonl")
      Writer = VerdictLogWriter(LogPath)
      Entry = VerdictLogEntry(
        entry_id="entry-1",
        wall_clock="2026-09-20T00:00:00+00:00",
        run_index=0,
        doc_id="doc-1",
        doc_title="제목",
        doc_body="본문",
        condition=Condition.B0,
        mode="split_by_layer",
        k=4,
        vault_size=3,
        retrieved_candidates=[Candidate(id="c1", layer="개인", title="후보", excerpt="발췌")],
        ok=True,
        errors=[],
        raw_verdict={"layer": "개인"},
        verdict=Verdict(
          layer="개인",
          upward_links=["doc-0"],
          downward_conditional_links=[DownwardConditionalLink(target_id="doc-2", visibility_condition="팀 이상")],
          rationale="테스트 근거",
        ),
        validation_problems=[],
        selection_rationale="테스트 근거",
        model_raw_output="raw output",
        cold_start=False,
        retried=True,
        processing_time_seconds=1.23,
        run_config_snapshot={"condition": "B0", "mode": "split_by_layer", "k": 4, "model_id": "qwen3-8b-q4_k_m"},
      )

      Writer.append(Entry)
      Loaded = load_log(LogPath)

      self.assertEqual(len(Loaded), 1)
      RoundTripped = Loaded[0]
      self.assertEqual(RoundTripped["entry_id"], "entry-1")
      self.assertEqual(RoundTripped["condition"], "B0")
      self.assertEqual(RoundTripped["retrieved_candidates"][0]["excerpt"], "발췌")
      self.assertEqual(RoundTripped["verdict"]["downward_conditional_links"][0]["visibility_condition"], "팀 이상")
      self.assertTrue(RoundTripped["retried"])
      self.assertFalse(RoundTripped["cold_start"])


if __name__ == "__main__":
  unittest.main()
