import os
import unittest
from unittest import mock

from retrieval.embeddings import EMBED_MAX_CHARS, EMBED_TIMEOUT_SECONDS, EMBEDDING_ENDPOINT_ENV, embed, embed_batch


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


class EmbeddingsTruncationTest(unittest.TestCase):
  # 픽스처일 뿐이며 규칙과 무관하다
  def _post_body(self, Texts: list[str]) -> dict:
    Response = mock.Mock()
    Response.json.return_value = {"data": [{"index": Index, "embedding": [1.0]} for Index in range(len(Texts))]}
    with mock.patch.dict(os.environ, {EMBEDDING_ENDPOINT_ENV: "http://127.0.0.1:0/v1/embeddings"}), mock.patch("requests.post", return_value=Response) as Post:
      embed_batch(Texts)
    return Post.call_args.kwargs["json"]

  def test_text_over_limit_is_cut_to_limit_in_request_body(self) -> None:
    Body = self._post_body(["가" * (EMBED_MAX_CHARS + 500)])
    self.assertEqual(Body["input"], ["가" * EMBED_MAX_CHARS])

  def test_text_within_limit_is_sent_as_is(self) -> None:
    Short = "나" * EMBED_MAX_CHARS
    Body = self._post_body(["짧은 글", Short])
    self.assertEqual(Body["input"], ["짧은 글", Short])

  def test_post_timeout_is_embed_timeout_seconds(self) -> None:
    Response = mock.Mock()
    Response.json.return_value = {"data": [{"index": 0, "embedding": [1.0]}]}
    with mock.patch.dict(os.environ, {EMBEDDING_ENDPOINT_ENV: "http://127.0.0.1:0/v1/embeddings"}), mock.patch("requests.post", return_value=Response) as Post:
      embed_batch(["x"])
    self.assertEqual(Post.call_args.kwargs["timeout"], EMBED_TIMEOUT_SECONDS)
    self.assertEqual(EMBED_TIMEOUT_SECONDS, 600)

  def test_limit_is_4000(self) -> None:
    self.assertEqual(EMBED_MAX_CHARS, 4000)

  def test_injected_backend_also_receives_cut_text(self) -> None:
    Seen = []

    def Backend(Texts: list[str]) -> list[list[float]]:
      Seen.extend(Texts)
      return [[1.0] for _ in Texts]

    embed_batch(["다" * (EMBED_MAX_CHARS + 1)], backend=Backend)
    self.assertEqual(Seen, ["다" * EMBED_MAX_CHARS])


if __name__ == "__main__":
  unittest.main()
