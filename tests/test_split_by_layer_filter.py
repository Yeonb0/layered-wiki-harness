import unittest

from retrieval.search import Retriever
from vault.types import DocumentRecord


def _fake_backend(Texts: list[str]) -> list[list[float]]:
  # 합성 벡터 - llama-server 없이 검색 로직만 검증한다
  return [[1.0, 0.0, 0.0] for _ in Texts]


class SplitByLayerFilterTest(unittest.TestCase):
  def setUp(self) -> None:
    self.Retriever = Retriever(embed_backend=_fake_backend)
    for Layer, DocId in [("개인", "p1"), ("팀", "t1"), ("전사", "e1")]:
      self.Retriever.add(
        DocumentRecord(
          id=DocId,
          layer=Layer,
          title=f"{Layer} 문서",
          body="본문",
          upward_links=[],
          downward_conditional_links=[],
          inserted_at_vault_size=0,
        )
      )

  def test_upper_layers_excluded(self) -> None:
    Results = self.Retriever.search(query="질의", k=10, mode="split_by_layer", caller_layer="개인")
    self.assertEqual(len(Results), 1)
    self.assertTrue(all(Candidate.layer == "개인" for Candidate in Results))

  def test_missing_caller_layer_raises(self) -> None:
    with self.assertRaises(ValueError):
      self.Retriever.search(query="질의", k=10, mode="split_by_layer", caller_layer=None)


if __name__ == "__main__":
  unittest.main()
