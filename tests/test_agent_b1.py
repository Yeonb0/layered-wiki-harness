import json
import unittest

from agent.b1 import run_b1_doc
from agent.llm_client import ChatResult, GenerationConfig
from agent.prompts import b1_schema, build_b1_messages, build_place_messages, layer_rule_sentence, place_schema, assign_schema
from agent.decompose import build_segment_labels
from agent.types import SourceDoc, SourceSegment
from retrieval.search import LAYER_ORDER, Retriever
from vault.types import DocumentRecord

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


def _note(Title="노트", Layer="팀", Up=None, Down=None) -> dict:
  return {"title": Title, "layer": Layer, "upward_links": Up or [], "downward_links": Down or [], "rationale": "합성 근거"}


def _output(Notes=None, Assign=None) -> dict:
  return {
    "assign": {"S1": 1, "S2": 1, "S3": 2} if Assign is None else Assign,
    "notes": [_note("노트1"), _note("노트2")] if Notes is None else Notes,
  }


class SpyRetriever(Retriever):
  # search_visible 를 감싸 질의 · 모드 · 호출 층 · 호출 그룹을 기록한다
  def __init__(self, embed_backend) -> None:
    super().__init__(embed_backend=embed_backend)
    self.Searches = []

  def search_visible(self, query, k, mode, caller_layer, caller_group, owners):
    self.Searches.append({"query": query, "mode": mode, "caller_layer": caller_layer, "caller_group": caller_group})
    return super().search_visible(query, k, mode, caller_layer, caller_group, owners)


def _record(Id: str, Layer: str) -> DocumentRecord:
  return DocumentRecord(id=Id, layer=Layer, title=f"{Id} 제목", body=f"{Id} 본문", upward_links=[], downward_conditional_links=[], inserted_at_vault_size=0)


def _run(Chat, mode="all_layers", Retr=None, Doc=_DOC, VaultNotes=None):
  Retr = Retr or Retriever(embed_backend=_embed_backend)
  VaultNotes = [] if VaultNotes is None else VaultNotes
  LayerGroupById = {}
  Log = run_b1_doc(
    Doc, mode, 4, Retr, VaultNotes, LayerGroupById, Chat, "합성모델", _CONFIG,
    _BLOCK, _BLOCK_SHA, _OWNERS, 9, _BASE_LOG,
  )
  return Log, VaultNotes, LayerGroupById, Retr


