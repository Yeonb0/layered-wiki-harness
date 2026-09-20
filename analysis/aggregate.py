import json
from typing import Any


def load_log(path: str) -> list[dict[str, Any]]:
  Entries: list[dict[str, Any]] = []
  with open(path, "r", encoding="utf-8") as File:
    for Line in File:
      Line = Line.strip()
      if not Line:
        continue
      Entries.append(json.loads(Line))
  return Entries


def describe_by(
  Entries: list[dict[str, Any]],
  group_fields: tuple[str, ...],
  value_field: str,
) -> dict[tuple, dict[str, float]]:
  Groups: dict[tuple, list[float]] = {}
  for Entry in Entries:
    Key = tuple(Entry.get(Field) for Field in group_fields)
    if any(Part is None for Part in Key):
      continue
    Value = Entry.get(value_field)
    if Value is None:
      continue
    Groups.setdefault(Key, []).append(Value)
  return {Key: _describe(Values) for Key, Values in Groups.items()}


def variance_by_condition(Entries: list[dict[str, Any]], field: str) -> dict[str, float]:
  Grouped = describe_by(Entries, ("condition",), field)
  return {Key[0]: Stats["variance"] for Key, Stats in Grouped.items()}


def processing_time_stats(
  Entries: list[dict[str, Any]],
  group_fields: tuple[str, ...] = (),
) -> dict[Any, dict[str, float]]:
  # cold_start, retried 건 제외
  Filtered = [Entry for Entry in Entries if not Entry.get("cold_start") and not Entry.get("retried")]
  if not group_fields:
    Values = [Entry["processing_time_seconds"] for Entry in Filtered if "processing_time_seconds" in Entry]
    return {"all": _describe(Values)}
  return describe_by(Filtered, group_fields, "processing_time_seconds")


def _describe(Values: list[float]) -> dict[str, float]:
  return {"variance": _variance(Values), "mean": _mean(Values), "n": len(Values)}


def _variance(Values: list[float]) -> float:
  if len(Values) < 2:
    return 0.0
  Mean = _mean(Values)
  return sum((X - Mean) ** 2 for X in Values) / (len(Values) - 1)


def _mean(Values: list[float]) -> float:
  if not Values:
    return 0.0
  return sum(Values) / len(Values)
