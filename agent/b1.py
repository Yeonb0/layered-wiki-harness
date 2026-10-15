import hashlib
import json
from dataclasses import asdict

from agent.decompose import DecompositionOutputError, build_drafts_from_assignment, build_segment_labels, coverage
from agent.placement import MODES, build_note_record, validate_placement
from agent.prompts import b1_schema, build_b1_messages, require_block_in_messages
from agent.propose import _chat_fields, _entry, _to_document_record

# 노트 항목의 토큰 · 시간 필드 - 한 번의 호출 값이라 노트마다 따로 없다 ( b1_call 항목에 있다 )
_NO_CALL_FIELDS = {
  "raw_text": None,
  "prompt_tokens": None,
  "completion_tokens": None,
  "elapsed_seconds": None,
  "finish_reason": None,
  "timings": None,
}


def _parse_call_output(raw_text: str, LabelMap: dict, TextById: dict):
  # 문서 실패 사유는 DecompositionOutputError 로 올린다 - ValueError ( 지침 3 절 ) 는 잡지 않는다
  try:
    Parsed = json.loads(raw_text)
  except json.JSONDecodeError as Error:
    raise DecompositionOutputError(f"JSON 이 아니다: {Error}") from Error
  # 최상위는 assign 과 notes 키를 가진 객체여야 한다
  if not isinstance(Parsed, dict) or "assign" not in Parsed or "notes" not in Parsed:
    raise DecompositionOutputError("assign 이나 notes 키가 없다")
  Assign = Parsed["assign"]
  Notes = Parsed["notes"]
  if not isinstance(Assign, dict):
    raise DecompositionOutputError("assign 이 객체가 아니다")
  # 지침 3 절 ValueError 가 notes 개수 같은 형식 실패에 묻히지 않게 개수 검사보다 먼저 본다
  Unknown = [Label for Label in Assign if Label not in LabelMap]
  if Unknown:
    raise ValueError(f"표지에 없는 assign 키: {Unknown}")
  if not isinstance(Notes, list) or not all(isinstance(Note, dict) for Note in Notes):
    raise DecompositionOutputError("notes 가 객체 목록이 아니다")
  # 번호 값이 목록 같은 것이면 집합을 만들 수 없다 - 번호 검사는 build_drafts_from_assignment 가 한다
  try:
    UsedCount = len(set(Assign.values()))
  except TypeError as Error:
    raise DecompositionOutputError("assign 의 번호가 정수가 아니다") from Error
  # notes 가 번호마다 하나씩 있어야 노트와 판정이 짝지어진다
  if len(Notes) != UsedCount:
    raise DecompositionOutputError(f"notes 개수({len(Notes)}) 가 쓰인 번호 수({UsedCount}) 와 다르다")
  Drafts = build_drafts_from_assignment(Assign, [Note.get("title") for Note in Notes], LabelMap, TextById)
  return Drafts, Notes


def run_b1_doc(
  doc,
  mode,
  k,
  retriever,
  VaultNotes,
  LayerGroupById,
  chat_fn,
  model_id,
  config,
  layer_block,
  layer_block_sha256,
  Owners,
  timeout_seconds,
  BaseLog,
) -> list[dict]:
  # mode 는 두 값뿐 - 다른 값은 검색 필터와 스키마가 달라진다
  if mode not in MODES:
    raise ValueError(f"알 수 없는 mode: {mode!r}")
  LabelMap, Shown = build_segment_labels(doc)
  TextById = {Seg.segment_id: Seg.text for Seg in doc.segments}
  Labels = list(LabelMap)
  Log = []

  # B1 은 문서 단위로 한 번 검색한다 - 층별 분리 모드만 출처 층 이상으로 제한한다
  CallerLayer = doc.source_layer if mode == "split_by_layer" else None
  # 호출이 실패한 문서도 볼트 크기를 로그에 남겨 순차 성장 곡선에서 재집계할 수 있게 검색 직전에 잡는다
  CallVaultSize = len(VaultNotes)
  # 질의는 Shown 하나로 한다 - Shown 이 이미 "제목 : ..." 으로 시작해 제목이 두 번 들어간다
  Candidates = retriever.search(Shown, k, mode, CallerLayer)
  Messages = build_b1_messages(layer_block, mode, doc.source_layer, Shown, Labels, Candidates)
  require_block_in_messages(Messages, layer_block)
  Result = chat_fn(
    Messages, model_id, config, b1_schema(Labels, mode, doc.source_layer, [Cand.id for Cand in Candidates]),
    timeout_seconds=timeout_seconds,
  )

  Drafts = []
  Notes = []
  Error = None
  # "length" 면 잘린 출력이다 - 파싱하지 않고 문서 실패로 기록한다
  if Result.finish_reason != "stop":
    Error = f"finish_reason:{Result.finish_reason}"
  else:
    try:
      Drafts, Notes = _parse_call_output(Result.text, LabelMap, TextById)
    except DecompositionOutputError as Failure:
      Error = str(Failure)
  Log.append(_entry(BaseLog, {
    "entry_type": "b1_call",
    "doc_id": doc.doc_id,
    "vault_size_before": CallVaultSize,
    "source_layer": doc.source_layer,
    "source_group": doc.source_group,
    "doc_view_sha256": hashlib.sha256(Shown.encode("utf-8")).hexdigest(),
    "layer_block_sha256": layer_block_sha256,
    "label_map": LabelMap,
    "ok": Error is None,
    "error": Error,
    "notes": [{"title": Draft.title, "source_segment_ids": Draft.source_segment_ids} for Draft in Drafts],
    "coverage": coverage(LabelMap, Drafts) if Error is None else None,
    "candidates": [{"id": Cand.id, "layer": Cand.layer, "title": Cand.title} for Cand in Candidates],
    **_chat_fields(Result),
  }))
  if Error is not None:
    return Log

  CandidateLog = [{"id": Cand.id, "layer": Cand.layer, "title": Cand.title} for Cand in Candidates]
  for NoteIndex, (Draft, Note) in enumerate(zip(Drafts, Notes)):
    VaultSize = len(VaultNotes)
    Raw = {Key: Note.get(Key) for Key in ("layer", "upward_links", "downward_links", "rationale")}
    # ValueError ( 층별 분리 모드의 출처 위 판정 등 ) 는 마지막 방어선이라 올린다
    Validation = validate_placement(Raw, mode, doc.source_layer, Candidates)
    Problems = list(Validation.problems)
    NoteId = None
    Links = []
    if not Problems:
      Record = build_note_record(Draft, Validation.verdict, doc, NoteIndex, VaultSize, LayerGroupById, Owners)
      NoteId = Record.note_id
      Links = [asdict(Link) for Link in Record.downward_conditional_links]
      VaultNotes.append(Record)
      LayerGroupById[Record.note_id] = (Record.layer, Record.group)
      retriever.add(_to_document_record(Record))
    Verdict = Validation.verdict
    Log.append(_entry(BaseLog, {
      "entry_type": "place",
      "doc_id": doc.doc_id,
      "note_index": NoteIndex,
      "vault_size_before": VaultSize,
      "note_id": NoteId,
      "source_segment_ids": list(Draft.source_segment_ids),
      "candidates": CandidateLog,
      "ok": not Problems,
      "problems": Problems,
      "verdict": None if Verdict is None or Problems else {
        "layer": Verdict.layer,
        "upward_links": Verdict.upward_links,
        "downward_target_ids": Verdict.downward_target_ids,
        "rationale": Verdict.rationale,
      },
      "downward_conditional_links": Links,
      "from_call": True,
      **_NO_CALL_FIELDS,
    }))
  return Log