class RunB1DocTest(unittest.TestCase):
  def test_normal_flow_two_notes_from_one_call(self) -> None:
    Chat = FakeChat([_result(_output())])
    Log, VaultNotes, LayerGroupById, Retr = _run(Chat)
    self.assertEqual(len(Chat.Calls), 1)
    self.assertEqual([Entry["entry_type"] for Entry in Log], ["b1_call", "place", "place"])
    self.assertEqual(VaultNotes[0].body, "첫째 글\n\n둘째 글")
    self.assertEqual(VaultNotes[1].body, "셋째 글")
    self.assertEqual([Note.title for Note in VaultNotes], ["노트1", "노트2"])
    self.assertEqual(LayerGroupById, {"문서A#n0": ("팀", "그룹A"), "문서A#n1": ("팀", "그룹A")})
    self.assertEqual(len(Retr.Index), 2)
    self.assertEqual(Log[2]["vault_size_before"], 1)

  def test_candidates_are_document_level_not_per_note(self) -> None:
    # 볼트에 기존 노트 하나를 미리 넣고, 같은 호출의 첫째 노트는 둘째 노트 후보에 들어가지 않는지 본다
    from vault.types import DocumentRecord
    Retr = Retriever(embed_backend=_embed_backend)
    Retr.add(DocumentRecord(id="기존", layer="팀", title="기존 제목", body="기존 본문", upward_links=[], downward_conditional_links=[], inserted_at_vault_size=0))
    Chat = FakeChat([_result(_output())])
    Log, _, _, _ = _run(Chat, Retr=Retr)
    self.assertEqual([Cand["id"] for Cand in Log[0]["candidates"]], ["기존"])
    self.assertEqual([Cand["id"] for Cand in Log[1]["candidates"]], ["기존"])
    self.assertEqual([Cand["id"] for Cand in Log[2]["candidates"]], ["기존"])
    # 스키마 링크 enum 도 호출 시점의 후보뿐이다
    self.assertEqual(Chat.Calls[0]["schema"]["properties"]["notes"]["items"]["properties"]["upward_links"]["items"]["enum"], ["기존"])

  def test_notes_count_mismatch_is_document_failure(self) -> None:
    Log, VaultNotes, _, _ = _run(FakeChat([_result(_output(Notes=[_note("노트1")]))]))
    self.assertEqual(len(Log), 1)
    self.assertFalse(Log[0]["ok"])
    self.assertIn("notes 개수", Log[0]["error"])
    self.assertEqual(VaultNotes, [])

  def test_finish_reason_length_is_document_failure(self) -> None:
    Log, VaultNotes, _, _ = _run(FakeChat([_result(_output(), FinishReason="length")]))
    self.assertEqual(len(Log), 1)
    self.assertEqual(Log[0]["error"], "finish_reason:length")
    self.assertEqual(VaultNotes, [])

  def test_not_json_and_wrong_shape_are_document_failures(self) -> None:
    for Raw in ("JSON 아님", {"assign": {}}, {"assign": [], "notes": []}, {"assign": {"S1": 1, "S2": 1, "S3": 1}, "notes": ["문자열"]}):
      with self.subTest(Raw):
        Log, VaultNotes, _, _ = _run(FakeChat([_result(Raw)]))
        self.assertFalse(Log[0]["ok"])
        self.assertEqual(VaultNotes, [])

  def test_missing_label_in_assign_is_document_failure(self) -> None:
    Log, VaultNotes, _, _ = _run(FakeChat([_result(_output(Notes=[_note("노트1")], Assign={"S1": 1, "S2": 1}))]))
    self.assertFalse(Log[0]["ok"])
    self.assertIn("assign 에 빠진 표지", Log[0]["error"])

  def test_unknown_label_in_assign_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      _run(FakeChat([_result(_output(Notes=[_note("노트1")], Assign={"S1": 1, "S2": 1, "S3": 1, "S9": 1}))]))

  def test_link_error_in_one_note_fails_only_that_note(self) -> None:
    Output = _output(Notes=[_note("노트1", Up=["없는-id"]), _note("노트2")])
    Log, VaultNotes, _, _ = _run(FakeChat([_result(Output)]))
    self.assertTrue(Log[0]["ok"])
    self.assertFalse(Log[1]["ok"])
    self.assertEqual(Log[1]["problems"], ["upward_links_unknown_id:없는-id"])
    self.assertIsNone(Log[1]["note_id"])
    self.assertTrue(Log[2]["ok"])
    self.assertEqual([Note.note_id for Note in VaultNotes], ["문서A#n1"])

  def test_split_by_layer_schema_enum_and_layer_above_source_raises_value_error(self) -> None:
    Chat = FakeChat([_result(_output(Notes=[_note("노트1", Layer="전사"), _note("노트2")]))])
    with self.assertRaises(ValueError):
      _run(Chat, mode="split_by_layer")
    Enum = Chat.Calls[0]["schema"]["properties"]["notes"]["items"]["properties"]["layer"]["enum"]
    # 사용자 결정 2026-10-16 (가-2) : 층별 분리 모드의 enum 은 출처 층 하나다
    self.assertEqual(Enum, ["팀"])

  def test_every_system_message_contains_layer_block(self) -> None:
    Chat = FakeChat([_result(_output())])
    _run(Chat)
    self.assertIn(_BLOCK, Chat.Calls[0]["messages"][0]["content"])

  def test_every_log_entry_has_base_log_keys_and_place_entries_mark_from_call(self) -> None:
    Log, _, _, _ = _run(FakeChat([_result(_output())]))
    for Entry in Log:
      for Key, Value in _BASE_LOG.items():
        self.assertEqual(Entry[Key], Value)
    for Entry in Log[1:]:
      self.assertTrue(Entry["from_call"])
      for Key in ("raw_text", "prompt_tokens", "completion_tokens", "elapsed_seconds", "finish_reason", "timings"):
        self.assertIsNone(Entry[Key])

  def test_unknown_mode_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      _run(FakeChat([]), mode="other_mode")


