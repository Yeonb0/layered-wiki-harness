import json
import unittest

from agent.b1 import run_b1_doc
from agent.llm_client import ChatResult, GenerationConfig
from agent.propose import run_propose_doc
from agent.types import SourceDoc, SourceSegment
from retrieval.search import Retriever
from vault.types import DocumentRecord

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
_OWNERS = {"주인A", "주인B"}
_BLOCK = "합성 층 정의 블록\n- 합성 조항"
_BLOCK_SHA = "0" * 64
_CONFIG = GenerationConfig(temperature=0.0, seed=1, max_tokens=64, enable_thinking=False)
_ENTRIES = [
  ("개인A노트", "개인", "주인A"),
  ("개인B노트", "개인", "주인B"),
  ("팀1조노트", "팀", "1조"),
  ("팀소공노트", "팀", "소공"),
  ("전사노트", "전사", None),
]


def _embed_backend(Texts: list[str]) -> list[list[float]]:
  # 합성 임베딩 - 글자 수로 만든 2차원 벡터이며 서버를 부르지 않는다
  return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


def _record(Id: str, Layer: str) -> DocumentRecord:
  return DocumentRecord(
    id=Id, layer=Layer, title=f"{Id} 제목", body=f"{Id} 본문", upward_links=[], downward_conditional_links=[],
    inserted_at_vault_size=0,
  )


def _filled_retriever() -> Retriever:
  Retr = Retriever(embed_backend=_embed_backend)
  for Id, Layer, Group in _ENTRIES:
    Retr.add(_record(Id, Layer), group=Group)
  return Retr


def _ids(Candidates) -> set:
  return {Cand.id for Cand in Candidates}


class SearchVisibleTest(unittest.TestCase):
  def test_split_by_layer_visible_set_per_caller(self) -> None:
    Retr = _filled_retriever()
    Cases = [
      (("개인", "주인A"), {"개인A노트", "팀1조노트", "전사노트"}),
      (("팀", "1조"), {"팀1조노트", "전사노트"}),
      (("팀", "소공"), {"팀소공노트", "전사노트"}),
      (("전사", None), {"전사노트"}),
    ]
    for (Layer, Group), Expected in Cases:
      with self.subTest(Layer=Layer, Group=Group):
        Found = Retr.search_visible("질의", 10, "split_by_layer", Layer, Group, _OWNERS)
        self.assertEqual(_ids(Found), Expected)

  def test_all_layers_returns_everything_for_any_caller(self) -> None:
    Retr = _filled_retriever()
    for Layer, Group in (("개인", "주인A"), ("팀", "소공"), ("전사", None)):
      with self.subTest(Layer=Layer):
        Found = Retr.search_visible("질의", 5, "all_layers", Layer, Group, _OWNERS)
        self.assertEqual(_ids(Found), {Id for Id, _, _ in _ENTRIES})

  def test_all_layers_matches_old_search_result(self) -> None:
    Retr = _filled_retriever()
    Old = Retr.search("질의", 5, "all_layers", None)
    New = Retr.search_visible("질의", 5, "all_layers", "팀", "1조", _OWNERS)
    self.assertEqual([Cand.id for Cand in Old], [Cand.id for Cand in New])

  def test_k_limits_result_count(self) -> None:
    Found = _filled_retriever().search_visible("질의", 2, "all_layers", "팀", "1조", _OWNERS)
    self.assertEqual(len(Found), 2)

  def test_unknown_group_entry_raises_value_error_in_split_only(self) -> None:
    Retr = _filled_retriever()
    # 그룹을 넘기지 않고 색인한 노트가 하나라도 있는 경우
    Retr.add(_record("모름노트", "팀"))
    with self.assertRaises(ValueError):
      Retr.search_visible("질의", 10, "split_by_layer", "팀", "1조", _OWNERS)
    Found = Retr.search_visible("질의", 10, "all_layers", "팀", "1조", _OWNERS)
    self.assertIn("모름노트", _ids(Found))

  def test_none_group_of_enterprise_note_is_not_unknown(self) -> None:
    # 전사 노트의 그룹은 None 이며 "그룹 모름" 이 아니다
    Retr = Retriever(embed_backend=_embed_backend)
    Retr.add(_record("전사노트", "전사"), group=None)
    Found = Retr.search_visible("질의", 10, "split_by_layer", "전사", None, _OWNERS)
    self.assertEqual(_ids(Found), {"전사노트"})

  def test_personal_caller_not_in_owners_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      _filled_retriever().search_visible("질의", 10, "split_by_layer", "개인", "목록에 없는 주인", _OWNERS)

  def test_unknown_mode_and_caller_layer_raise_value_error(self) -> None:
    Retr = _filled_retriever()
    with self.assertRaises(ValueError):
      Retr.search_visible("질의", 10, "other_mode", "팀", "1조", _OWNERS)
    with self.assertRaises(ValueError):
      Retr.search_visible("질의", 10, "split_by_layer", "없는층", None, _OWNERS)


