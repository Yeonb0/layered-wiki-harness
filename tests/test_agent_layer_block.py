import hashlib
import os
import tempfile
import unittest

from agent.layer_block import MARK, extract_layer_block, extract_layer_block_with_skipped, load_layer_block

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 마크다운이다


class ExtractLayerBlockTest(unittest.TestCase):
  def test_marked_lines_only_keep_document_order(self) -> None:
    Text = f"머리말\n- 첫 {MARK} 줄\n사이 글\n- 둘째 {MARK} 줄\n끝 글"
    self.assertEqual(extract_layer_block(Text), f"- 첫 {MARK} 줄\n- 둘째 {MARK} 줄")

  def test_marked_h2_runs_to_next_h2_including_h3(self) -> None:
    Text = f"# 제목\n## 가 {MARK}\n가 본문\n### 가-1\n가-1 본문\n## 나\n나 본문\n"
    self.assertEqual(extract_layer_block(Text), f"## 가 {MARK}\n가 본문\n### 가-1\n가-1 본문")

  def test_marked_h3_runs_to_next_h3_or_h2(self) -> None:
    Text = f"## 가\n### 가-1 {MARK}\n가-1 본문\n### 가-2\n가-2 본문\n"
    self.assertEqual(extract_layer_block(Text), f"### 가-1 {MARK}\n가-1 본문")
    Text2 = f"## 가\n### 가-1 {MARK}\n가-1 본문\n## 나\n나 본문\n"
    self.assertEqual(extract_layer_block(Text2), f"### 가-1 {MARK}\n가-1 본문")

  def test_marked_line_inside_marked_section_is_not_duplicated(self) -> None:
    Text = f"## 가 {MARK}\n본문 {MARK} 줄\n## 나\n"
    self.assertEqual(extract_layer_block(Text), f"## 가 {MARK}\n본문 {MARK} 줄")

  def test_marked_line_after_section_end_is_included_separately(self) -> None:
    Text = f"## 가 {MARK}\n가 본문\n## 나\n- 나 {MARK} 줄\n"
    self.assertEqual(extract_layer_block(Text), f"## 가 {MARK}\n가 본문\n## 나\n- 나 {MARK} 줄")

  def test_clauses_outside_section_get_nearest_heading_once_per_heading(self) -> None:
    Text = f"### 가\n- 가1 {MARK}\n- 가2 {MARK}\n### 나\n- 나1 {MARK}\n"
    self.assertEqual(
      extract_layer_block(Text),
      f"### 가\n- 가1 {MARK}\n- 가2 {MARK}\n### 나\n- 나1 {MARK}",
    )

  def test_clauses_without_any_heading_have_no_heading_prefix(self) -> None:
    Text = f"머리말\n- 첫 {MARK}\n- 둘째 {MARK}\n"
    self.assertEqual(extract_layer_block(Text), f"- 첫 {MARK}\n- 둘째 {MARK}")

  def test_heading_inside_code_block_is_not_used_as_clause_heading(self) -> None:
    Text = f"### 가\n```\n### 코드 안\n```\n- 조항 {MARK}\n"
    self.assertEqual(extract_layer_block(Text), f"### 가\n- 조항 {MARK}")

  def test_hash_inside_code_block_is_not_heading(self) -> None:
    Text = f"## 가 {MARK}\n```\n# 코드 안 제목\n## 코드 안 둘째\n```\n뒤 본문\n## 나\n"
    self.assertEqual(
      extract_layer_block(Text),
      f"## 가 {MARK}\n```\n# 코드 안 제목\n## 코드 안 둘째\n```\n뒤 본문",
    )

  def test_trailing_blank_lines_removed_and_inner_blank_lines_kept(self) -> None:
    Text = f"## 가 {MARK}\n\n본문\n\n\n## 나\n"
    self.assertEqual(extract_layer_block(Text), f"## 가 {MARK}\n\n본문")

  def test_plain_paragraph_mark_line_outside_section_is_skipped_and_reported(self) -> None:
    Text = f"설명 {MARK} 문단\n- 조항 {MARK}\n"
    Block, Skipped = extract_layer_block_with_skipped(Text)
    self.assertEqual(Block, f"- 조항 {MARK}")
    self.assertEqual(Skipped, [1])

  def test_indented_list_item_is_included(self) -> None:
    Text = f"- 상위\n  - 하위 {MARK}\n"
    Block, Skipped = extract_layer_block_with_skipped(Text)
    self.assertEqual(Block, f"  - 하위 {MARK}")
    self.assertEqual(Skipped, [])

  def test_plain_paragraph_inside_marked_section_is_included(self) -> None:
    Text = f"## 가 {MARK}\n일반 문단 {MARK}\n그냥 문단\n## 나\n"
    Block, Skipped = extract_layer_block_with_skipped(Text)
    self.assertEqual(Block, f"## 가 {MARK}\n일반 문단 {MARK}\n그냥 문단")
    self.assertEqual(Skipped, [])

  def test_only_skipped_lines_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      extract_layer_block(f"설명 {MARK} 문단\n다른 글\n")

  def test_no_mark_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      extract_layer_block("## 가\n본문\n")

  def test_same_input_twice_gives_same_hash(self) -> None:
    Text = f"## 가 {MARK}\n본문\n"
    First = hashlib.sha256(extract_layer_block(Text).encode("utf-8")).hexdigest()
    Second = hashlib.sha256(extract_layer_block(Text).encode("utf-8")).hexdigest()
    self.assertEqual(First, Second)


class LoadLayerBlockTest(unittest.TestCase):
  def setUp(self) -> None:
    self.Dir = tempfile.TemporaryDirectory()
    self.addCleanup(self.Dir.cleanup)
    self.Path = os.path.join(self.Dir.name, "criteria.md")
    self.Raw = f"## 가 {MARK}\n본문\n## 나\n".encode("utf-8")
    with open(self.Path, "wb") as File:
      File.write(self.Raw)
    self.FileSha = hashlib.sha256(self.Raw).hexdigest()

  def test_load_returns_block_and_its_sha256(self) -> None:
    Block, BlockSha = load_layer_block(self.Path, self.FileSha)
    self.assertEqual(Block, f"## 가 {MARK}\n본문")
    self.assertEqual(BlockSha, hashlib.sha256(Block.encode("utf-8")).hexdigest())

  def test_load_twice_gives_same_sha256(self) -> None:
    self.assertEqual(load_layer_block(self.Path, self.FileSha), load_layer_block(self.Path, self.FileSha))

  def test_hash_mismatch_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      load_layer_block(self.Path, "0" * 64)


if __name__ == "__main__":
  unittest.main()
