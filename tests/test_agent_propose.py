import json
import unittest

from agent.decompose import parse_grouping
from agent.llm_client import ChatResult, GenerationConfig
from agent.prompts import (
  build_decompose_messages,
  build_place_messages,
  decompose_schema,
  place_schema,
  require_block_in_messages,
)
from agent.propose import run_propose_doc
from agent.types import SourceDoc, SourceSegment
from retrieval.search import LAYER_ORDER, Retriever

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
_BLOCK = "합성 층 정의 블록\n- 합성 조항"
_BLOCK_SHA = "0" * 64
_OWNERS = {"주인A"}
_CONFIG = GenerationConfig(temperature=0.0, seed=1, max_tokens=64, enable_thinking=False)
_BASE_LOG = {"trial_id": "t1", "seed": 1, "condition": "합성", "mode_tag": "m", "k_tag": 4}
_DOC = SourceDoc(
  doc_id="문서A",
  title="합성 제목",
  source_layer="팀",
  source_group="그룹A",
  # seq 를 일부러 뒤섞어 본문이 seq 순서로 이어지는지 본다
  segments=[
    SourceSegment(segment_id="세그C", seq=3, text="셋째 글"),
    SourceSegment(segment_id="세그A", seq=1, text="첫째 글"),
    SourceSegment(segment_id="세그B", seq=2, text="둘째 글"),
  ],
)


def _embed_backend(Texts: list[str]) -> list[list[float]]:
  # 합성 임베딩 - 글자 수와 특정 글자 개수로 만든 3차원 벡터이며 서버를 부르지 않는다
  return [[float(len(Text) % 7 + 1), float(Text.count("첫") + 1), float(Text.count("셋") + 1)] for Text in Texts]


def _result(Text, FinishReason="stop") -> ChatResult:
  return ChatResult(
    text=Text if isinstance(Text, str) else json.dumps(Text, ensure_ascii=False),
    finish_reason=FinishReason,
    prompt_tokens=10,
    completion_tokens=5,
    elapsed_seconds=0.5,
    timings=None,
    request_body={},
    response_body={},
  )


class FakeChat:
  # 호출 순서대로 미리 정한 결과를 돌려주고 받은 messages · schema 를 기록한다
  def __init__(self, Results: list) -> None:
    self.Results = list(Results)
    self.Calls = []

  def __call__(self, messages, model_id, config, response_schema, *, timeout_seconds):
    self.Calls.append({"messages": messages, "schema": response_schema, "model_id": model_id})
    return self.Results.pop(0)


def _place(Layer="팀", Up=None, Down=None) -> dict:
  return {"layer": Layer, "upward_links": Up or [], "downward_links": Down or [], "rationale": "합성 근거"}


def _run(Chat, mode="all_layers", Doc=_DOC):
  Retr = Retriever(embed_backend=_embed_backend)
  VaultNotes = []
  LayerGroupById = {}
  Log = run_propose_doc(
    Doc, mode, 4, Retr, VaultNotes, LayerGroupById, Chat, "합성모델", _CONFIG, _CONFIG,
    _BLOCK, _BLOCK_SHA, _OWNERS, 9, _BASE_LOG,
  )
  return Log, VaultNotes, LayerGroupById, Retr


_TWO_NOTES = {"notes": [{"title": "노트1", "segments": ["S2", "S1"]}, {"title": "노트2", "segments": ["S3"]}]}


class ParseGroupingTest(unittest.TestCase):
  def test_body_is_segment_texts_in_seq_order(self) -> None:
    LabelMap = {"S1": "세그A", "S2": "세그B", "S3": "세그C"}
    TextById = {"세그A": "첫째 글", "세그B": "둘째 글", "세그C": "셋째 글"}
    Drafts = parse_grouping(json.dumps(_TWO_NOTES, ensure_ascii=False), LabelMap, TextById)
    self.assertEqual(Drafts[0].source_segment_ids, ["세그A", "세그B"])
    self.assertEqual(Drafts[0].body, "첫째 글\n\n둘째 글")
    self.assertEqual(Drafts[1].body, "셋째 글")


