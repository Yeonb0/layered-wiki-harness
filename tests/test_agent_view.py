import unittest

from runner.agent_view import build_agent_view


class BuildAgentViewTest(unittest.TestCase):
  def test_returns_title_blank_line_body(self) -> None:
    self.assertEqual(build_agent_view("제목", "본문"), "제목" + "\n\n" + "본문")


if __name__ == "__main__":
  unittest.main()