class B1VaultSizeAndSearchTest(unittest.TestCase):
  def test_vault_size_before_is_recorded_before_search_and_grows_per_note(self) -> None:
    # 자리 채움 값으로 볼트를 미리 2개 채운다 - run_b1_doc 은 len 과 append 만 쓴다
    Filled = ["자리1", "자리2"]
    Log, VaultNotes, _, _ = _run(FakeChat([_result(_output())]), VaultNotes=Filled)
    self.assertEqual(Log[0]["vault_size_before"], 2)
    self.assertEqual(Log[1]["vault_size_before"], 2)
    self.assertEqual(Log[2]["vault_size_before"], 3)
    self.assertEqual(len(VaultNotes), 4)

  def test_vault_size_before_is_in_b1_call_even_when_call_fails(self) -> None:
    Log, _, _, _ = _run(FakeChat([_result(_output(), FinishReason="length")]), VaultNotes=["자리1", "자리2"])
    self.assertEqual(len(Log), 1)
    self.assertFalse(Log[0]["ok"])
    self.assertEqual(Log[0]["vault_size_before"], 2)

  def _spy_with_three_layers(self) -> SpyRetriever:
    Retr = SpyRetriever(_embed_backend)
    # 사용자 결정 2026-10-16 (나-2) : 층별 분리 모드는 그룹을 알아야 하므로 노트마다 그룹을 넘긴다
    for Id, Layer, Group in (("개인노트", "개인", "주인A"), ("팀노트", "팀", "그룹A"), ("전사노트", "전사", None)):
      Retr.add(_record(Id, Layer), group=Group)
    return Retr

  def test_split_by_layer_search_uses_source_layer_as_caller_and_filters_lower(self) -> None:
    Retr = self._spy_with_three_layers()
    Log, _, _, _ = _run(FakeChat([_result(_output())]), mode="split_by_layer", Retr=Retr)
    self.assertEqual({Cand["layer"] for Cand in Log[0]["candidates"]}, {"팀", "전사"})
    self.assertEqual(len(Retr.Searches), 1)
    self.assertEqual(Retr.Searches[0]["mode"], "split_by_layer")
    self.assertEqual(Retr.Searches[0]["caller_layer"], "팀")
    self.assertEqual(Retr.Searches[0]["caller_group"], "그룹A")

  def test_all_layers_search_is_unfiltered_and_includes_personal(self) -> None:
    Retr = self._spy_with_three_layers()
    Log, _, _, _ = _run(FakeChat([_result(_output())]), mode="all_layers", Retr=Retr)
    self.assertIn("개인", {Cand["layer"] for Cand in Log[0]["candidates"]})
    self.assertEqual(Retr.Searches[0]["mode"], "all_layers")

  def test_search_query_is_shown_and_title_appears_once(self) -> None:
    Retr = SpyRetriever(_embed_backend)
    _run(FakeChat([_result(_output())]), Retr=Retr)
    _, Shown = build_segment_labels(_DOC)
    self.assertEqual(Retr.Searches[0]["query"], Shown)
    self.assertEqual(Retr.Searches[0]["query"].count(_DOC.title), 1)

  def test_unknown_label_with_notes_count_mismatch_raises_value_error(self) -> None:
    Output = _output(Notes=[_note("노트1"), _note("노트2")], Assign={"S1": 1, "S2": 1, "S3": 1, "S9": 1})
    with self.assertRaises(ValueError) as Ctx:
      _run(FakeChat([_result(Output)]))
    self.assertIn("표지에 없는 assign 키", str(Ctx.exception))


