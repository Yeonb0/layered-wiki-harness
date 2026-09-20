import json
import os
from dataclasses import asdict

from vault.store import VaultStore
from vault.types import DocumentRecord, DownwardConditionalLink


class JsonlVaultStore(VaultStore):
  # 볼트 파일 포맷 미결정 - JSONL 은 파일럿 잠정 처리, 포맷 의존 코드는 이 파일에 격리
  def __init__(self, path: str) -> None:
    self.path = path
    self._size = 0
    if os.path.exists(path):
      with open(path, "r", encoding="utf-8") as File:
        self._size = sum(1 for _ in File)

  def append(self, record: DocumentRecord) -> None:
    with open(self.path, "a", encoding="utf-8") as File:
      File.write(json.dumps(asdict(record), ensure_ascii=False))
      File.write("\n")
    self._size += 1

  def load_all(self) -> list[DocumentRecord]:
    if not os.path.exists(self.path):
      return []
    Records: list[DocumentRecord] = []
    with open(self.path, "r", encoding="utf-8") as File:
      for Line in File:
        Line = Line.strip()
        if not Line:
          continue
        Raw = json.loads(Line)
        Raw["downward_conditional_links"] = [
          DownwardConditionalLink(**Item) for Item in Raw["downward_conditional_links"]
        ]
        Records.append(DocumentRecord(**Raw))
    return Records

  def size(self) -> int:
    return self._size
