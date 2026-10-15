from agent.placement import MODES
from retrieval.search import LAYER_ORDER

def decompose_schema(Labels: list[str]) -> dict:
  # 표지가 없으면 enum 이 비어 어떤 출력도 만들 수 없다
  if not Labels:
    raise ValueError("Labels 가 비어 있다")
  # 연기 시험에서 모델이 없는 표지를 S355 까지 세어 나감 ( 101 · 102단계 ) - 형식으로 막고 ValueError 는 마지막 방어선
  return {
    "type": "object",
    "properties": {
      "notes": {
        "type": "array",
        "minItems": 1,
        "maxItems": len(Labels),
        "items": {
          "type": "object",
          "properties": {
            # 제목은 짧은 구라서 상한을 두어 반복 출력이 끝없이 이어지는 것을 막는다
            "title": {"type": "string", "maxLength": 60},
            "segments": {"type": "array", "minItems": 1, "maxItems": len(Labels), "items": {"type": "string", "enum": list(Labels)}},
          },
          "required": ["title", "segments"],
        },
      }
    },
    "required": ["notes"],
  }


def assign_schema(Labels: list[str]) -> dict:
  # 표지가 없으면 assign 이 비어 어떤 출력도 의미가 없다
  if not Labels:
    raise ValueError("Labels 가 비어 있다")
  Count = len(Labels)
  # 105단계에서 프롬프트 규칙으로는 표지 겹침을 막지 못함 - 표지마다 번호 하나라 겹침 · 없는 표지가 형식상 불가능
  # ( 사용자 결정 (가) 겹침 금지 · 빠짐없이 )
  return {
    "type": "object",
    "properties": {
      "assign": {
        "type": "object",
        "properties": {Label: {"type": "integer", "minimum": 1, "maximum": Count} for Label in Labels},
        "required": list(Labels),
        "additionalProperties": False,
      },
      # 제목은 짧은 구라서 상한을 두어 반복 출력이 끝없이 이어지는 것을 막는다
      "titles": {"type": "array", "minItems": 1, "maxItems": Count, "items": {"type": "string", "maxLength": 60}},
    },
    "required": ["assign", "titles"],
  }


def _check_mode_and_layer(mode: str, source_layer: str) -> None:
  # mode 는 두 값뿐 - 다른 값은 층 규칙 문구를 정할 수 없다
  if mode not in MODES:
    raise ValueError(f"알 수 없는 mode: {mode!r}")
  # 출처 층이 층 순서에 없으면 enum 을 만들 수 없다
  if source_layer not in LAYER_ORDER:
    raise ValueError(f"알 수 없는 source_layer: {source_layer!r}")


def _placement_properties(mode: str, source_layer: str, CandidateIds: list[str]) -> dict:
  # 배치 호출과 B1 호출이 같은 층 enum · 링크 스키마를 쓰도록 한 곳에 둔다
  _check_mode_and_layer(mode, source_layer)
  # 후보 id 가 겹치면 enum 이 모호하고 링크 대상 층도 모호하다
  if len(set(CandidateIds)) != len(CandidateIds):
    raise ValueError(f"후보 id 중복: {CandidateIds}")
  # 연기 시험 103단계에서 후보 0개 배치 출력이 512 토큰에서 잘림 - 링크 대상을 형식으로 막는다
  if CandidateIds:
    LinkSchema = {"type": "array", "maxItems": len(CandidateIds), "items": {"type": "string", "enum": list(CandidateIds)}}
  else:
    LinkSchema = {"type": "array", "maxItems": 0}
  # 고정 결정 : 층별 분리 모드에서 출처 층보다 위 새 노트 금지 - 스키마 enum 으로도 막는다
  if mode == "all_layers":
    Layers = list(LAYER_ORDER)
  else:
    Layers = LAYER_ORDER[: LAYER_ORDER.index(source_layer) + 1]
  return {
    "layer": {"type": "string", "enum": Layers},
    "upward_links": dict(LinkSchema),
    "downward_links": dict(LinkSchema),
    # 근거는 한 문장이라서 상한을 두어 반복 출력이 끝없이 이어지는 것을 막는다
    "rationale": {"type": "string", "maxLength": 200},
  }