class RunProposeDocTest(unittest.TestCase):
  def test_all_layers_normal_flow(self) -> None:
    Chat = FakeChat([_result(_TWO_NOTES), _result(_place()), _result(_place(Up=["문서A#n0"]))])
    Log, VaultNotes, LayerGroupById, Retr = _run(Chat)
    self.assertEqual([Entry["entry_type"] for Entry in Log], ["decompose", "place", "place"])
    self.assertEqual(VaultNotes[0].body, "첫째 글\n\n둘째 글")
    self.assertEqual(VaultNotes[1].body, "셋째 글")
    # 둘째 노트의 검색 후보에 첫째 노트가 있다
    self.assertEqual([Cand["id"] for Cand in Log[2]["candidates"]], ["문서A#n0"])
    self.assertEqual(Log[2]["vault_size_before"], 1)
    self.assertEqual(LayerGroupById, {"문서A#n0": ("팀", "그룹A"), "문서A#n1": ("팀", "그룹A")})
    self.assertEqual(len(Retr.Index), 2)
    self.assertEqual(VaultNotes[1].upward_links, ["문서A#n0"])

  def test_split_by_layer_schema_enum_and_prompt_rule(self) -> None:
    Chat = FakeChat([_result({"notes": [{"title": "노트1", "segments": ["S1"]}]}), _result(_place())])
    _run(Chat, mode="split_by_layer")
    Enum = Chat.Calls[1]["schema"]["properties"]["layer"]["enum"]
    self.assertEqual(Enum, ["개인", "팀"])
    self.assertIn("이 에이전트는 출처 층 ( 팀 ) 에서만 노트를 만든다. layer 값은 팀 하나뿐이다.", Chat.Calls[1]["messages"][0]["content"])

  def test_all_layers_schema_enum_is_every_layer(self) -> None:
    self.assertEqual(place_schema("all_layers", "팀")["properties"]["layer"]["enum"], LAYER_ORDER)

  def test_split_by_layer_layer_above_source_raises_value_error(self) -> None:
    Chat = FakeChat([_result({"notes": [{"title": "노트1", "segments": ["S1"]}]}), _result(_place(Layer="전사"))])
    with self.assertRaises(ValueError):
      _run(Chat, mode="split_by_layer")

  def test_decompose_finish_reason_length_is_recorded_as_failure(self) -> None:
    Log, VaultNotes, _, _ = _run(FakeChat([_result(_TWO_NOTES, FinishReason="length")]))
    self.assertEqual(len(Log), 1)
    self.assertFalse(Log[0]["ok"])
    self.assertEqual(Log[0]["error"], "finish_reason:length")
    self.assertEqual(VaultNotes, [])

  def test_decompose_not_json_is_recorded_as_failure(self) -> None:
    Log, VaultNotes, _, _ = _run(FakeChat([_result("JSON 아님")]))
    self.assertFalse(Log[0]["ok"])
    self.assertIn("JSON 이 아니다", Log[0]["error"])
    self.assertEqual(VaultNotes, [])

  def test_decompose_empty_segments_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      _run(FakeChat([_result({"notes": [{"title": "노트1", "segments": []}]})]))

  def test_place_link_error_fails_only_that_note(self) -> None:
    Chat = FakeChat([_result(_TWO_NOTES), _result(_place(Up=["없는-id"])), _result(_place())])
    Log, VaultNotes, _, _ = _run(Chat)
    self.assertFalse(Log[1]["ok"])
    self.assertEqual(Log[1]["problems"], ["upward_links_unknown_id:없는-id"])
    self.assertIsNone(Log[1]["note_id"])
    self.assertTrue(Log[2]["ok"])
    self.assertEqual([Note.note_id for Note in VaultNotes], ["문서A#n1"])

  def test_place_finish_reason_length_fails_only_that_note(self) -> None:
    Chat = FakeChat([_result(_TWO_NOTES), _result(_place(), FinishReason="length"), _result(_place())])
    Log, VaultNotes, _, _ = _run(Chat)
    self.assertEqual(Log[1]["problems"], ["finish_reason:length"])
    self.assertEqual(len(VaultNotes), 1)

  def test_place_not_json_fails_only_that_note(self) -> None:
    Chat = FakeChat([_result(_TWO_NOTES), _result("JSON 아님"), _result(_place())])
    Log, VaultNotes, _, _ = _run(Chat)
    self.assertEqual(Log[1]["problems"], ["not_json"])
    self.assertEqual(len(VaultNotes), 1)

  def test_every_system_message_contains_layer_block(self) -> None:
    Chat = FakeChat([_result(_TWO_NOTES), _result(_place()), _result(_place())])
    _run(Chat)
    for Call in Chat.Calls:
      self.assertIn(_BLOCK, Call["messages"][0]["content"])

  def test_every_log_entry_has_base_log_keys(self) -> None:
    Chat = FakeChat([_result(_TWO_NOTES), _result(_place()), _result(_place(Up=["없는-id"]))])
    Log, _, _, _ = _run(Chat)
    for Entry in Log:
      for Key, Value in _BASE_LOG.items():
        self.assertEqual(Entry[Key], Value)

  def test_base_log_key_collision_raises_value_error(self) -> None:
    Retr = Retriever(embed_backend=_embed_backend)
    with self.assertRaises(ValueError):
      run_propose_doc(
        _DOC, "all_layers", 4, Retr, [], {}, FakeChat([_result(_TWO_NOTES)]), "합성모델", _CONFIG, _CONFIG,
        _BLOCK, _BLOCK_SHA, _OWNERS, 9, {"entry_type": "x"},
      )

  def test_unknown_mode_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      _run(FakeChat([]), mode="other_mode")


