from dataclasses import dataclass


@dataclass
class Candidate:
  id: str
  layer: str
  title: str
  excerpt: str
