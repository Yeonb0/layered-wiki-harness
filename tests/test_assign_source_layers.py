import json
import os
import random
import tempfile
import unicodedata
import unittest
from unittest import mock

from labeling.assign_source_layers import SEED, assign_source_layers

# 이 파일의 모든 id · exclusions 값은 픽스처일 뿐이며 규칙과 무관하다


def _write_lines(path: str, lines: list[str]) -> None:
  with open(path, "w", encoding="utf-8") as File:
    for Line in lines:
      File.write(Line)
      File.write("\n")


def _write_jsonl(path: str, records: list[dict]) -> None:
  with open(path, "w", encoding="utf-8") as File:
    for Record in records:
      File.write(json.dumps(Record, ensure_ascii=False))
      File.write("\n")


def _read_records(path: str) -> list[dict]:
  Records = []
  with open(path, "r", encoding="utf-8") as File:
    for Line in File:
      Line = Line.strip()
      if Line:
        Records.append(json.loads(Line))
  return Records


class AssignSourceLayersTest(unittest.TestCase):
  def test_same_input_twice_produces_byte_identical_output(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_lines(IdsPath, [f"a{Index}/doc{Index}.md" for Index in range(6)])
      _write_jsonl(ExclusionsPath, [])

      Out1 = os.path.join(TempDir, "out1.jsonl")
      Out2 = os.path.join(TempDir, "out2.jsonl")
      assign_source_layers(IdsPath, ExclusionsPath, "pilot", Out1)
      assign_source_layers(IdsPath, ExclusionsPath, "pilot", Out2)

      with open(Out1, "rb") as File:
        Bytes1 = File.read()
      with open(Out2, "rb") as File:
        Bytes2 = File.read()
      self.assertEqual(Bytes1, Bytes2)

  def test_input_order_does_not_change_assignment(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      Ids = [f"a{Index}/doc{Index}.md" for Index in range(6)]
      IdsPathA = os.path.join(TempDir, "ids_a.txt")
      IdsPathB = os.path.join(TempDir, "ids_b.txt")
      _write_lines(IdsPathA, Ids)
      _write_lines(IdsPathB, list(reversed(Ids)))
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])

      OutA = os.path.join(TempDir, "out_a.jsonl")
      OutB = os.path.join(TempDir, "out_b.jsonl")
      assign_source_layers(IdsPathA, ExclusionsPath, "pilot", OutA)
      assign_source_layers(IdsPathB, ExclusionsPath, "pilot", OutB)

      AssignmentA = {R["doc_id"]: R["source_layer"] for R in _read_records(OutA)}
      AssignmentB = {R["doc_id"]: R["source_layer"] for R in _read_records(OutB)}
      self.assertEqual(AssignmentA, AssignmentB)

  def test_layer_counts_within_stratum_differ_by_at_most_one(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      Ids = []
      for FolderIndex, Size in enumerate([5, 7, 10]):
        for DocIndex in range(Size):
          Ids.append(f"f{FolderIndex}/doc{DocIndex}.md")
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, Ids)
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)
      Records = _read_records(OutPath)

      ByStratum: dict[str, dict[str, int]] = {}
      for Record in Records:
        Counts = ByStratum.setdefault(Record["stratum"], {})
        Counts[Record["source_layer"]] = Counts.get(Record["source_layer"], 0) + 1

      for Stratum, Counts in ByStratum.items():
        with self.subTest(stratum=Stratum):
          Values = list(Counts.values())
          self.assertLessEqual(max(Values) - min(Values), 1)

  def test_start_layer_cycles_by_stratum_ordinal(self) -> None:
    # 폴더 4개, 각 4건 (3 의 배수 아님) - 나머지 1건이 시작 층에만 더 붙는다
    with tempfile.TemporaryDirectory() as TempDir:
      Ids = []
      for FolderIndex in range(4):
        for DocIndex in range(4):
          Ids.append(f"a{FolderIndex}/doc{DocIndex}.md")
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, Ids)
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)
      Records = _read_records(OutPath)

      ByStratum: dict[str, dict[str, int]] = {}
      for Record in Records:
        Counts = ByStratum.setdefault(Record["stratum"], {})
        Counts[Record["source_layer"]] = Counts.get(Record["source_layer"], 0) + 1

      ExpectedStartLayer = {
        "a0": "개인",
        "a1": "팀",
        "a2": "전사",
        "a3": "개인",
      }
      for Stratum, ExpectedLayer in ExpectedStartLayer.items():
        with self.subTest(stratum=Stratum):
          Counts = ByStratum[Stratum]
          ExtraLayers = [Layer for Layer, Count in Counts.items() if Count == 2]
          self.assertEqual(ExtraLayers, [ExpectedLayer])

  def test_missing_exclusions_raises(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, ["a0/doc0.md"])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      OutPath = os.path.join(TempDir, "out.jsonl")

      with self.assertRaises(ValueError):
        assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)

  def test_exclusions_only_apply_to_matching_split(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, ["a0/doc0.md", "a0/doc1.md"])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(
        ExclusionsPath,
        [
          {"split": "main", "doc_id": "a0/doc0.md"},
          {"split": "pilot", "doc_id": "a0/doc1.md"},
        ],
      )
      OutPath = os.path.join(TempDir, "out.jsonl")

      assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)
      DocIds = {R["doc_id"] for R in _read_records(OutPath)}
      self.assertEqual(DocIds, {"a0/doc0.md"})

  def test_existing_output_raises_and_leaves_file_unchanged(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, ["a0/doc0.md"])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")
      with open(OutPath, "w", encoding="utf-8") as File:
        File.write("기존 내용\n")

      with self.assertRaises(ValueError):
        assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)

      with open(OutPath, "r", encoding="utf-8") as File:
        self.assertEqual(File.read(), "기존 내용\n")

  def test_nfc_nfd_collision_raises(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      NfcId = "a0/가.md"
      NfdId = unicodedata.normalize("NFD", "a0/가.md")
      self.assertNotEqual(NfcId, NfdId)
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, [NfcId, NfdId])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      with self.assertRaises(ValueError):
        assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)

  def test_hangul_filenames_differing_only_in_content_stay_distinct(self) -> None:
    # glibc 로케일 정렬에서 한글이 같게 비교되던 문제의 회귀 테스트
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, ["프로그래밍 언어/반복문.md", "프로그래밍 언어/산술 표현식.md"])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)
      Records = _read_records(OutPath)
      DocIds = {R["doc_id"] for R in Records}
      self.assertEqual(len(Records), 2)
      self.assertEqual(DocIds, {"프로그래밍 언어/반복문.md", "프로그래밍 언어/산술 표현식.md"})

  def test_duplicate_id_in_input_raises(self) -> None:
    # 중복 id 가 두 번 배정되면 층화 개수가 어긋난다
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, ["a0/doc0.md", "a0/doc1.md", "a0/doc0.md"])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      with self.assertRaises(ValueError):
        assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)

  def test_exclusion_doc_id_missing_from_input_raises_only_for_matching_split(self) -> None:
    # v1 §1 - 제외 대상이 조용히 무시되면 제외돼야 할 문서가 배정에 남는다
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, ["a0/doc0.md"])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(
        ExclusionsPath,
        [
          {"split": "pilot", "doc_id": "a0/없는-문서.md"},
          {"split": "main", "doc_id": "a0/다른-split-없는-문서.md"},
        ],
      )
      OutPath = os.path.join(TempDir, "out.jsonl")

      with self.assertRaises(ValueError):
        assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)

      # 다른 split(main) 의 없는 id 는 pilot 배정에 영향을 주지 않는다 - 위와 별개 입력으로 확인
      IdsPathOther = os.path.join(TempDir, "ids_other.txt")
      _write_lines(IdsPathOther, ["a0/doc0.md"])
      ExclusionsPathOther = os.path.join(TempDir, "exclusions_other.jsonl")
      _write_jsonl(ExclusionsPathOther, [{"split": "main", "doc_id": "a0/다른-split-없는-문서.md"}])
      OutPathOther = os.path.join(TempDir, "out_other.jsonl")

      assign_source_layers(IdsPathOther, ExclusionsPathOther, "pilot", OutPathOther)
      DocIds = {R["doc_id"] for R in _read_records(OutPathOther)}
      self.assertEqual(DocIds, {"a0/doc0.md"})

  def test_stratum_nfc_nfd_collision_raises(self) -> None:
    # 같은 폴더가 둘로 갈라지면 v1 §5 폴더 층화가 깨진다
    with tempfile.TemporaryDirectory() as TempDir:
      FolderNfc = unicodedata.normalize("NFC", "가나")
      FolderNfd = unicodedata.normalize("NFD", "가나")
      self.assertNotEqual(FolderNfc, FolderNfd)
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, [f"{FolderNfc}/x.md", f"{FolderNfd}/y.md"])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      with self.assertRaises(ValueError):
        assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)

  def test_random_constructed_exactly_once_with_fixed_seed(self) -> None:
    # v1 §5.2 - Rng 하나를 폴더 순서대로 이어 쓴다. 폴더마다 새로 만들면 이 테스트가 실패해야 한다
    with tempfile.TemporaryDirectory() as TempDir:
      Ids = []
      for FolderIndex in range(4):
        for DocIndex in range(3):
          Ids.append(f"a{FolderIndex}/doc{DocIndex}.md")
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, Ids)
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      OriginalRandom = random.Random
      with mock.patch("labeling.assign_source_layers.random.Random", side_effect=OriginalRandom) as RandomSpy:
        assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)

      self.assertEqual(RandomSpy.call_count, 1)
      RandomSpy.assert_called_once_with(20260926)

  def test_all_records_have_null_personal_user_and_fixed_seed(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      IdsPath = os.path.join(TempDir, "ids.txt")
      _write_lines(IdsPath, [f"a0/doc{Index}.md" for Index in range(5)])
      ExclusionsPath = os.path.join(TempDir, "exclusions.jsonl")
      _write_jsonl(ExclusionsPath, [])
      OutPath = os.path.join(TempDir, "out.jsonl")

      assign_source_layers(IdsPath, ExclusionsPath, "pilot", OutPath)
      Records = _read_records(OutPath)
      self.assertTrue(Records)
      for Record in Records:
        self.assertIsNone(Record["personal_user"])
        self.assertEqual(Record["seed"], SEED)
        self.assertEqual(Record["seed"], 20260926)


if __name__ == "__main__":
  unittest.main()
