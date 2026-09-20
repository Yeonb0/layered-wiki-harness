from typing import Protocol

from vault.types import DocumentRecord


class VaultStore(Protocol):
  def append(self, record: DocumentRecord) -> None: ...

  def load_all(self) -> list[DocumentRecord]: ...

  def size(self) -> int: ...