def place_schema(mode: str, source_layer: str, CandidateIds: list[str]) -> dict:
  return {
    "type": "object",
    "properties": _placement_properties(mode, source_layer, CandidateIds),
    "required": ["layer", "upward_links", "downward_links", "rationale"],
  }


def b1_schema(Labels: list[str], mode: str, source_layer: str, CandidateIds: list[str]) -> dict:
  # B1 은 분해와 배치를 한 번에 받으므로 assign 은 분해 스키마의 것을, 노트 항목은 배치 스키마의 것을 그대로 쓴다
  Assign = assign_schema(Labels)["properties"]["assign"]
  NoteProperties = {"title": {"type": "string", "maxLength": 60}}
  NoteProperties.update(_placement_properties(mode, source_layer, CandidateIds))
  return {
    "type": "object",
    "properties": {
      "assign": Assign,
      "notes": {
        "type": "array",
        "minItems": 1,
        "maxItems": len(Labels),
        "items": {
          "type": "object",
          "properties": NoteProperties,
          "required": ["title", "layer", "upward_links", "downward_links", "rationale"],
        },
      },
    },
    "required": ["assign", "notes"],
  }


def build_decompose_messages(layer_block: str, source_layer: str, shown: str, Labels: list[str]) -> list[dict]:
  # 규칙 3 문구에 표지 범위를 넣으려면 표지가 하나는 있어야 한다
  if not Labels:
    raise ValueError("Labels 가 비어 있다")
  System = "\n".join([
    "너는 문서를 개념 단위 노트로 나누는 에이전트다. 아래 층 정의를 따른다.",
    "",
    layer_block,
    "",
    "규칙",
    "1. 입력 문서의 세그먼트 표지 [S1], [S2] … 를 묶어 노트를 만든다. 노트 하나는 하나의 개념 · 결정 · 기록을 다룬다.",
    "2. 층 성격 ( 개인 · 팀 · 전사 ) 이 다른 세그먼트는 같은 노트에 묶지 않는다.",
    f"3. assign 에는 표지 ( {Labels[0]} ~ {Labels[-1]} ) 마다 노트 번호를 하나씩 적는다. 번호는 1 부터 쓰고, 같은 노트에 묶을 표지는 같은 번호를 쓴다.",
    "4. titles 에는 노트 번호 순서대로 노트 제목을 짧은 한국어 구로 쓴다.",
    "5. JSON 만 출력한다.",
  ])
  User = f"출처 층 : {source_layer}\n\n{shown}"
  return [{"role": "system", "content": System}, {"role": "user", "content": User}]


def layer_rule_sentence(mode: str, source_layer: str) -> str:
  # 배치 프롬프트와 B1 프롬프트가 같은 층 규칙 문장을 쓰게 한 곳에 둔다
  if mode == "all_layers":
    return f"출처 층은 {source_layer} 이다. 출처 층보다 아래로는 두지 않는다."
  return f"이 에이전트는 출처 층 ( {source_layer} ) 에서만 노트를 만든다. layer 값은 {source_layer} 하나뿐이다."


def candidate_lines(Candidates: list) -> str:
  # 배치 프롬프트와 B1 프롬프트가 같은 후보 줄 형식을 쓰게 한 곳에 둔다
  if not Candidates:
    return "( 없음 )"
  return "\n".join(
    f"- id : {Cand.id} | 층 : {Cand.layer} | 제목 : {Cand.title} | 발췌 : {Cand.excerpt}" for Cand in Candidates
  )


