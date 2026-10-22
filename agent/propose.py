import hashlib
import json
from dataclasses import asdict

from agent.decompose import DecompositionOutputError, build_segment_labels, coverage, parse_assignment
from agent.placement import MODES, build_note_record, validate_placement
from agent.prompts import (
  assign_schema,
  build_decompose_messages,
  build_place_messages,
  place_schema,
  require_block_in_messages,
)
from labeling.gold import Membership
from vault.types import DocumentRecord, DownwardConditionalLink


def _entry(BaseLog: dict, Fields: dict) -> dict:
  # BaseLog 키와 항목 키가 겹치면 러너가 준 값이 조용히 덮인다
  Overlap = set(BaseLog) & set(Fields)
  if Overlap:
    raise ValueError(f"BaseLog 키가 항목 키와 겹친다: {sorted(Overlap)}")
  return {**BaseLog, **Fields}


def _chat_fields(Result) -> dict:
  return {
    "raw_text": Result.text,
    "prompt_tokens": Result.prompt_tokens,
    "completion_tokens": Result.completion_tokens,
    "elapsed_seconds": Result.elapsed_seconds,
    "finish_reason": Result.finish_reason,
    "timings": Result.timings,
  }


def _to_document_record(Note) -> DocumentRecord:
  # 볼트 레코드의 가시 조건은 문자열이고 노트 레코드의 것은 dict 이다 - 키 순서를 고정한 JSON 문자열로 옮긴다
  Links = [
    DownwardConditionalLink(
      target_id=Link.target_id,
      visibility_condition=json.dumps(Link.visibility_condition, ensure_ascii=False, sort_keys=True),
    )
    for Link in Note.downward_conditional_links
  ]
  return DocumentRecord(
    id=Note.note_id,
    layer=Note.layer,
    title=Note.title,
    body=Note.body,
    upward_links=list(Note.upward_links),
    downward_conditional_links=Links,
    inserted_at_vault_size=Note.inserted_at_vault_size,
  )


def run_propose_doc(
  doc,
  mode,
  k,
  retriever,
  VaultNotes,
  LayerGroupById,
  chat_fn,
  model_id,
  decompose_config,
  place_config,
  layer_block,
  layer_block_sha256,
  # 사용자 결정 2026-10-22 : 소속 팀 표 - 검색 · 배치 그룹이 이 표에서 나온다
  Owners: Membership,
  timeout_seconds,
  BaseLog,
) -> list[dict]:
  # mode 는 두 값뿐 - 다른 값은 검색 필터와 스키마가 달라진다
  if mode not in MODES:
    raise ValueError(f"알 수 없는 mode: {mode!r}")
  LabelMap, Shown = build_segment_labels(doc)
  TextById = {Seg.segment_id: Seg.text for Seg in doc.segments}
  Log = []

  # 모델이 이 문서에 없는 표지를 만들지 못하게 표지 목록을 프롬프트와 스키마에 넘긴다 ( 표지마다 노트 번호 하나 )
  Labels = list(LabelMap)
  Messages = build_decompose_messages(layer_block, doc.source_layer, Shown, Labels)
  require_block_in_messages(Messages, layer_block)
  # 호출이 실패한 문서도 볼트 크기를 로그에 남겨 조건 간 로그 필드를 맞춘다 ( B1 의 b1_call 과 같은 키 )
  DecomposeVaultSize = len(VaultNotes)
  Result = chat_fn(Messages, model_id, decompose_config, assign_schema(Labels), timeout_seconds=timeout_seconds)

  Drafts = []
  Error = None
  # "length" 면 잘린 출력이다 - 파싱하지 않고 형식 실패로 기록한다
  if Result.finish_reason != "stop":
    Error = f"finish_reason:{Result.finish_reason}"
  else:
    try:
      Drafts = parse_assignment(Result.text, LabelMap, TextById)
    except DecompositionOutputError as Failure:
      # 형식 오류는 러너가 실패로 기록할 대상이다 - ValueError 는 잡지 않고 올린다
      Error = str(Failure)
  Log.append(_entry(BaseLog, {
    "entry_type": "decompose",
    "doc_id": doc.doc_id,
    "vault_size_before": DecomposeVaultSize,
    "source_layer": doc.source_layer,
    "source_group": doc.source_group,
    "doc_view_sha256": hashlib.sha256(Shown.encode("utf-8")).hexdigest(),
    "layer_block_sha256": layer_block_sha256,
    "label_map": LabelMap,
    "ok": Error is None,
    "error": Error,
    "notes": [{"title": Draft.title, "source_segment_ids": Draft.source_segment_ids} for Draft in Drafts],
    "coverage": coverage(LabelMap, Drafts) if Error is None else None,
    **_chat_fields(Result),
  }))
  if Error is not None:
    return Log

  for NoteIndex, Draft in enumerate(Drafts):
    VaultSize = len(VaultNotes)
    # 사용자 결정 2026-10-16 (나-2) : 층별 분리 모드의 가시 범위는 층 × 그룹이다 - 모드 분기는 search_visible 이 한다
    Candidates = retriever.search_visible(Draft.title + "\n" + Draft.body, k, mode, doc.source_layer, doc.source_group, Owners)
    PlaceMessages = build_place_messages(layer_block, mode, doc.source_layer, Draft.title, Draft.body, Candidates)
    require_block_in_messages(PlaceMessages, layer_block)
    PlaceResult = chat_fn(
      PlaceMessages, model_id, place_config, place_schema(mode, doc.source_layer, Candidates),
      timeout_seconds=timeout_seconds
    )

    Problems = []
    Raw = None
    # "length" 면 잘린 출력이다 - 파싱하지 않고 실패로 기록한다
    if PlaceResult.finish_reason != "stop":
      Problems.append(f"finish_reason:{PlaceResult.finish_reason}")
    else:
      try:
        Raw = json.loads(PlaceResult.text)
      except json.JSONDecodeError:
        Problems.append("not_json")
    Verdict = None
    if not Problems:
      # ValueError ( 층별 분리 모드의 출처 위 판정 등 ) 는 마지막 방어선이라 올린다
      Validation = validate_placement(Raw, mode, doc.source_layer, Candidates)
      Problems = list(Validation.problems)
      Verdict = Validation.verdict

    NoteId = None
    Links = []
    if not Problems:
      Record = build_note_record(Draft, Verdict, doc, NoteIndex, VaultSize, LayerGroupById, Owners)
      NoteId = Record.note_id
      Links = [asdict(Link) for Link in Record.downward_conditional_links]
      VaultNotes.append(Record)
      LayerGroupById[Record.note_id] = (Record.layer, Record.group)
      # 그룹을 함께 색인해야 이후 문서의 층 × 그룹 검색이 이 노트를 판정할 수 있다
      retriever.add(_to_document_record(Record), group=Record.group)
    Log.append(_entry(BaseLog, {
      "entry_type": "place",
      "doc_id": doc.doc_id,
      "note_index": NoteIndex,
      "vault_size_before": VaultSize,
      "note_id": NoteId,
      "source_segment_ids": list(Draft.source_segment_ids),
      "candidates": [{"id": Cand.id, "layer": Cand.layer, "title": Cand.title} for Cand in Candidates],
      "ok": not Problems,
      "problems": Problems,
      "verdict": None if Verdict is None or Problems else {
        "layer": Verdict.layer,
        "upward_links": Verdict.upward_links,
        "downward_target_ids": Verdict.downward_target_ids,
        "rationale": Verdict.rationale,
      },
      "downward_conditional_links": Links,
      **_chat_fields(PlaceResult),
    }))
  return Log
