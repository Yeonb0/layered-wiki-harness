from dataclasses import dataclass


@dataclass
class DownwardConditionalLink:
  target_id: str
  visibility_condition: str


@dataclass
class DocumentRecord:
  id: str
  layer: str
  title: str
  body: str
  upward_links: list[str]
  downward_conditional_links: list[DownwardConditionalLink]
  inserted_at_vault_size: int
