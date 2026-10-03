"""세그먼트 · 제외 규칙 v1 테스트

아래 문서 · 이름 · 속성 값은 전부 합성 픽스처일 뿐이며 규칙과 무관하다
"""
import collections
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile

from segmentation import segment as sg

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32
ID_E = "e" * 32
ID_X = "f" * 32


def lines(text):
  return list(enumerate(text.splitlines(), 1))


def texts(Segs):
  return ["\n".join(t for _, t in s) for s in Segs]


class TestBoundaries(unittest.TestCase):
  def test_h1_h2_h3_are_boundaries_h4_is_not(self):
    Body = lines("intro\n# A\na\n## B\nb\n### C\nc\n#### D\nd")
    self.assertEqual(texts(sg.split_segments(Body)), ["intro", "# A\na", "## B\nb", "### C\nc\n#### D\nd"])

  def test_heading_inside_code_fence_is_not_boundary(self):
    Body = lines("### A\n```\n# comment\n```\nx")
    self.assertEqual(len(sg.split_segments(Body)), 1)

  def test_indented_heading_is_not_boundary(self):
    Body = lines("### A\n    ### inner\nx")
    self.assertEqual(len(sg.split_segments(Body)), 1)

  def test_no_heading_doc_is_one_segment(self):
    Body = lines("a\n\nb\n- c")
    self.assertEqual(texts(sg.split_segments(Body)), ["a\n\nb\n- c"])

  def test_heading_only_merges_forward_and_last_merges_backward(self):
    Body = lines("## P\n\n### A\na\n## Q")
    self.assertEqual(texts(sg.split_segments(Body)), ["## P\n### A\na\n## Q"])

  def test_trim_and_line_numbers(self):
    Body = lines("\n\n### A\na\n\n")
    Segs = sg.split_segments(Body)
    self.assertEqual((Segs[0][0][0], Segs[0][-1][0]), (3, 4))


class TestPreprocess(unittest.TestCase):
  def test_title_and_properties_only_with_db_keys(self):
    Body, title, Props = sg.split_title_and_properties(lines("# T\n\n과목: X (url)\n선택: Y\n\nbody\n과목: not prop"), ["과목", "선택"])
    self.assertEqual(title, "T")
    self.assertEqual(Props, {"과목": "X (url)", "선택": "Y"})
    self.assertEqual([t for _, t in Body if t.strip()], ["body", "과목: not prop"])

  def test_no_db_keys_keeps_property_like_line(self):
    Body, title, Props = sg.split_title_and_properties(lines("# T\n날짜: 1"), None)
    self.assertEqual(Props, {})
    self.assertEqual([t for _, t in Body], ["날짜: 1"])

  def test_decorations(self):
    Stats = collections.Counter()
    raw = "![" + sg.BANNER_ALT + "](x.png)\n\n- Index\n\n### A\n- Index\na\n\n---\n\n- 자주 사용하는 특수 문자\n    ∞\n    ex) Example"
    Body = sg.strip_decorations(lines(raw), Stats)
    self.assertEqual([t for _, t in Body if t.strip()], ["### A", "- Index", "a"])
    self.assertEqual((Stats["banner"], Stats["index"], Stats["footer"], Stats["footer_trailing_content"]), (1, 1, 1, 0))

  def test_footer_trailing_content_is_counted_and_kept(self):
    Stats = collections.Counter()
    Body = sg.strip_decorations(lines("### A\n---\n- 자주 사용하는 특수 문자\n    ∞\nafter"), Stats)
    self.assertEqual([t for _, t in Body], ["### A", "after"])
    self.assertEqual(Stats["footer_trailing_content"], 1)

  def test_plain_rule_is_kept(self):
    Stats = collections.Counter()
    Body = sg.strip_decorations(lines("a\n---\nb"), Stats)
    self.assertEqual([t for _, t in Body], ["a", "---", "b"])


class TestDocLevel(unittest.TestCase):
  def test_doc_id(self):
    self.assertEqual(sg.doc_id_for(f"x/y {ID_A}.md"), ID_A)
    self.assertTrue(sg.doc_id_for("x/ATTACH.md").startswith("att-"))

  def test_exclusions(self):
    self.assertEqual(sg.doc_exclusion("lecture_note", f"L/p {ID_X}.md", ID_X, {ID_X}), "E1_탐색표본")
    self.assertEqual(sg.doc_exclusion("team_1jo", f"1조/TODOs/t {ID_A}.md", ID_A, set()), "E2_TODOs")
    self.assertEqual(sg.doc_exclusion("team_soft_eng", f"소프트웨어 공학 {ID_A}.md", ID_A, set()), "E3_소공범위밖")
    self.assertIsNone(sg.doc_exclusion("team_soft_eng", "소프트웨어 공학/00_공용_기준문서.md", "att-0", set()))
    self.assertIsNone(sg.doc_exclusion("team_soft_eng", f"소프트웨어 공학/과제/p {ID_A}.md", ID_A, set()))

  def test_source_layer(self):
    Owners = {"갑"}
    self.assertEqual(sg.source_layer("team_1jo", f"1조/갑 {ID_A}.md", Owners), ("개인", "갑"))
    self.assertEqual(sg.source_layer("team_1jo", f"1조/갑/p {ID_B}.md", Owners), ("개인", "갑"))
    self.assertEqual(sg.source_layer("team_1jo", f"1조/회의록/p {ID_B}.md", Owners), ("팀", "1조"))
    self.assertEqual(sg.source_layer("team_soft_eng", "소프트웨어 공학/과제/p.md", Owners), ("팀", "소공"))
    self.assertEqual(sg.source_layer("lecture_note", "L/p.md", Owners), ("전사", None))
    with self.assertRaises(ValueError):
      sg.source_layer("unknown", "p.md", Owners)


