import json
from typing import Any

from verdictlog.problem_codes import PROBLEM_CODE_CLASSIFICATION


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


def validation_breakdown(Entries: list[dict[str, Any]]) -> dict[str, Any]:
  # 로그 JSONL 만 읽는다 - 볼트 · 모델 · 러너에 접근하지 않는다
  ExcludedWithoutTrialId = 0
  ExcludedWithoutCellKey = 0
  CellTrials: dict[str, dict[str, Any]] = {}

  for Entry in Entries:
    TrialId = Entry.get("trial_id")
    if TrialId is None:
      ExcludedWithoutTrialId += 1
      continue
    Condition = Entry.get("condition")
    Mode = Entry.get("mode")
    K = Entry.get("k")
    if Condition is None or Mode is None or K is None:
      ExcludedWithoutCellKey += 1
      continue
    CellKey = f"{Condition}|{Mode}|{K}"
    Cell = CellTrials.setdefault(CellKey, {"condition": Condition, "mode": Mode, "k": K, "trials": {}})
    Cell["trials"].setdefault(TrialId, []).append(Entry)

  Cells: dict[str, Any] = {}
  for CellKey, CellData in CellTrials.items():
    TrialsMap = CellData["trials"]
    SchemaRates: list[float] = []
    ModeRuleRates: list[float] = []
    DecisionRates: list[float] = []
    WorkflowFailureRates: list[float] = []
    TrialsOutput: dict[str, Any] = {}

    for TrialId, TrialEntries in TrialsMap.items():
      Denominator = len(TrialEntries)
      SchemaNumerator = 0
      ModeRuleNumerator = 0
      DecisionNumerator = 0
      WorkflowFailureNumerator = 0
      for Entry in TrialEntries:
        Problems = Entry.get("validation_problems") or []
        Classifications = set()
        for Code in Problems:
          if Code not in PROBLEM_CODE_CLASSIFICATION:
            # 등록되지 않은 코드가 스키마 오류로 조용히 떨어지면 결정 위반이 스키마 오류에 섞인다
            raise ValueError(f"등록되지 않은 problem 코드 {Code!r}")
          Classifications.add(PROBLEM_CODE_CLASSIFICATION[Code])
        if "mode_rule_rejection" in Classifications:
          ModeRuleNumerator += 1
        if "decision_violation" in Classifications:
          DecisionNumerator += 1
        if "schema_error" in Classifications:
          SchemaNumerator += 1
        if Entry.get("ok") is False:
          WorkflowFailureNumerator += 1

      SchemaRates.append(SchemaNumerator / Denominator)
      ModeRuleRates.append(ModeRuleNumerator / Denominator)
      DecisionRates.append(DecisionNumerator / Denominator)
      WorkflowFailureRates.append(WorkflowFailureNumerator / Denominator)
      TrialsOutput[TrialId] = {
        "schema_error": {"numerator": SchemaNumerator, "denominator": Denominator},
        "mode_rule_rejection": {"numerator": ModeRuleNumerator, "denominator": Denominator},
        "decision_violation": {"numerator": DecisionNumerator, "denominator": Denominator},
        "workflow_failure": {"numerator": WorkflowFailureNumerator, "denominator": Denominator},
      }

    Cells[CellKey] = {
      "condition": CellData["condition"],
      "mode": CellData["mode"],
      "k": CellData["k"],
      "schema_error_rate": _describe_trials(SchemaRates),
      "mode_rule_rejection_rate": _describe_trials(ModeRuleRates),
      "decision_violation_rate": _describe_trials(DecisionRates),
      "workflow_failure_rate": _describe_trials(WorkflowFailureRates),
      "trials": TrialsOutput,
    }

  return {
    "excluded_without_trial_id": ExcludedWithoutTrialId,
    "excluded_without_cell_key": ExcludedWithoutCellKey,
    "cells": Cells,
  }


def _describe_trials(Values: list[float]) -> dict[str, float | int | None]:
  Variance = _variance(Values) if len(Values) >= 2 else None
  return {"variance": Variance, "mean": _mean(Values), "n_trials": len(Values)}


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