def build_b1_messages(
  layer_block: str, mode: str, source_layer: str, shown: str, Labels: list[str], Candidates: list
) -> list[dict]:
  _check_mode_and_layer(mode, source_layer)
  # 규칙 3 문구에 표지 범위를 넣으려면 표지가 하나는 있어야 한다
  if not Labels:
    raise ValueError("Labels 가 비어 있다")
  System = "\n".join([
    "너는 문서를 개념 단위 노트로 나누고, 각 노트의 층과 링크를 한 번에 정하는 에이전트다. 아래 층 정의를 따른다.",
    "",
    layer_block,
    "",
    "규칙",
    "1. 입력 문서의 세그먼트 표지 [S1], [S2] … 를 묶어 노트를 만든다. 노트 하나는 하나의 개념 · 결정 · 기록을 다룬다.",
    "2. 층 성격 ( 개인 · 팀 · 전사 ) 이 다른 세그먼트는 같은 노트에 묶지 않는다.",
    f"3. assign 에는 표지 ( {Labels[0]} ~ {Labels[-1]} ) 마다 노트 번호를 하나씩 적는다. 번호는 1 부터 쓰고, 같은 노트에 묶을 표지는 같은 번호를 쓴다.",
    "4. notes 에는 노트 번호 순서대로 노트마다 title, layer, upward_links, downward_links, rationale 을 쓴다.",
    "5. title 은 노트 내용을 요약한 짧은 한국어 구로 쓴다.",
    f"6. layer : {layer_rule_sentence(mode, source_layer)}",
    "7. upward_links : 후보 가운데 이 노트와 직접 관련된, 이 노트와 같은 층이거나 더 위층인 노트의 id.",
    "8. downward_links : 후보 가운데 이 노트와 직접 관련된, 이 노트보다 아래층인 노트의 id.",
    "9. 관련 없는 후보는 링크하지 않는다. 없으면 빈 목록이다.",
    "10. rationale : 층과 링크를 정한 이유를 200자 이하 한 문장으로 쓴다.",
    "11. JSON 만 출력한다.",
  ])
  User = f"출처 층 : {source_layer}\n\n{shown}\n\n후보 노트 :\n{candidate_lines(Candidates)}"
  return [{"role": "system", "content": System}, {"role": "user", "content": User}]


def build_place_messages(
  layer_block: str, mode: str, source_layer: str, note_title: str, note_body: str, Candidates: list
) -> list[dict]:
  _check_mode_and_layer(mode, source_layer)
  LayerRule = layer_rule_sentence(mode, source_layer)
  System = "\n".join([
    "너는 새 노트의 층과 링크를 정하는 에이전트다. 아래 층 정의를 따른다.",
    "",
    layer_block,
    "",
    "규칙",
    f"1. 노트의 층을 정한다. {LayerRule}",
    "2. upward_links : 후보 가운데 이 노트와 직접 관련된, 이 노트와 같은 층이거나 더 위층인 노트의 id.",
    "3. downward_links : 후보 가운데 이 노트와 직접 관련된, 이 노트보다 아래층인 노트의 id.",
    "4. 관련 없는 후보는 링크하지 않는다. 없으면 빈 목록이다.",
    "5. rationale : 층과 링크를 정한 이유를 200자 이하 한 문장으로 쓴다.",
    "6. JSON 만 출력한다.",
  ])
  CandidateLines = candidate_lines(Candidates)
  User = (
    f"출처 층 : {source_layer}\n\n노트 제목 : {note_title}\n노트 본문 :\n{note_body}\n\n후보 노트 :\n{CandidateLines}"
  )
  return [{"role": "system", "content": System}, {"role": "user", "content": User}]


def require_block_in_messages(messages: list, layer_block: str) -> None:
  # 기준 §0 : 층 정의 블록이 system 메시지에 그대로 들어가야 한다
  Systems = [Message["content"] for Message in messages if Message.get("role") == "system"]
  if not any(layer_block in Content for Content in Systems):
    raise ValueError("system 메시지에 층 정의 블록이 그대로 들어 있지 않다")
