import json
import unittest

from agent.llm_client import ChatResult, GenerationConfig
from agent.prompts import b1_schema, place_schema
from agent.propose import run_propose_doc
from agent.types import SourceDoc, SourceSegment
from retrieval.search import Retriever
from retrieval.types import Candidate
from vault.types import DocumentRecord

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
_OWNERS = {"주인A"}
_BLOCK = "합성 층 정의 블록\n- 합성 조항"
_BLOCK_SHA = "0" * 64
_CONFIG = GenerationConfig(temperature=0.0, seed=1, max_tokens=64, enable_thinking=False)
_EMPTY = {"type": "array", "maxItems": 0}


def _cand(Id: str, Layer: str) -> Candidate:
  return Candidate(id=Id, layer=Layer, title="합성", excerpt="합성")


def _enum(Link: dict) -> list:
  return Link["items"]["enum"]


class LinkEnumTest(unittest.TestCase):
  def _links(self, Mode, SourceLayer, Candidates):
    Props = place_schema(Mode, SourceLayer, Candidates)["properties"]
    return Props["upward_links"], Props["downward_links"]

  def test_all_layers_team_source(self) -> None:
    Up, Down = self._links("all_layers", "팀", [_cand("a", "개인"), _cand("b", "팀"), _cand("c", "전사")])
    self.assertEqual(_enum(Up), ["b", "c"])
    self.assertEqual(Up["maxItems"], 2)
    self.assertEqual(_enum(Down), ["a", "b"])
    self.assertEqual(Down["maxItems"], 2)

  def test_all_layers_personal_source(self) -> None:
    Up, Down = self._links("all_layers", "개인", [_cand("a", "개인"), _cand("b", "팀"), _cand("c", "전사")])
    self.assertEqual(_enum(Up), ["a", "b", "c"])
    self.assertEqual(_enum(Down), ["a", "b"])

  def test_split_by_layer_team_source_has_no_downward_target(self) -> None:
    Up, Down = self._links("split_by_layer", "팀", [_cand("b", "팀"), _cand("c", "전사")])
    self.assertEqual(_enum(Up), ["b", "c"])
    self.assertEqual(Down, _EMPTY)

  def test_no_candidates_gives_empty_both_directions(self) -> None:
    Up, Down = self._links("all_layers", "팀", [])
    self.assertEqual((Up, Down), (_EMPTY, _EMPTY))

  def test_only_lower_candidates_gives_empty_upward(self) -> None:
    Up, Down = self._links("all_layers", "팀", [_cand("a", "개인")])
    self.assertEqual(Up, _EMPTY)
    self.assertEqual(_enum(Down), ["a"])

  def test_unknown_candidate_layer_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      place_schema("all_layers", "팀", [_cand("a", "없는층")])
    with self.assertRaises(ValueError):
      b1_schema(["S1"], "all_layers", "팀", [_cand("a", "없는층")])

  def test_b1_note_item_has_same_link_schema_as_place(self) -> None:
    Candidates = [_cand("a", "개인"), _cand("b", "팀"), _cand("c", "전사")]
    for Mode in ("all_layers", "split_by_layer"):
      Visible = Candidates if Mode == "all_layers" else Candidates[1:]
      Item = b1_schema(["S1", "S2"], Mode, "팀", Visible)["properties"]["notes"]["items"]["properties"]
      Place = place_schema(Mode, "팀", Visible)["properties"]
      for Key in ("layer", "upward_links", "downward_links", "rationale"):
        self.assertEqual(Item[Key], Place[Key])


def _result(Obj) -> ChatResult:
  return ChatResult(
    text=json.dumps(Obj, ensure_ascii=False), finish_reason="stop", prompt_tokens=10, completion_tokens=5,
    elapsed_seconds=0.1, timings=None, request_body={}, response_body={},
  )


class RecordingChat:
  # 받은 스키마를 기록하고 링크 없는 합성 출력을 낸다
  def __init__(self) -> None:
    self.Schemas = []

  def __call__(self, messages, model_id, config, response_schema, *, timeout_seconds):
    self.Schemas.append(response_schema)
    Props = response_schema["properties"]
    if "assign" in Props:
      return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["합성 노트"]})
    return _result({"layer": "팀", "upward_links": [], "downward_links": [], "rationale": "합성 근거"})


def _embed_backend(Texts: list[str]) -> list[list[float]]:
  # 합성 임베딩 - 글자 수로 만든 2차원 벡터이며 서버를 부르지 않는다
  return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


def _doc(Id: str) -> SourceDoc:
  return SourceDoc(
    doc_id=Id, title=f"{Id} 제목", source_layer="팀", source_group="그룹A",
    segments=[SourceSegment(segment_id=f"{Id}-s1", seq=1, text=f"{Id} 합성 글")],
  )


def _run(Mode, Retr, Doc, VaultNotes):
  Chat = RecordingChat()
  run_propose_doc(
    Doc, Mode, 10, Retr, VaultNotes, {}, Chat, "합성모델", _CONFIG, _CONFIG, _BLOCK, _BLOCK_SHA, _OWNERS, 9,
    {"trial_id": "t"},
  )
  return Chat.Schemas


class RegressionTest(unittest.TestCase):
  def test_personal_candidate_is_not_in_upward_enum_for_team_source(self) -> None:
    # 출처 팀 문서의 전 층 모드 배치 스키마에서 후보 개인 노트는 상향 링크 대상이 아니다
    Retr = Retriever(embed_backend=_embed_backend)
    Retr.add(DocumentRecord(
      id="개인노트", layer="개인", title="개인 제목", body="개인 본문", upward_links=[], downward_conditional_links=[],
      inserted_at_vault_size=0,
    ), group="주인A")
    Schemas = _run("all_layers", Retr, _doc("문서A"), [])
    PlaceSchema = Schemas[1]
    self.assertEqual(PlaceSchema["properties"]["upward_links"], _EMPTY)
    self.assertEqual(_enum(PlaceSchema["properties"]["downward_links"]), ["개인노트"])

  def test_previous_note_of_same_doc_is_not_in_downward_enum_in_split_by_layer(self) -> None:
    # 층별 분리 모드에서 앞 노트 ( 같은 층 ) 는 하향 링크 대상이 아니다
    Retr = Retriever(embed_backend=_embed_backend)
    Retr.add(DocumentRecord(
      id="앞노트", layer="팀", title="앞 제목", body="앞 본문", upward_links=[], downward_conditional_links=[],
      inserted_at_vault_size=0,
    ), group="그룹A")
    Schemas = _run("split_by_layer", Retr, _doc("문서A"), [])
    PlaceSchema = Schemas[1]
    self.assertEqual(_enum(PlaceSchema["properties"]["upward_links"]), ["앞노트"])
    self.assertEqual(PlaceSchema["properties"]["downward_links"], _EMPTY)


if __name__ == "__main__":
  unittest.main()
