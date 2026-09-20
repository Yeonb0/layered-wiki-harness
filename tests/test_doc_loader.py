import json
import os
import tempfile
import unittest

from runner.doc_loader import load_docs


class LoadDocsTest(unittest.TestCase):
  def test_reads_jsonl_fields(self) -> None:
    with tempfile.TemporaryDirectory() as TempDir:
      DocsPath = os.path.join(TempDir, "docs.jsonl")
      with open(DocsPath, "w", encoding="utf-8") as File:
        File.write(json.dumps({"id": "d0", "title": "제목0", "body": "본문0"}, ensure_ascii=False) + "\n")
        File.write("\n")
        File.write(json.dumps({"id": "d1", "title": "제목1", "body": "본문1"}, ensure_ascii=False) + "\n")

      Docs = load_docs(DocsPath)

      self.assertEqual([Doc.id for Doc in Docs], ["d0", "d1"])
      self.assertEqual(Docs[0].title, "제목0")
      self.assertEqual(Docs[1].body, "본문1")


if __name__ == "__main__":
  unittest.main()
