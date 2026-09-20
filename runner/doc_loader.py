import json

from runner.types import InputDoc

# 문서 소스 포맷 미결정 - 파일럿은 JSONL {id, title, body} 로 잠정 처리, 포맷 의존 코드는 이 모듈에 격리


def load_docs(path: str) -> list[InputDoc]:
  Docs: list[InputDoc] = []
  with open(path, "r", encoding="utf-8") as File:
    for Line in File:
      Line = Line.strip()
      if not Line:
        continue
      Raw = json.loads(Line)
      Docs.append(InputDoc(id=Raw["id"], title=Raw["title"], body=Raw["body"]))
  return Docs
