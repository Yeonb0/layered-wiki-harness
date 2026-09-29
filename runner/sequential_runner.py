import hashlib
import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from client.dify_client import DifyClient
from client.validation import validate_outputs
from retrieval.search import LAYER_ORDER
from runner.agent_view import build_agent_view
from runner.cold_start import ColdStartDetector
from runner.conditions import ConditionCell, build_interleaved_schedule
from runner.types import ConditionCellState, InputDoc
from vault.types import DocumentRecord
from verdictlog.types import VerdictLogEntry
from verdictlog.writer import VerdictLogWriter


def run(
  Docs: list[InputDoc],
  ConditionCellStates: dict[ConditionCell, ConditionCellState],
  client: DifyClient,
  log_writer: VerdictLogWriter,
  cold_start_detector: ColdStartDetector,
  schedule_seed: int,
) -> None:
  for Cell, State in ConditionCellStates.items():
    if State.vault.size() != 0:
      # 빈 볼트에서 시작해야 한다 - 재사용된 볼트 파일이면 볼트 크기 곡선 자체가 무의미해진다
      raise ValueError(f"condition cell {Cell} 의 볼트가 비어있지 않다 (size={State.vault.size()})")

  TrialId = str(uuid.uuid4())
  Schedule = build_interleaved_schedule(Docs, list(ConditionCellStates.keys()), schedule_seed)
  RunIndexByCell = {SelectedCell: 0 for SelectedCell in ConditionCellStates}

  for Doc, SelectedCell in Schedule:
    _process_one(
      Doc,
      SelectedCell,
      ConditionCellStates[SelectedCell],
      client,
      log_writer,
      cold_start_detector,
      RunIndexByCell,
      TrialId,
      schedule_seed,
    )


def _process_one(
  doc: InputDoc,
  cell: ConditionCell,
  state: ConditionCellState,
  client: DifyClient,
  log_writer: VerdictLogWriter,
  cold_start_detector: ColdStartDetector,
  run_index_by_cell: dict[ConditionCell, int],
  trial_id: str,
  schedule_seed: int,
) -> None:
  VaultSize = state.vault.size()
  if cell.mode == "split_by_layer":
    if doc.source_layer is None or doc.source_layer not in LAYER_ORDER:
      # 확정 결정 2026-09-26 - 조용히 기본값을 쓰면 검색 후보가 전 층 열람과 같아져 누출 0 하한 기준선이 무너진다
      raise ValueError(f"split_by_layer 모드는 문서의 source_layer 가 LAYER_ORDER 안의 값이어야 한다 (doc={doc.id}, source_layer={doc.source_layer!r})")
    CallerLayer = doc.source_layer
  else:
    CallerLayer = None
  Candidates = state.retriever.search(
    query=doc.title + "\n" + doc.body,
    k=cell.k,
    mode=cell.mode,
    caller_layer=CallerLayer,
  )

  IsColdStart = cold_start_detector.check(time.monotonic())

  CandidatesJson = json.dumps([asdict(C) for C in Candidates], ensure_ascii=False)
  RunConfigSnapshot = asdict(state.run_config)
  RunConfigJson = json.dumps(RunConfigSnapshot, ensure_ascii=False)

  # 라벨링 기준 v1 §1 - 제목을 빼면 라벨러가 본 정보를 에이전트가 받지 못한다
  AgentView = build_agent_view(doc.title, doc.body)
  DocViewSha256 = hashlib.sha256(AgentView.encode("utf-8")).hexdigest()

  StartedAt = time.monotonic()
  Result, Retried = client.run_workflow(
    doc=AgentView,
    candidates_json=CandidatesJson,
    vault_size=VaultSize,
    mode=cell.mode,
    run_config_json=RunConfigJson,
  )
  EndedAt = time.monotonic()
  ProcessingTimeSeconds = EndedAt - StartedAt
  cold_start_detector.record_call_end(EndedAt)

  # candidates 전달 - 러너가 판정에 쓴 후보 목록을 이미 들고 있으므로 그대로 넘긴다
  Validation = validate_outputs(Result, mode=cell.mode, caller_layer=CallerLayer, candidates=Candidates, source_layer=doc.source_layer)

  if Validation.valid and Validation.verdict is not None:
    Record = DocumentRecord(
      id=doc.id,
      layer=Validation.verdict.layer,
      title=doc.title,
      body=doc.body,
      upward_links=Validation.verdict.upward_links,
      downward_conditional_links=Validation.verdict.downward_conditional_links,
      inserted_at_vault_size=VaultSize,
    )
    state.vault.append(Record)
    state.retriever.add(Record)

  RunIndex = run_index_by_cell[cell]
  run_index_by_cell[cell] = RunIndex + 1

  log_writer.append(
    VerdictLogEntry(
      entry_id=str(uuid.uuid4()),
      trial_id=trial_id,
      wall_clock=datetime.now(timezone.utc).isoformat(),
      schedule_seed=schedule_seed,
      run_index=RunIndex,
      doc_id=doc.id,
      doc_title=doc.title,
      doc_body=doc.body,
      doc_view_sha256=DocViewSha256,
      source_layer=doc.source_layer,
      condition=cell.condition,
      mode=cell.mode,
      k=cell.k,
      vault_size=VaultSize,
      retrieved_candidates=Candidates,
      ok=Result.ok,
      errors=Result.errors,
      raw_verdict=Result.verdict,
      verdict=Validation.verdict,
      validation_problems=Validation.problems,
      selection_rationale=Validation.verdict.rationale if Validation.verdict else "",
      model_raw_output=Result.log,
      cold_start=IsColdStart,
      retried=Retried,
      processing_time_seconds=ProcessingTimeSeconds,
      run_config_snapshot=RunConfigSnapshot,
    )
  )
