import unittest

from config.run_config import RunConfig

# 이 파일의 criteria_sha256 · labels_sha256 값은 픽스처일 뿐이며 규칙과 무관하다
VALID_SHA256 = "a" * 64


class RunConfigTest(unittest.TestCase):
  def test_missing_criteria_sha256_raises_type_error(self) -> None:
    with self.assertRaises(TypeError):
      RunConfig(condition="B0", mode="all_layers", k=4, model_id="fake")  # type: ignore[call-arg]

  def test_invalid_criteria_sha256_raises_value_error(self) -> None:
    InvalidValues = [
      "a" * 63,  # 63자
      "A" * 64,  # 대문자
      "g" * 64,  # 비16진
      "a" * 64 + "\n",  # 끝 줄바꿈
    ]
    for InvalidValue in InvalidValues:
      with self.subTest(value=InvalidValue):
        with self.assertRaises(ValueError):
          RunConfig(
            condition="B0",
            mode="all_layers",
            k=4,
            model_id="fake",
            criteria_sha256=InvalidValue,
            labels_sha256=None,
          )

  def test_labels_sha256_none_allowed_and_invalid_format_raises(self) -> None:
    RunConfig(
      condition="B0",
      mode="all_layers",
      k=4,
      model_id="fake",
      criteria_sha256=VALID_SHA256,
      labels_sha256=None,
    )

    with self.assertRaises(ValueError):
      RunConfig(
        condition="B0",
        mode="all_layers",
        k=4,
        model_id="fake",
        criteria_sha256=VALID_SHA256,
        labels_sha256="A" * 64,
      )

    with self.assertRaises(ValueError):
      RunConfig(
        condition="B0",
        mode="all_layers",
        k=4,
        model_id="fake",
        criteria_sha256=VALID_SHA256,
        labels_sha256="a" * 64 + "\n",  # 끝 줄바꿈
      )


if __name__ == "__main__":
  unittest.main()
