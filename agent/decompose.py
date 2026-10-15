import json

from agent.types import NoteDraft, SourceDoc


class DecompositionOutputError(Exception):
  # 모델 출력 형식 오류 - ValueError 가 아니다 ( 러너가 실패로 기록할 대상 )
  pass


def build_segment_labels(doc: SourceDoc) -> tuple[dict, str]:
  # 세그먼트가 없으면 분해할 입력이 없다
  if not doc.segments:
    raise ValueError(f"세그먼트가 없는 문서: {doc.doc_id}")
  Ordered = sorted(doc.segments, key=lambda Seg: Seg.seq)
  # 같은 seq 가 있으면 표지 순서가 입력 순서에 따라 달라진다
  if len({Seg.seq for Seg in Ordered}) != len(Ordered):
    raise ValueError(f"세그먼트 seq 중복: {doc.doc_id}")
  LabelMap = {}
  Blocks = []
  for Index, Seg in enumerate(Ordered, start=1):
    Label = f"S{Index}"
    LabelMap[Label] = Seg.segment_id
    Blocks.append(f"[{Label}]\n{Seg.text}")
  Shown = f"제목 : {doc.title}\n\n" + "\n\n".join(Blocks)
  return LabelMap, Shown


def _require_text(Value, name: str) -> str:
  # title · body 가 빈 문자열이거나 문자열이 아니면 노트로 쓸 수 없다
  if not isinstance(Value, str) or Value.strip() == "":
    raise DecompositionOutputError(f"{name} 가 비어 있거나 문자열이 아니다")
  return Value


def parse_decomposition(raw_text: str, LabelMap: dict) -> list[NoteDraft]:
  try:
    Parsed = json.loads(raw_text)
  except json.JSONDecodeError as Error:
    # 모델 출력이 JSON 이 아니면 러너가 실패로 기록한다
    raise DecompositionOutputError(f"JSON 이 아니다: {Error}") from Error
  # 최상위는 notes 키를 가진 객체여야 한다
  if not isinstance(Parsed, dict) or "notes" not in Parsed:
    raise DecompositionOutputError("notes 키가 없다")
  RawNotes = Parsed["notes"]
  # notes 가 목록이 아니거나 비면 노트가 하나도 없다
  if not isinstance(RawNotes, list) or len(RawNotes) == 0:
    raise DecompositionOutputError("notes 가 빈 목록이거나 목록이 아니다")

  Drafts = []
  for RawNote in RawNotes:
    # 노트 하나는 객체여야 한다
    if not isinstance(RawNote, dict):
      raise DecompositionOutputError("노트가 객체가 아니다")
    Title = _require_text(RawNote.get("title"), "title")
    Body = _require_text(RawNote.get("body"), "body")
    Labels = RawNote.get("segments")
    # segments 는 문자열 목록이어야 한다
    if not isinstance(Labels, list) or not all(isinstance(L, str) for L in Labels):
      raise DecompositionOutputError("segments 가 문자열 목록이 아니다")
    # 한 노트 안 표지 중복은 출처 기록이 부풀려진다
    if len(set(Labels)) != len(Labels):
      raise DecompositionOutputError(f"한 노트 안 표지 중복: {Labels}")
    # 지침 3 절 : source_segment_ids 가 비면 멈춘다
    if len(Labels) == 0:
      raise ValueError(f"노트의 segments 가 비어 있다: {Title!r}")
    # 지침 3 절 : 없는 id 를 가리키면 멈춘다
    Unknown = [L for L in Labels if L not in LabelMap]
    if Unknown:
      raise ValueError(f"표지에 없는 segments: {Unknown}")
    Drafts.append(NoteDraft(title=Title, body=Body, source_segment_ids=[LabelMap[L] for L in Labels]))
  return Drafts


def coverage(LabelMap: dict, Drafts: list[NoteDraft]) -> dict:
  # 기록용 - 검사가 아니다 ( 어느 노트에도 안 들어간 세그먼트를 남긴다 )
  Used = {SegId for Draft in Drafts for SegId in Draft.source_segment_ids}
  AllIds = list(LabelMap.values())
  Uncovered = [SegId for SegId in AllIds if SegId not in Used]
  return {"segments": len(AllIds), "covered": len(AllIds) - len(Uncovered), "uncovered_ids": Uncovered}
