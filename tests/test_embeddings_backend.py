import os
import unittest
from unittest import mock

from retrieval.embeddings import EMBEDDING_ENDPOINT_ENV, embed, embed_batch


def _synthetic_backend(Texts: list[str]) -> list[list[float]]:
  return [[float(len(Text)), 0.0] for Text in Texts]


class EmbeddingsBackendTest(unittest.TestCase):
  def test_embed_batch_uses_injected_backend(self) -> None:
    Vectors = embed_batch(["ab", "abc"], backend=_synthetic_backend)
    self.assertEqual(Vectors, [[2.0, 0.0], [3.0, 0.0]])

  def test_embed_uses_injected_backend(self) -> None:
    Vector = embed("abcd", backend=_synthetic_backend)
    self.assertEqual(Vector, [4.0, 0.0])


class EmbeddingsEndpointTest(unittest.TestCase):
  # 네트워크 호출은 requests.post mock 으로 막는다 — 실제 서버를 부르지 않는다
  def test_missing_endpoint_env_raises_value_error(self) -> None:
    Env = {Key: Value for Key, Value in os.environ.items() if Key != EMBEDDING_ENDPOINT_ENV}
    with mock.patch.dict(os.environ, Env, clear=True), mock.patch("requests.post") as Post:
      with self.assertRaises(ValueError):
        embed("x")
      Post.assert_not_called()

  def test_empty_endpoint_env_raises_value_error(self) -> None:
    with mock.patch.dict(os.environ, {EMBEDDING_ENDPOINT_ENV: ""}), mock.patch("requests.post") as Post:
      with self.assertRaises(ValueError):
        embed("x")
      Post.assert_not_called()

  def test_zero_length_vector_raises_value_error(self) -> None:
    Response = mock.Mock()
    Response.json.return_value = {"data": [{"index": 0, "embedding": []}]}
    with mock.patch.dict(os.environ, {EMBEDDING_ENDPOINT_ENV: "http://127.0.0.1:0/v1/embeddings"}), mock.patch("requests.post", return_value=Response):
      with self.assertRaises(ValueError):
        embed("x")


if __name__ == "__main__":
  unittest.main()
