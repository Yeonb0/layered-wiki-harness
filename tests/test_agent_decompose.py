import json
import unittest

from agent.decompose import DecompositionOutputError, build_segment_labels, coverage, parse_decomposition
from agent.types import SourceDoc, SourceSegment

# 픽스처일 뿐이며 규칙과 무관하다
_DOC = SourceDoc(
  doc_id="문서A",
  title="합성 제목",
  source_layer="팀",
  source_group="그룹A",
  # seq 를 일부러 뒤섞어 표지가 seq 순서로 붙는지 본다
  segments=[
    SourceSegment(segment_id="세그C", seq=3, text="셋째 글"),
    SourceSegment(segment_id="세그A", seq=1, text="첫째 글"),
    SourceSegment(segment_id="세그B", seq=2, text="둘째 글"),
  ],
)


def _raw(Notes) -> str:
  return json.dumps({"notes": Notes}, ensure_ascii=False)


class BuildSegmentLabelsTest(unittest.TestCase):
  def test_label_string_format_and_map(self) -> None:
    LabelMap, Shown = build_segment_labels(_DOC)
    self.assertEqual(LabelMap, {"S1": "세그A", "S2": "세그B", "S3": "세그C"})
    self.assertEqual(Shown, "제목 : 합성 제목\n\n[S1]\n첫째 글\n\n[S2]\n둘째 글\n\n[S3]\n셋째 글")

  def test_no_segments_raises_value_error(self) -> None:
    Empty = SourceDoc(doc_id="문서B", title="t", source_layer="팀", source_group=None, segments=[])
    with self.assertRaises(ValueError):
      build_segment_labels(Empty)


class ParseDecompositionTest(unittest.TestCase):
  def setUp(self) -> None:
    self.LabelMap, _ = build_segment_labels(_DOC)

  def test_valid_output_converts_labels_to_segment_ids(self) -> None:
    Drafts = parse_decomposition(_raw([{"title": "제목1", "body": "본문1", "segments": ["S3", "S1"]}]), self.LabelMap)
    self.assertEqual(len(Drafts), 1)
    self.assertEqual(Drafts[0].title, "제목1")
    self.assertEqual(Drafts[0].body, "본문1")
    self.assertEqual(Drafts[0].source_segment_ids, ["세그C", "세그A"])

  def test_not_json_raises_output_error(self) -> None:
    with self.assertRaises(DecompositionOutputError):
      parse_decomposition("JSON 아님", self.LabelMap)

  def test_output_error_is_not_value_error(self) -> None:
    # 러너가 형식 오류와 하니스 오류를 구분해야 한다
    self.assertFalse(issubclass(DecompositionOutputError, ValueError))

  def test_missing_notes_raises_output_error(self) -> None:
    with self.assertRaises(DecompositionOutputError):
      parse_decomposition(json.dumps({"other": []}), self.LabelMap)

  def test_empty_notes_raises_output_error(self) -> None:
    with self.assertRaises(DecompositionOutputError):
      parse_decomposition(_raw([]), self.LabelMap)

  def test_empty_title_raises_output_error(self) -> None:
    with self.assertRaises(DecompositionOutputError):
      parse_decomposition(_raw([{"title": "", "body": "본문", "segments": ["S1"]}]), self.LabelMap)

  def test_empty_body_raises_output_error(self) -> None:
    with self.assertRaises(DecompositionOutputError):
      parse_decomposition(_raw([{"title": "제목", "body": "  ", "segments": ["S1"]}]), self.LabelMap)

  def test_segments_not_string_list_raises_output_error(self) -> None:
    with self.assertRaises(DecompositionOutputError):
      parse_decomposition(_raw([{"title": "제목", "body": "본문", "segments": [1, 2]}]), self.LabelMap)

  def test_empty_segments_raises_value_error(self) -> None:
    with self.assertRaises(ValueError) as Ctx:
      parse_decomposition(_raw([{"title": "제목", "body": "본문", "segments": []}]), self.LabelMap)
    self.assertNotIsInstance(Ctx.exception, DecompositionOutputError)

  def test_unknown_label_raises_value_error(self) -> None:
    with self.assertRaises(ValueError) as Ctx:
      parse_decomposition(_raw([{"title": "제목", "body": "본문", "segments": ["S9"]}]), self.LabelMap)
    self.assertNotIsInstance(Ctx.exception, DecompositionOutputError)

  def test_duplicate_label_in_one_note_raises_output_error(self) -> None:
    with self.assertRaises(DecompositionOutputError):
      parse_decomposition(_raw([{"title": "제목", "body": "본문", "segments": ["S1", "S1"]}]), self.LabelMap)


class CoverageTest(unittest.TestCase):
  def test_coverage_counts_and_uncovered_ids(self) -> None:
    LabelMap, _ = build_segment_labels(_DOC)
    Drafts = parse_decomposition(
      _raw(
        [
          {"title": "가", "body": "가", "segments": ["S1", "S2"]},
          {"title": "나", "body": "나", "segments": ["S2"]},
        ]
      ),
      LabelMap,
    )
    self.assertEqual(coverage(LabelMap, Drafts), {"segments": 3, "covered": 2, "uncovered_ids": ["세그C"]})


if __name__ == "__main__":
  unittest.main()