def _result(Obj) -> ChatResult:
  return ChatResult(
    text=json.dumps(Obj, ensure_ascii=False), finish_reason="stop", prompt_tokens=10, completion_tokens=5,
    elapsed_seconds=0.1, timings=None, request_body={}, response_body={},
  )


def fake_chat(messages, model_id, config, response_schema, *, timeout_seconds):
  # 스키마 모양으로 어떤 호출인지 알아보고 출처 층 노트 하나짜리 합성 출력을 낸다 ( 링크 없음 )
  Props = response_schema["properties"]
  if "notes" in Props:
    Layer = Props["notes"]["items"]["properties"]["layer"]["enum"][0]
    return _result({
      "assign": {Label: 1 for Label in Props["assign"]["required"]},
      "notes": [{"title": "합성 노트", "layer": Layer, "upward_links": [], "downward_links": [], "rationale": "합성 근거"}],
    })
  if "assign" in Props:
    return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["합성 노트"]})
  return _result({"layer": Props["layer"]["enum"][0], "upward_links": [], "downward_links": [], "rationale": "합성 근거"})


def _doc(Id: str) -> SourceDoc:
  return SourceDoc(
    doc_id=Id, title=f"{Id} 제목", source_layer="개인", source_group="주인A",
    segments=[SourceSegment(segment_id=f"{Id}-s1", seq=1, text=f"{Id} 합성 글")],
  )


def _run_propose(Doc, Mode, Retr, VaultNotes=None):
  return run_propose_doc(
    Doc, Mode, 10, Retr, [] if VaultNotes is None else VaultNotes, {}, fake_chat, "합성모델", _CONFIG, _CONFIG, _BLOCK,
    _BLOCK_SHA, _OWNERS, 9, {"trial_id": "t"},
  )


def _run_b1(Doc, Mode, Retr, VaultNotes=None):
  return run_b1_doc(
    Doc, Mode, 10, Retr, [] if VaultNotes is None else VaultNotes, {}, fake_chat, "합성모델", _CONFIG, _BLOCK, _BLOCK_SHA,
    _OWNERS, 9, {"trial_id": "t"},
  )


def _candidate_ids(Log) -> set:
  return {Cand["id"] for Entry in Log for Cand in Entry.get("candidates", [])}


class IntegrationTest(unittest.TestCase):
  def test_split_by_layer_hides_other_owner_and_other_team_in_both_conditions(self) -> None:
    for Name, Run in (("propose", _run_propose), ("b1", _run_b1)):
      with self.subTest(Name):
        Log = Run(_doc("문서A"), "split_by_layer", _filled_retriever())
        Seen = _candidate_ids(Log)
        self.assertNotIn("개인B노트", Seen)
        self.assertNotIn("팀소공노트", Seen)
        self.assertEqual(Seen, {"개인A노트", "팀1조노트", "전사노트"})

  def test_all_layers_shows_everything_in_both_conditions(self) -> None:
    for Name, Run in (("propose", _run_propose), ("b1", _run_b1)):
      with self.subTest(Name):
        Log = Run(_doc("문서A"), "all_layers", _filled_retriever())
        self.assertEqual(_candidate_ids(Log), {Id for Id, _, _ in _ENTRIES})

  def test_created_notes_are_indexed_with_group_so_next_split_search_works(self) -> None:
    for Name, Run in (("propose", _run_propose), ("b1", _run_b1)):
      with self.subTest(Name):
        Retr = Retriever(embed_backend=_embed_backend)
        VaultNotes = []
        Run(_doc("문서A"), "split_by_layer", Retr, VaultNotes)
        # 첫 문서가 만든 노트는 출처 그룹과 함께 색인된다
        self.assertEqual(len(VaultNotes), 1)
        self.assertEqual(Retr.Groups, ["주인A"])
        # 다음 문서의 층별 분리 검색이 그룹을 모른다는 ValueError 없이 앞 노트를 본다
        Log = Run(_doc("문서B"), "split_by_layer", Retr, VaultNotes)
        self.assertIn("문서A#n0", _candidate_ids(Log))


if __name__ == "__main__":
  unittest.main()
