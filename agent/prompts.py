from agent.placement import MODES
from retrieval.search import LAYER_ORDER

DECOMPOSE_SCHEMA = {
  "type": "object",
  "properties": {
    "notes": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "segments": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        },
        "required": ["title", "segments"],
      },
    }
  },
  "required": ["notes"],
}


def _check_mode_and_layer(mode: str, source_layer: str) -> None:
  # mode 는 두 값뿐 - 다른 값은 층 규칙 문구를 정할 수 없다
  if mode not in MODES:
    raise ValueError(f"알 수 없는 mode: {mode!r}")
  # 출처 층이 층 순서에 없으면 enum 을 만들 수 없다
  if source_layer not in LAYER_ORDER:
    raise ValueError(f"알 수 없는 source_layer: {source_layer!r}")


def place_schema(mode: str, source_layer: str) -> dict:
  _check_mode_and_layer(mode, source_layer)
  # 고정 결정 : 층별 분리 모드에서 출처 층보다 위 새 노트 금지 - 스키마 enum 으로도 막는다
  if mode == "all_layers":
    Layers = list(LAYER_ORDER)
  else:
    Layers = LAYER_ORDER[: LAYER_ORDER.index(source_layer) + 1]
  return {
    "type": "object",
    "properties": {
      "layer": {"type": "string", "enum": Layers},
      "upward_links": {"type": "array", "items": {"type": "string"}},
      "downward_links": {"type": "array", "items": {"type": "string"}},
      "rationale": {"type": "string"},
    },
    "required": ["layer", "upward_links", "downward_links", "rationale"],
  }


def build_decompose_messages(layer_block: str, source_layer: str, shown: str) -> list[dict]:
  System = "\n".join([
    "너는 문서를 개념 단위 노트로 나누는 에이전트다. 아래 층 정의를 따른다.",
    "",
    layer_block,
    "",
    "규칙",
    "1. 입력 문서의 세그먼트 표지 [S1], [S2] … 를 묶어 노트를 만든다. 노트 하나는 하나의 개념 · 결정 · 기록을 다룬다.",
    "2. 층 성격 ( 개인 · 팀 · 전사 ) 이 다른 세그먼트는 같은 노트에 묶지 않는다.",
    "3. 모든 노트는 입력에 있는 표지를 1개 이상 가진다.",
    "4. 노트 제목은 내용을 요약한 짧은 한국어 구로 쓴다.",
    "5. JSON 만 출력한다.",
  ])
  User = f"출처 층 : {source_layer}\n\n{shown}"
  return [{"role": "system", "content": System}, {"role": "user", "content": User}]


def build_place_messages(
  layer_block: str, mode: str, source_layer: str, note_title: str, note_body: str, Candidates: list
) -> list[dict]:
  _check_mode_and_layer(mode, source_layer)
  if mode == "all_layers":
    LayerRule = f"출처 층은 {source_layer} 이다. 출처 층보다 아래로는 두지 않는다."
  else:
    LayerRule = f"이 에이전트는 출처 층 ( {source_layer} ) 에서만 노트를 만든다. layer 값은 {source_layer} 하나뿐이다."
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
    "5. rationale : 층과 링크를 정한 이유를 한 문장으로 쓴다.",
    "6. JSON 만 출력한다.",
  ])
  if Candidates:
    CandidateLines = "\n".join(
      f"- id : {Cand.id} | 층 : {Cand.layer} | 제목 : {Cand.title} | 발췌 : {Cand.excerpt}" for Cand in Candidates
    )
  else:
    CandidateLines = "( 없음 )"
  User = (
    f"출처 층 : {source_layer}\n\n노트 제목 : {note_title}\n노트 본문 :\n{note_body}\n\n후보 노트 :\n{CandidateLines}"
  )
  return [{"role": "system", "content": System}, {"role": "user", "content": User}]


def require_block_in_messages(messages: list, layer_block: str) -> None:
  # 기준 §0 : 층 정의 블록이 system 메시지에 그대로 들어가야 한다
  Systems = [Message["content"] for Message in messages if Message.get("role") == "system"]
  if not any(layer_block in Content for Content in Systems):
    raise ValueError("system 메시지에 층 정의 블록이 그대로 들어 있지 않다")