class B1PromptAndSchemaTest(unittest.TestCase):
  def test_layer_rule_sentence_is_same_as_place_prompt(self) -> None:
    for Mode in ("all_layers", "split_by_layer"):
      Sentence = layer_rule_sentence(Mode, "팀")
      Place = build_place_messages(_BLOCK, Mode, "팀", "제목", "본문", [])[0]["content"]
      B1 = build_b1_messages(_BLOCK, Mode, "팀", "보임", ["S1", "S2"], [])[0]["content"]
      self.assertIn(f"1. 노트의 층을 정한다. {Sentence}", Place)
      self.assertIn(f"6. layer : {Sentence}", B1)

  def test_b1_system_message_rules(self) -> None:
    Content = build_b1_messages(_BLOCK, "all_layers", "팀", "보임", ["S1", "S2", "S3"], [])[0]["content"]
    self.assertIn(_BLOCK, Content)
    self.assertIn("3. assign 에는 표지 ( S1 ~ S3 ) 마다 노트 번호를 하나씩 적는다.", Content)
    self.assertIn("4. notes 에는 노트 번호 순서대로 노트마다 title, layer, upward_links, downward_links, rationale 을 쓴다.", Content)
    self.assertIn("10. rationale : 층과 링크를 정한 이유를 200자 이하 한 문장으로 쓴다.", Content)
    self.assertIn("11. JSON 만 출력한다.", Content)

  def test_b1_user_message_has_candidates_or_none(self) -> None:
    from retrieval.types import Candidate
    Empty = build_b1_messages(_BLOCK, "all_layers", "팀", "보임", ["S1"], [])[1]["content"]
    self.assertEqual(Empty, "출처 층 : 팀\n\n보임\n\n후보 노트 :\n( 없음 )")
    Cands = [Candidate(id="a", layer="팀", title="t", excerpt="e")]
    Filled = build_b1_messages(_BLOCK, "all_layers", "팀", "보임", ["S1"], Cands)[1]["content"]
    self.assertTrue(Filled.endswith("후보 노트 :\n- id : a | 층 : 팀 | 제목 : t | 발췌 : e"))

  def test_b1_schema_shape(self) -> None:
    Schema = b1_schema(["S1", "S2"], "all_layers", "팀", ["a"])
    self.assertEqual(Schema["required"], ["assign", "notes"])
    self.assertEqual(Schema["properties"]["assign"], assign_schema(["S1", "S2"])["properties"]["assign"])
    Notes = Schema["properties"]["notes"]
    self.assertEqual((Notes["minItems"], Notes["maxItems"]), (1, 2))
    Item = Notes["items"]
    self.assertEqual(Item["required"], ["title", "layer", "upward_links", "downward_links", "rationale"])
    self.assertEqual(Item["properties"]["title"], {"type": "string", "maxLength": 60})
    Place = place_schema("all_layers", "팀", ["a"])["properties"]
    for Key in ("layer", "upward_links", "downward_links", "rationale"):
      self.assertEqual(Item["properties"][Key], Place[Key])
    # 사용자 결정 2026-10-16 (가-2) : 전 층 모드의 enum 은 출처 층 이상이다
    self.assertEqual(Item["properties"]["layer"]["enum"], ["팀", "전사"])

  def test_b1_schema_reuses_place_checks(self) -> None:
    with self.assertRaises(ValueError):
      b1_schema(["S1"], "other_mode", "팀", [])
    with self.assertRaises(ValueError):
      b1_schema(["S1"], "all_layers", "없는층", [])
    with self.assertRaises(ValueError):
      b1_schema(["S1"], "all_layers", "팀", ["a", "a"])
    with self.assertRaises(ValueError):
      b1_schema([], "all_layers", "팀", [])


if __name__ == "__main__":
  unittest.main()
