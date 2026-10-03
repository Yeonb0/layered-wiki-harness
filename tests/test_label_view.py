"""라벨링 뷰 테스트

아래 문서 · 세그먼트 · title 은 전부 합성 픽스처일 뿐이며 규칙과 무관하다
"""
import json
import os
import tempfile
import unittest

from labeling import label_view as lv


def write_jsonl(path, Rows):
  with open(path, "w", encoding="utf-8") as f:
    for r in Rows:
      f.write(json.dumps(r, ensure_ascii=False) + "\n")


def fixture(d):
  seg, spl = os.path.join(d, "seg"), os.path.join(d, "split")
  os.makedirs(seg)
  os.makedirs(spl)
  Docs = [
    {"doc_id": "a", "source": "team_1jo", "title": "회의", "path": "1조/회의록/회의 a.md", "layer": "팀", "group": "1조", "properties": {"날짜": "x"}},
    {"doc_id": "b", "source": "team_soft_eng", "title": None, "path": "소프트웨어 공학/과제/b.md", "layer": "팀", "group": "소공", "properties": {}},
    {"doc_id": "c", "source": "lecture_note", "title": "강의", "path": "L/c.md", "layer": "전사", "group": None, "properties": {}},
  ]
  Segs = [
    {"segment_id": "a#s2", "doc_id": "a", "seq": 2, "text": "둘째"},
    {"segment_id": "a#s1", "doc_id": "a", "seq": 1, "text": "첫째"},
    {"segment_id": "b#s1", "doc_id": "b", "seq": 1, "text": "하나"},
    {"segment_id": "c#s1", "doc_id": "c", "seq": 1, "text": "강의 내용"},
  ]
  write_jsonl(os.path.join(seg, "docs.jsonl"), Docs)
  write_jsonl(os.path.join(seg, "segments.jsonl"), Segs)
  with open(os.path.join(spl, "pilot_doc_ids.txt"), "w", encoding="utf-8") as f:
    f.write("a\nb\nc\n")
  return seg, spl


class TestLabelView(unittest.TestCase):
  def test_excludes_lecture_and_hides_location(self):
    with tempfile.TemporaryDirectory() as d:
      seg, spl = fixture(d)
      Views, Rows, Key = lv.build(seg, spl, "pilot", 1)
    text = "\n".join(Views)
    self.assertNotIn("강의 내용", text)
    for hidden in ("1조/회의록", "소프트웨어 공학", "날짜", "a#s1", "team_1jo", "팀"):
      self.assertNotIn(hidden, text)
    self.assertEqual(len(Rows), 3)
    self.assertIn("( 제목 없음 )", text)

  def test_segments_in_seq_order_and_key_maps(self):
    with tempfile.TemporaryDirectory() as d:
      seg, spl = fixture(d)
      Views, Rows, Key = lv.build(seg, spl, "pilot", 1)
    va = [v for v in Views if "회의" in v][0]
    self.assertLess(va.index("[1]"), va.index("[2]"))
    self.assertEqual({k["segment_id"] for k in Key}, {"a#s1", "a#s2", "b#s1"})

  def test_seed_deterministic(self):
    with tempfile.TemporaryDirectory() as d:
      seg, spl = fixture(d)
      self.assertEqual(lv.build(seg, spl, "pilot", 5), lv.build(seg, spl, "pilot", 5))

  def test_missing_doc_raises(self):
    with tempfile.TemporaryDirectory() as d:
      seg, spl = fixture(d)
      with open(os.path.join(spl, "pilot_doc_ids.txt"), "a", encoding="utf-8") as f:
        f.write("zzz\n")
      with self.assertRaises(ValueError):
        lv.build(seg, spl, "pilot", 1)


if __name__ == "__main__":
  unittest.main()
