import json
from dataclasses import asdict

from verdictlog.types import VerdictLogEntry


class VerdictLogWriter:
  def __init__(self, path: str) -> None:
    self.path = path

  def append(self, entry: VerdictLogEntry) -> None:
    with open(self.path, "a", encoding="utf-8") as File:
      File.write(json.dumps(asdict(entry), ensure_ascii=False, default=str))
      File.write("\n")
