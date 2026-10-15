"""라벨 TSV 변환 테스트

아래 TSV · key · 기준 파일은 전부 합성 픽스처일 뿐이며 규칙과 무관하다
"""
import hashlib
import json
import os
import tempfile
import unittest

from labeling import convert_labels as cl

# 합성 픽스처일 뿐이며 규칙과 무관하다
CRITERIA_TEXT = "합성 기준 본문\n"
GOOD_ROWS = [
  ["D01", "1", "개인", "P1", "", "3", "합성 근거 하나"],
  ["D01", "2", "팀", "T1", "T3,BB2", "3", "합성 근거 둘"],
  ["D02", "1", "전사", "D0", "", "1", "합성 근거 셋"],
]
GOOD_KEY = [
  {"doc": "D01", "n": 1, "doc_id": "x", "segment_id": "x#s1", "view_sha256": "a" * 64},
  {"doc": "D01", "n": 2, "doc_id": "x", "segment_id": "x#s2", "view_sha256": "a" * 64},
  {"doc": "D02", "n": 1, "doc_id": "y", "segment_id": "y#s1", "view_sha256": "b" * 64},
]


def make(d, Rows=GOOD_ROWS, Header=cl.TSV_HEADER, Key=GOOD_KEY):
  Tsv, KeyPath, Crit = (os.path.join(d, n) for n in ("labels.tsv", "key.jsonl", "criteria.md"))
  with open(Tsv, "w", encoding="utf-8", newline="") as f:
    f.write("".join("\t".join(r) + "\n" for r in [Header] + Rows))
  with open(KeyPath, "w", encoding="utf-8") as f:
    f.write("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in Key))
  with open(Crit, "w", encoding="utf-8") as f:
    f.write(CRITERIA_TEXT)
  return {
    "tsv_path": Tsv, "key_path": KeyPath, "criteria_path": Crit,
    "criteria_sha256": hashlib.sha256(CRITERIA_TEXT.encode("utf-8")).hexdigest(),
    "labeler": "합성라벨러", "round_no": 1, "labeled_at": "2026-10-15T09:00:00+09:00", "labeled_at_rows": [],
    "out_path": os.path.join(d, "labels.jsonl"), "meta_out_path": os.path.join(d, "meta.json"),
  }


def read_out(Kw):
  with open(Kw["out_path"], encoding="utf-8") as f:
    return [json.loads(l) for l in f]


class TestConvertLabels(unittest.TestCase):
  def test_converts_in_key_order_with_field_order(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Key=list(reversed(GOOD_KEY)))
      Meta = cl.convert(**Kw)
      Out = read_out(Kw)
      with open(Kw["meta_out_path"], encoding="utf-8") as f:
        MetaFile = json.load(f)
    self.assertEqual([r["segment_id"] for r in Out], ["y#s1", "x#s2", "x#s1"])
    self.assertEqual(
      list(Out[0]),
      ["segment_id", "view_sha256", "intrinsic_layer", "applied_clause", "also_hit", "default_applied",
       "rationale", "confidence", "boundary_note", "labeler", "round", "labeled_at", "criteria_sha256"],
    )
    self.assertEqual(Out[0]["view_sha256"], "b" * 64)
    self.assertTrue(Out[0]["default_applied"])
    self.assertEqual(Out[1]["also_hit"], ["T3", "BB2"])
    self.assertFalse(Out[1]["default_applied"])
    self.assertEqual(Out[2]["also_hit"], [])
    self.assertIs(type(Out[2]["confidence"]), int)
    self.assertIsNone(Out[2]["boundary_note"])
    self.assertEqual(Out[2]["labeler"], "합성라벨러")
    self.assertEqual(Out[2]["round"], 1)
    self.assertEqual(Out[2]["criteria_sha256"], Kw["criteria_sha256"])
    self.assertEqual(Meta, MetaFile)
    self.assertEqual(
      list(Meta), ["tsv_sha256", "key_sha256", "criteria_sha256", "rows", "labeler", "round", "script"]
    )
    self.assertEqual(Meta["rows"], 3)
    self.assertEqual(Meta["script"], "labeling/convert_labels.py")

  def test_labeled_at_row_overrides_only_that_row(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      Kw["labeled_at_rows"] = ["D01-2=2026-10-16T10:00:00+09:00"]
      cl.convert(**Kw)
      Out = read_out(Kw)
    self.assertEqual([r["labeled_at"] for r in Out], ["2026-10-15T09:00:00+09:00", "2026-10-16T10:00:00+09:00", "2026-10-15T09:00:00+09:00"])

  def test_header_mismatch_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Header=["doc", "n", "layer", "clause", "also_hit", "confidence", "memo"])
      with self.assertRaisesRegex(ValueError, "헤더"):
        cl.convert(**Kw)

  def test_row_not_in_key_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=GOOD_ROWS + [["D03", "1", "개인", "P2", "", "3", "합성 근거 넷"]])
      with self.assertRaisesRegex(ValueError, "key 에 없는"):
        cl.convert(**Kw)

  def test_key_row_missing_in_tsv_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=GOOD_ROWS[:2])
      with self.assertRaisesRegex(ValueError, "TSV 에 없는"):
        cl.convert(**Kw)

  def test_duplicate_row_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=GOOD_ROWS + [GOOD_ROWS[0]])
      with self.assertRaisesRegex(ValueError, "중복"):
        cl.convert(**Kw)

  def test_clause_layer_mismatch_raises(self):
    for Row in (["D01", "1", "팀", "P1", "", "3", "합성"], ["D01", "1", "개인", "T1", "", "3", "합성"], ["D01", "1", "팀", "D0", "", "1", "합성"]):
      with self.subTest(Row=Row):
        with tempfile.TemporaryDirectory() as d:
          Kw = make(d, Rows=[Row] + GOOD_ROWS[1:])
          with self.assertRaisesRegex(ValueError, "맞지 않는다"):
            cl.convert(**Kw)

  def test_d0_with_confidence_2_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=GOOD_ROWS[:2] + [["D02", "1", "전사", "D0", "", "2", "합성"]])
      with self.assertRaisesRegex(ValueError, "D0"):
        cl.convert(**Kw)

  def test_also_hit_same_as_clause_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=[["D01", "1", "개인", "P1", "P1", "3", "합성"]] + GOOD_ROWS[1:])
      with self.assertRaisesRegex(ValueError, "clause 와 같은"):
        cl.convert(**Kw)

  def test_also_hit_duplicate_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=[["D01", "1", "개인", "P1", "T3,T3", "3", "합성"]] + GOOD_ROWS[1:])
      with self.assertRaisesRegex(ValueError, "중복"):
        cl.convert(**Kw)

  def test_criteria_hash_mismatch_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      Kw["criteria_sha256"] = "0" * 64
      with self.assertRaisesRegex(ValueError, "sha256"):
        cl.convert(**Kw)

  def test_time_without_offset_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      Kw["labeled_at"] = "2026-10-15T09:00:00"
      with self.assertRaisesRegex(ValueError, "오프셋"):
        cl.convert(**Kw)

  def test_row_time_without_offset_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      Kw["labeled_at_rows"] = ["D01-1=2026-10-15T09:00:00"]
      with self.assertRaisesRegex(ValueError, "오프셋"):
        cl.convert(**Kw)

  def test_row_time_key_not_in_tsv_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      Kw["labeled_at_rows"] = ["D09-1=2026-10-15T09:00:00+09:00"]
      with self.assertRaisesRegex(ValueError, "TSV 에 없다"):
        cl.convert(**Kw)

  def test_existing_output_raises_and_is_untouched(self):
    for Target in ("out_path", "meta_out_path"):
      with self.subTest(Target=Target):
        with tempfile.TemporaryDirectory() as d:
          Kw = make(d)
          with open(Kw[Target], "w", encoding="utf-8") as f:
            f.write("기존")
          with self.assertRaisesRegex(ValueError, "이미 있다"):
            cl.convert(**Kw)
          with open(Kw[Target], encoding="utf-8") as f:
            self.assertEqual(f.read(), "기존")

  def test_empty_labeler_and_round_zero_raise(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      Kw["labeler"] = " "
      with self.assertRaisesRegex(ValueError, "labeler"):
        cl.convert(**Kw)
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      Kw["round_no"] = 0
      with self.assertRaisesRegex(ValueError, "round"):
        cl.convert(**Kw)

  def test_bom_and_cr_raise(self):
    for Bad in ("﻿", "\r"):
      with self.subTest(Bad=repr(Bad)):
        with tempfile.TemporaryDirectory() as d:
          Kw = make(d)
          with open(Kw["tsv_path"], "r", encoding="utf-8", newline="") as f:
            Text = f.read()
          Text = Bad + Text if Bad == "﻿" else Text.replace("\n", "\r\n")
          with open(Kw["tsv_path"], "w", encoding="utf-8", newline="") as f:
            f.write(Text)
          with self.assertRaises(ValueError):
            cl.convert(**Kw)

  def test_short_row_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=[["D01", "1", "개인", "P1", "", "3"]] + GOOD_ROWS[1:])
      with self.assertRaisesRegex(ValueError, "7 칸"):
        cl.convert(**Kw)

  def test_empty_rationale_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Rows=[["D01", "1", "개인", "P1", "", "3", " "]] + GOOD_ROWS[1:])
      with self.assertRaisesRegex(ValueError, "rationale"):
        cl.convert(**Kw)


if __name__ == "__main__":
  unittest.main()