def write_json(path, obj):
  with open(path, "w", encoding="utf-8") as f:
    json.dump(obj, f, ensure_ascii=False)


def read_jsonl(path):
  with open(path, encoding="utf-8") as f:
    return [json.loads(l) for l in f]


def make_corpus(root, Files, tamper=False):
  os.makedirs(os.path.join(root, "snapshot1", "raw"))
  os.makedirs(os.path.join(root, "selection"))
  Mf = []
  for source, name, Members in Files:
    p = os.path.join(root, "snapshot1", "raw", name)
    with zipfile.ZipFile(p, "w") as zf:
      for n, data in Members.items():
        zf.writestr(n, data)
    with open(p, "rb") as f:
      digest = hashlib.sha256(f.read()).hexdigest()
    Mf.append({"source": source, "path": "raw/" + name, "sha256": "0" * 64 if tamper else digest})
  write_json(os.path.join(root, "snapshot1", "manifest.json"), {"snapshot": 1, "files": Mf})
  write_json(os.path.join(root, "selection", "lecture_subjects.json"), {"excluded_pages": {"ids": [ID_X]}})
  write_json(os.path.join(root, "selection", "source_layers.json"), {"team_1jo_personal_owners": ["갑"]})


FILES = [
  ("lecture_note", "lec.zip", {
    f"L {ID_C}_all.csv": "이름,과목,선택\nx,y,z\n",
    f"L/강의 {ID_C}.md": "# 강의\n\n과목: S (u)\n\n![" + sg.BANNER_ALT + "](b.png)\n\n- Index\n\n## ✦ P\n\n### ◆ A\na\n\n### ◆ B\nb\n\n---\n\n- 자주 사용하는 특수 문자\n    ∞",
    f"L/표본 {ID_X}.md": "# 표본\n\n### ◆ A\na",
  }),
  ("team_1jo", "jo.zip", {
    f"1조/갑 {ID_A}.md": "# 갑\n\n[하위](x)",
    f"1조/갑/생각 {ID_B}.md": "# 생각\n아이디어 한 줄",
    f"1조/TODOs/할일 {ID_D}.md": "# 할일\n하기",
    f"1조/모음/제목 없음 {ID_E}_all.csv": "Name,Files & media\nx,y\n",
    f"1조/모음/제목 없음/소 {ID_E}.md": "# 소\n\nFiles & media: so.png",
    "1조/회의록/8차/Q.md": "# Q\n\n## 하나\n1\n## 둘\n2",
  }),
]


class TestRun(unittest.TestCase):
  def test_end_to_end(self):
    with tempfile.TemporaryDirectory() as d:
      root = os.path.join(d, "corpus")
      make_corpus(root, FILES)
      Report = sg.run(root, os.path.join(d, "out"))
      Segs = read_jsonl(os.path.join(d, "out", "segments.jsonl"))
      Exc = {e["path"]: e["reason"] for e in read_jsonl(os.path.join(d, "out", "excluded.jsonl"))}
      Docs = {r["doc_id"]: r for r in read_jsonl(os.path.join(d, "out", "docs.jsonl"))}
    Lec = [s for s in Segs if s["doc_id"] == ID_C]
    self.assertEqual([s["text"] for s in Lec], ["## ✦ P\n### ◆ A\na", "### ◆ B\nb"])
    self.assertEqual([s["segment_id"] for s in Lec], [f"{ID_C}#s1", f"{ID_C}#s2"])
    self.assertEqual(Docs[ID_C]["properties"], {"과목": "S (u)"})
    self.assertEqual(Exc[f"L/표본 {ID_X}.md"], "E1_탐색표본")
    self.assertEqual(Exc[f"1조/TODOs/할일 {ID_D}.md"], "E2_TODOs")
    self.assertEqual(Exc[f"1조/모음/제목 없음/소 {ID_E}.md"], "E4_빈문서")
    self.assertEqual(Docs[ID_A]["layer"], "개인")
    self.assertEqual(Docs[ID_B]["group"], "갑")
    att = [d for d in Docs.values() if d["path"] == "1조/회의록/8차/Q.md"][0]
    self.assertEqual((att["layer"], att["group"], att["n_segments"]), ("팀", "1조", 2))
    self.assertTrue(att["doc_id"].startswith("att-"))
    self.assertEqual(Report["e1_matched"], 1)
    self.assertEqual(Report["decoration_by_source"]["lecture_note"], {"banner": 1, "index": 1, "footer": 1})

  def test_zip_hash_mismatch_raises(self):
    with tempfile.TemporaryDirectory() as d:
      root = os.path.join(d, "corpus")
      make_corpus(root, FILES, tamper=True)
      with self.assertRaises(ValueError):
        sg.run(root, os.path.join(d, "out"))

  def test_empty_owner_list_raises(self):
    with tempfile.TemporaryDirectory() as d:
      root = os.path.join(d, "corpus")
      make_corpus(root, FILES)
      write_json(os.path.join(root, "selection", "source_layers.json"), {"team_1jo_personal_owners": []})
      with self.assertRaises(ValueError):
        sg.run(root, os.path.join(d, "out"))


if __name__ == "__main__":
  unittest.main()
