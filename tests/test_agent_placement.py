import itertools
import unittest

from agent.placement import build_note_record, validate_placement
from agent.types import NoteDraft, PlacementVerdict, SourceDoc
from retrieval.search import LAYER_ORDER
from retrieval.types import Candidate

# 픽스처일 뿐이며 규칙과 무관하다
_OWNERS = {"주인A", "주인B"}


def _cand(Id: str, Layer: str) -> Candidate:
  return Candidate(id=Id, layer=Layer, title="합성", excerpt="합성")


_CANDS = [_cand("개인노트", "개인"), _cand("팀노트", "팀"), _cand("전사노트", "전사")]


def _raw(Layer, Up, Down, Rationale="합성 근거") -> dict:
  return {"layer": Layer, "upward_links": Up, "downward_links": Down, "rationale": Rationale}


class ValidatePlacementTest(unittest.TestCase):
  def test_valid_verdict(self) -> None:
    Result = validate_placement(_raw("팀", ["전사노트"], ["개인노트"]), "all_layers", "팀", _CANDS)
    self.assertTrue(Result.valid)
    self.assertEqual(Result.problems, [])
    self.assertEqual(Result.verdict.layer, "팀")
    self.assertEqual(Result.verdict.upward_links, ["전사노트"])
    self.assertEqual(Result.verdict.downward_target_ids, ["개인노트"])

  def test_invalid_mode_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      validate_placement(_raw("팀", [], []), "other_mode", "팀", _CANDS)

  def test_split_layer_above_source_raises_value_error(self) -> None:
    Cands = [_cand("팀노트", "팀"), _cand("전사노트", "전사")]
    with self.assertRaises(ValueError):
      validate_placement(_raw("전사", [], []), "split_by_layer", "팀", Cands)

  def test_split_with_lower_layer_candidate_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      validate_placement(_raw("팀", [], []), "split_by_layer", "팀", _CANDS)

  def test_layer_below_source_is_problem(self) -> None:
    Result = validate_placement(_raw("개인", [], []), "all_layers", "팀", _CANDS)
    self.assertFalse(Result.valid)
    self.assertIn("layer_below_source", Result.problems)
    self.assertIsNone(Result.verdict)

  def test_upward_link_to_lower_layer_is_problem(self) -> None:
    Result = validate_placement(_raw("팀", ["개인노트"], []), "all_layers", "팀", _CANDS)
    self.assertFalse(Result.valid)
    self.assertIn("upward_links_target_below_note:개인노트", Result.problems)

  def test_downward_link_to_same_layer_is_problem(self) -> None:
    Result = validate_placement(_raw("팀", [], ["팀노트"]), "all_layers", "팀", _CANDS)
    self.assertFalse(Result.valid)
    self.assertIn("downward_links_target_not_below_note:팀노트", Result.problems)

  def test_downward_link_to_upper_layer_is_problem(self) -> None:
    Result = validate_placement(_raw("팀", [], ["전사노트"]), "all_layers", "팀", _CANDS)
    self.assertFalse(Result.valid)
    self.assertIn("downward_links_target_not_below_note:전사노트", Result.problems)

  def test_id_outside_candidates_is_problem(self) -> None:
    Result = validate_placement(_raw("팀", ["없는노트"], ["또없는노트"]), "all_layers", "팀", _CANDS)
    self.assertFalse(Result.valid)
    self.assertIn("upward_links_unknown_id:없는노트", Result.problems)
    self.assertIn("downward_links_unknown_id:또없는노트", Result.problems)

  def test_layer_outside_order_is_problem(self) -> None:
    Result = validate_placement(_raw("없는층", [], []), "all_layers", "팀", _CANDS)
    self.assertFalse(Result.valid)
    self.assertIn("layer_invalid", Result.problems)

  def test_rationale_not_string_is_problem(self) -> None:
    Result = validate_placement(_raw("팀", [], [], Rationale=3), "all_layers", "팀", _CANDS)
    self.assertFalse(Result.valid)
    self.assertIn("rationale_not_string", Result.problems)


class SplitByLayerSpyTest(unittest.TestCase):
  def test_above_source_always_raises_and_others_never_do(self) -> None:
    # 출처 층 3개 x 판정 층 3개 전부 - 출처 위 판정만 ValueError 여야 한다 ( 누출 하한선 )
    for Source, Verdict in itertools.product(LAYER_ORDER, LAYER_ORDER):
      Cands = [_cand(f"{L}노트", L) for L in LAYER_ORDER if LAYER_ORDER.index(L) >= LAYER_ORDER.index(Source)]
      Above = LAYER_ORDER.index(Verdict) > LAYER_ORDER.index(Source)
      with self.subTest(source=Source, verdict=Verdict):
        if Above:
          with self.assertRaises(ValueError):
            validate_placement(_raw(Verdict, [], []), "split_by_layer", Source, Cands)
        else:
          # ValueError 가 나면 그대로 테스트 오류가 된다
          validate_placement(_raw(Verdict, [], []), "split_by_layer", Source, Cands)


class BuildNoteRecordTest(unittest.TestCase):
  def setUp(self) -> None:
    self.Doc = SourceDoc(doc_id="문서A", title="t", source_layer="개인", source_group="주인A", segments=[])
    self.Draft = NoteDraft(title="제목", body="본문", source_segment_ids=["세그A", "세그B"])
    self.Verdict = PlacementVerdict(layer="팀", upward_links=["전사노트"], downward_target_ids=["개인노트"], rationale="합성")
    self.LayerGroupById = {"개인노트": ("개인", "주인B"), "전사노트": ("전사", None)}

  def test_personal_source_team_verdict_gets_team_group(self) -> None:
    Rec = build_note_record(self.Draft, self.Verdict, self.Doc, 2, 17, self.LayerGroupById, _OWNERS)
    self.assertEqual(Rec.note_id, "문서A#n2")
    self.assertEqual(Rec.layer, "팀")
    self.assertEqual(Rec.group, "1조")
    self.assertEqual(Rec.source_doc_id, "문서A")
    self.assertEqual(Rec.source_layer, "개인")
    self.assertEqual(Rec.source_group, "주인A")
    self.assertEqual(Rec.source_segment_ids, ["세그A", "세그B"])
    self.assertEqual(Rec.upward_links, ["전사노트"])
    self.assertEqual(Rec.inserted_at_vault_size, 17)

  def test_downward_link_visibility_condition_filled_from_vault(self) -> None:
    Rec = build_note_record(self.Draft, self.Verdict, self.Doc, 0, 5, self.LayerGroupById, _OWNERS)
    self.assertEqual(len(Rec.downward_conditional_links), 1)
    self.assertEqual(Rec.downward_conditional_links[0].target_id, "개인노트")
    self.assertEqual(Rec.downward_conditional_links[0].visibility_condition, {"layer": "개인", "group": "주인B"})

  def test_downward_target_missing_from_vault_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      build_note_record(self.Draft, self.Verdict, self.Doc, 0, 5, {}, _OWNERS)

  def test_same_layer_keeps_source_group(self) -> None:
    Verdict = PlacementVerdict(layer="개인", upward_links=[], downward_target_ids=[], rationale="합성")
    Rec = build_note_record(self.Draft, Verdict, self.Doc, 1, 5, self.LayerGroupById, _OWNERS)
    self.assertEqual(Rec.group, "주인A")


if __name__ == "__main__":
  unittest.main()
