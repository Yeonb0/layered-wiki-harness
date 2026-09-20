import unittest

from retrieval.embeddings import embed, embed_batch


def _synthetic_backend(Texts: list[str]) -> list[list[float]]:
  return [[float(len(Text)), 0.0] for Text in Texts]


class EmbeddingsBackendTest(unittest.TestCase):
  def test_embed_batch_uses_injected_backend(self) -> None:
    Vectors = embed_batch(["ab", "abc"], backend=_synthetic_backend)
    self.assertEqual(Vectors, [[2.0, 0.0], [3.0, 0.0]])

  def test_embed_uses_injected_backend(self) -> None:
    Vector = embed("abcd", backend=_synthetic_backend)
    self.assertEqual(Vector, [4.0, 0.0])


if __name__ == "__main__":
  unittest.main()