class DecomposeSchemaTest(unittest.TestCase):
  def test_enum_and_limits_follow_labels(self) -> None:
    Schema = decompose_schema(["S1", "S2", "S3"])
    Notes = Schema["properties"]["notes"]
    self.assertEqual(Notes["maxItems"], 3)
    self.assertEqual(Notes["minItems"], 1)
    self.assertEqual(Notes["items"]["properties"]["title"]["maxLength"], 60)
    Segments = Notes["items"]["properties"]["segments"]
    self.assertEqual(Segments["maxItems"], 3)
    self.assertEqual(Segments["items"], {"type": "string", "enum": ["S1", "S2", "S3"]})

  def test_empty_labels_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      decompose_schema([])
    with self.assertRaises(ValueError):
      build_decompose_messages(_BLOCK, "팀", "보임", [])

  def test_rule_three_mentions_label_range(self) -> None:
    Messages = build_decompose_messages(_BLOCK, "팀", "보임", ["S1", "S2", "S3"])
    self.assertIn("3. 모든 노트는 입력에 있는 표지 ( S1 ~ S3 ) 를 1개 이상 가진다. 다른 표지는 쓰지 않는다.", Messages[0]["content"])

  def test_run_propose_doc_passes_document_labels_to_decompose_call(self) -> None:
    Chat = FakeChat([_result(_TWO_NOTES), _result(_place()), _result(_place())])
    _run(Chat)
    Segments = Chat.Calls[0]["schema"]["properties"]["notes"]["items"]["properties"]["segments"]
    self.assertEqual(Segments["items"]["enum"], ["S1", "S2", "S3"])
    self.assertEqual(Chat.Calls[0]["schema"]["properties"]["notes"]["maxItems"], 3)
    self.assertIn("( S1 ~ S3 )", Chat.Calls[0]["messages"][0]["content"])


class RequireBlockTest(unittest.TestCase):
  def test_missing_block_raises_value_error(self) -> None:
    Messages = build_decompose_messages(_BLOCK, "팀", "보임", ["S1", "S2"])
    require_block_in_messages(Messages, _BLOCK)
    with self.assertRaises(ValueError):
      require_block_in_messages(Messages, "다른 블록")

  def test_block_only_in_user_message_raises_value_error(self) -> None:
    Messages = [{"role": "system", "content": "블록 없음"}, {"role": "user", "content": _BLOCK}]
    with self.assertRaises(ValueError):
      require_block_in_messages(Messages, _BLOCK)

  def test_place_messages_list_candidates_or_none(self) -> None:
    from retrieval.types import Candidate
    Empty = build_place_messages(_BLOCK, "all_layers", "팀", "제목", "본문", [])
    self.assertTrue(Empty[1]["content"].endswith("후보 노트 :\n( 없음 )"))
    Cands = [Candidate(id="a", layer="팀", title="t", excerpt="e")]
    Filled = build_place_messages(_BLOCK, "all_layers", "팀", "제목", "본문", Cands)
    self.assertTrue(Filled[1]["content"].endswith("- id : a | 층 : 팀 | 제목 : t | 발췌 : e"))


if __name__ == "__main__":
  unittest.main()
