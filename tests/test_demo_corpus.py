import collections
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import demo_corpus.build_snapshot as B
from labeling.gold import read_membership
from runner.v2_sequential import load_source_docs
from segmentation.segment import run

# 합성 시연 코퍼스 ( 스냅샷 900 ) 는 시연 경로 전용이며 실험 코퍼스 · 정답셋 · 평가 결과와 섞지 않는다 ( 사용자 결정 2026-10-22 )
# 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다


def _read_jsonl(Path) -> list:
  with open(Path, encoding="utf-8") as File:
    return [json.loads(Line) for Line in File if Line.strip()]


def _file_bytes(Root) -> dict:
  Out = {}
  for Dir, _, Names in os.walk(Root):
    for Name in Names:
      Path = os.path.join(Dir, Name)
      with open(Path, "rb") as File:
        Out[os.path.relpath(Path, Root)] = File.read()
  return Out


class BuiltCorpusTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.Tmp = tempfile.TemporaryDirectory()
    cls.Root = os.path.join(cls.Tmp.name, "corpus")
    cls.Manifest = B.build(cls.Root)
    cls.Seg = os.path.join(cls.Tmp.name, "seg")
    run(cls.Root, cls.Seg)
    cls.Docs = _read_jsonl(os.path.join(cls.Seg, "docs.jsonl"))
    cls.Segs = _read_jsonl(os.path.join(cls.Seg, "segments.jsonl"))

  @classmethod
  def tearDownClass(cls) -> None:
    cls.Tmp.cleanup()

  def test_two_builds_are_byte_identical(self) -> None:
    with tempfile.TemporaryDirectory() as Dir:
      Second = os.path.join(Dir, "again")
      Manifest = B.build(Second)
      self.assertEqual(Manifest, self.Manifest)
      self.assertEqual(_file_bytes(Second), _file_bytes(self.Root))

  def test_manifest_shape(self) -> None:
    self.assertEqual(self.Manifest["snapshot"], 900)
    self.assertEqual([F["source"] for F in self.Manifest["files"]], ["demo_studio", "demo_team1", "demo_team2"])
    for F in self.Manifest["files"]:
      self.assertEqual(F["path"], f"raw/{F['source']}.zip")

  def test_segment_rules_keep_all_twenty_docs(self) -> None:
    self.assertEqual(len(self.Docs), 20)
    self.assertEqual(_read_jsonl(os.path.join(self.Seg, "excluded.jsonl")), [])
    Counts = collections.Counter(S["doc_id"] for S in self.Segs)
    for Doc in self.Docs:
      self.assertGreaterEqual(Counts[Doc["doc_id"]], 1, Doc["path"])

  def test_layer_group_team_counts_are_exact(self) -> None:
    # 개인 폴더 이름 오타가 조용히 팀 문서가 되는 경우를 잡는 검사다 - 집계가 한 칸이라도 다르면 실패한다
    Counted = collections.Counter((D["layer"], D["group"], D.get("team")) for D in self.Docs)
    Expected = {
      ("전사", None, None): 4,
      ("팀", "팀1", None): 4,
      ("팀", "팀2", None): 4,
      ("개인", "팀원A", "팀1"): 1,
      ("개인", "팀원B", "팀1"): 1,
      ("개인", "팀원C", "팀2"): 1,
      ("개인", "팀원D", "팀2"): 1,
      ("개인", "팀원E", "팀1"): 1,
      ("개인", "팀원E", "팀2"): 1,
      ("개인", "팀원F", "팀1"): 1,
      ("개인", "팀원F", "팀2"): 1,
    }
    self.assertEqual(dict(Counted), Expected)

  def test_team_and_enterprise_rows_have_no_team_key(self) -> None:
    for Row in self.Docs + self.Segs:
      if Row["layer"] != "개인":
        self.assertNotIn("team", Row)
      else:
        self.assertIn("team", Row)

  def test_runner_loads_twenty_docs_with_source_team_on_personal_only(self) -> None:
    Docs, _ = load_source_docs(
      os.path.join(self.Seg, "segments.jsonl"), os.path.join(self.Seg, "docs.jsonl"),
      os.path.join(self.Root, "doc_ids.txt"), os.path.join(self.Root, "split_doc_ids.txt"),
      os.path.join(self.Root, "selection", "lecture_subjects.json"),
    )
    self.assertEqual(len(Docs), 20)
    for Doc in Docs:
      if Doc.source_layer == "개인":
        self.assertIsNotNone(Doc.source_team)
      else:
        self.assertIsNone(Doc.source_team)

  def test_membership_has_six_owners_and_two_in_both_teams(self) -> None:
    Membership = read_membership(os.path.join(self.Root, "selection", "source_layers.json"))
    self.assertEqual(sorted(Membership.teams_by_owner), [f"팀원{C}" for C in "ABCDEF"])
    Both = sorted(O for O, Teams in Membership.teams_by_owner.items() if len(Teams) == 2)
    self.assertEqual(Both, ["팀원E", "팀원F"])
    self.assertIsNone(Membership.legacy_team)

  def test_doc_id_lists_are_the_same_and_sorted(self) -> None:
    with open(os.path.join(self.Root, "doc_ids.txt"), encoding="utf-8") as F1, open(os.path.join(self.Root, "split_doc_ids.txt"), encoding="utf-8") as F2:
      A, B_ = F1.read(), F2.read()
    self.assertEqual(A, B_)
    Ids = A.split()
    self.assertEqual(Ids, sorted(Ids))
    self.assertEqual(len(Ids), 20)


class BuildErrorTest(unittest.TestCase):
  def setUp(self) -> None:
    self.Tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.Tmp.cleanup)
    # 실제 demo_corpus/ 를 건드리지 않도록 복사본을 만들어 CORPUS_DIR 을 바꿔 쓴다
    self.Corpus = os.path.join(self.Tmp.name, "demo_copy")
    shutil.copytree(B.CORPUS_DIR, self.Corpus, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    Patch = mock.patch.object(B, "CORPUS_DIR", self.Corpus)
    Patch.start()
    self.addCleanup(Patch.stop)
    self.Out = os.path.join(self.Tmp.name, "out")

  def test_existing_out_root_raises_value_error(self) -> None:
    os.makedirs(self.Out)
    with self.assertRaises(ValueError):
      B.build(self.Out)

  def test_folder_not_in_sources_raises_value_error(self) -> None:
    os.makedirs(os.path.join(self.Corpus, "pages", "demo_extra"))
    with self.assertRaises(ValueError):
      B.build(self.Out)
    self.assertFalse(os.path.exists(self.Out))

  def test_missing_or_empty_source_folder_raises_value_error(self) -> None:
    shutil.rmtree(os.path.join(self.Corpus, "pages", "demo_team2"))
    with self.assertRaises(ValueError):
      B.build(self.Out)
    os.makedirs(os.path.join(self.Corpus, "pages", "demo_team2"))
    with self.assertRaises(ValueError):
      B.build(self.Out)
    self.assertFalse(os.path.exists(self.Out))

  def test_duplicate_doc_id_raises_value_error(self) -> None:
    Source = os.path.join(self.Corpus, "pages", "demo_team1", "전투팀", "복제 90000000000000000000000000000013.md")
    with open(Source, "w", encoding="utf-8") as File:
      File.write("# 복제\n\n합성 본문")
    with self.assertRaises(ValueError):
      B.build(self.Out)


if __name__ == "__main__":
  unittest.main()
