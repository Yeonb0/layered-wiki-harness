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


def parse_grouping(raw_text: str, LabelMap: dict, TextById: dict) -> list[NoteDraft]:
  # 모델은 제목과 세그먼트 묶음만 낸다 - 본문은 근거 세그먼트 원문을 seq 순서로 이어 붙인다 ( 사용자 결정 )
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

  # LabelMap 은 seq 순서로 만들어지므로 키 순서가 곧 seq 순서다
  Order = {Label: Position for Position, Label in enumerate(LabelMap)}
  Drafts = []
  for RawNote in RawNotes:
    # 노트 하나는 객체여야 한다
    if not isinstance(RawNote, dict):
      raise DecompositionOutputError("노트가 객체가 아니다")
    Title = _require_text(RawNote.get("title"), "title")
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
    SegmentIds = [LabelMap[L] for L in sorted(Labels, key=lambda L: Order[L])]
    # 본문을 만들 원문이 없는 세그먼트는 본문이 조용히 비게 된다
    Missing = [SegId for SegId in SegmentIds if SegId not in TextById]
    if Missing:
      raise ValueError(f"TextById 에 없는 segment_id: {Missing}")
    Body = "\n\n".join(TextById[SegId] for SegId in SegmentIds)
    Drafts.append(NoteDraft(title=Title, body=Body, source_segment_ids=SegmentIds))
  # 사용자 결정 (가) 표지 하나는 노트 하나에만 - 노트 본문이 원문 연결이라 겹치면 원문이 중복된다
  # 하니스가 고쳐서 넘기지 않고 실패로 기록한다 ( 모든 노트를 읽은 뒤에 본다 )
  Seen = {}
  for Draft in Drafts:
    for SegId in Draft.source_segment_ids:
      Seen[SegId] = Seen.get(SegId, 0) + 1
  Overlapped = [SegId for SegId, Count in Seen.items() if Count > 1]
  if Overlapped:
    OverlappedLabels = [Label for Label in LabelMap if LabelMap[Label] in Overlapped]
    raise DecompositionOutputError(f"표지가 두 노트 이상에 있다: {OverlappedLabels}")
  return Drafts


def parse_assignment(raw_text: str, LabelMap: dict, TextById: dict) -> list[NoteDraft]:
  # 모델은 표지마다 노트 번호 하나와 노트 제목만 낸다 - 겹침 · 빠짐은 형식상 불가능하거나 출력 오류로 걸러진다
  try:
    Parsed = json.loads(raw_text)
  except json.JSONDecodeError as Error:
    # 모델 출력이 JSON 이 아니면 러너가 실패로 기록한다
    raise DecompositionOutputError(f"JSON 이 아니다: {Error}") from Error
  # 최상위는 assign 과 titles 키를 가진 객체여야 한다
  if not isinstance(Parsed, dict) or "assign" not in Parsed or "titles" not in Parsed:
    raise DecompositionOutputError("assign 이나 titles 키가 없다")
  return build_drafts_from_assignment(Parsed["assign"], Parsed["titles"], LabelMap, TextById)


def build_drafts_from_assignment(Assign, Titles, LabelMap: dict, TextById: dict) -> list[NoteDraft]:
  # 분해 호출과 B1 호출이 같은 검증 · 노트 구성을 쓰도록 JSON 파싱 뒤의 부분을 따로 둔다
  # assign 은 객체, titles 는 문자열 목록이어야 한다
  if not isinstance(Assign, dict):
    raise DecompositionOutputError("assign 이 객체가 아니다")
  if not isinstance(Titles, list) or not all(isinstance(T, str) for T in Titles):
    raise DecompositionOutputError("titles 가 문자열 목록이 아니다")
  # 제목이 하나도 없으면 노트가 하나도 없다
  if len(Titles) == 0:
    raise DecompositionOutputError("titles 가 비어 있다")
  # 지침 3 절 : 없는 id 를 가리키면 멈춘다
  Unknown = [Label for Label in Assign if Label not in LabelMap]
  if Unknown:
    raise ValueError(f"표지에 없는 assign 키: {Unknown}")
  # 사용자 결정 : 모든 세그먼트가 노트에 들어간다 - 빠진 표지는 출력 오류다
  Missing = [Label for Label in LabelMap if Label not in Assign]
  if Missing:
    raise DecompositionOutputError(f"assign 에 빠진 표지: {Missing}")
  for Label, Number in Assign.items():
    # bool 은 int 의 하위 형이라 따로 거른다
    if not isinstance(Number, int) or isinstance(Number, bool):
      raise DecompositionOutputError(f"노트 번호가 정수가 아니다: {Label}")
    # 번호는 제목 개수 안에 있어야 노트에 대응한다
    if Number < 1 or Number > len(Titles):
      raise DecompositionOutputError(f"노트 번호가 범위 밖이다: {Label} = {Number}")
  # 표지 없이 제목만 있는 번호는 노트가 아니라 출력 오류다
  if set(Assign.values()) != set(range(1, len(Titles) + 1)):
    raise DecompositionOutputError("쓰인 번호가 1 부터 제목 개수까지 빠짐없지 않다")

  # LabelMap 은 seq 순서로 만들어지므로 키 순서가 곧 seq 순서다
  Drafts = []
  for Number, Title in enumerate(Titles, start=1):
    _require_text(Title, "title")
    SegmentIds = [LabelMap[Label] for Label in LabelMap if Assign[Label] == Number]
    # 본문을 만들 원문이 없는 세그먼트는 본문이 조용히 비게 된다
    NoText = [SegId for SegId in SegmentIds if SegId not in TextById]
    if NoText:
      raise ValueError(f"TextById 에 없는 segment_id: {NoText}")
    Body = "\n\n".join(TextById[SegId] for SegId in SegmentIds)
    Drafts.append(NoteDraft(title=Title, body=Body, source_segment_ids=SegmentIds))
  return Drafts
