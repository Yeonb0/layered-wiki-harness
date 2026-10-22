import json
import os
import tempfile
import unittest

from labeling.gold import (
  LAYER_RANK,
  Membership,
  group_for,
  note_group,
  personal_team,
  read_membership,
  read_owners,
  visible_pairs_for,
)

# 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
_LAYERS = ["개인", "팀", "전사"]
_LEGACY_OWNERS = ["주인A", "주인B"]
_NEW_FORMAT = {"주인A": ["팀가"], "주인B": ["팀가"], "주인C": ["팀나"], "주인D": ["팀나"], "주인E": ["팀가", "팀나"], "주인F": ["팀가", "팀나"]}


def _outcome(Fn):
  # 값 또는 ValueError 를 같은 모양으로 담아 두 구현을 비교한다
  try:
    return ("ok", Fn())
  except ValueError:
    return ("error",)


class MembershipTestBase(unittest.TestCase):
  def setUp(self) -> None:
    self.Tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.Tmp.cleanup)

  def write(self, Obj, Name="source_layers.json") -> str:
    Path = os.path.join(self.Tmp.name, Name)
    with open(Path, "w", encoding="utf-8") as File:
      json.dump(Obj, File, ensure_ascii=False)
    return Path

  def legacy(self) -> Membership:
    return read_membership(self.write({"team_1jo_personal_owners": _LEGACY_OWNERS}, "legacy.json"))

  def new(self) -> Membership:
    return read_membership(self.write({"personal_owner_teams": _NEW_FORMAT}, "new.json"))


class LegacyFormatTest(MembershipTestBase):
  def test_legacy_file_maps_every_owner_to_team_1jo(self) -> None:
    Path = self.write({"team_1jo_personal_owners": _LEGACY_OWNERS})
    Membership_ = read_membership(Path)
    self.assertEqual(Membership_.legacy_team, "1조")
    self.assertEqual(set(Membership_.teams_by_owner), read_owners(Path))
    for Teams in Membership_.teams_by_owner.values():
      self.assertEqual(Teams, frozenset({"1조"}))

  def test_note_group_matches_group_for_in_every_combination(self) -> None:
    Owners = set(_LEGACY_OWNERS)
    Membership_ = self.legacy()
    for SegLayer in _LAYERS:
      for SegGroup in ("주인A", "주인B", "주인Z", "1조", "소공", None):
        Seg = {"layer": SegLayer, "group": SegGroup, "segment_id": "s1"}
        for Gold in _LAYERS:
          self.assertEqual(
            _outcome(lambda: note_group(Seg, Gold, Membership_)),
            _outcome(lambda: group_for(Seg, Gold, Owners)),
            (SegLayer, SegGroup, Gold),
          )

  def test_visible_pairs_match_the_group_for_formula(self) -> None:
    Owners = set(_LEGACY_OWNERS)
    Membership_ = self.legacy()
    for Layer in _LAYERS:
      for Group in ("주인A", "주인B", "주인Z", "1조", "소공", None, ""):
        def Formula():
          return {
            (L, group_for({"layer": Layer, "group": Group, "segment_id": "<viewer>"}, L, Owners))
            for L in _LAYERS[_LAYERS.index(Layer):]
          }

        Expected = _outcome(Formula)
        Actual = _outcome(lambda: visible_pairs_for(Layer, Group, Membership_))
        # 식이 ValueError 를 내는 조합은 같이 ValueError 여야 한다
        if Expected == ("error",):
          self.assertEqual(Actual, ("error",), (Layer, Group))
        # 팀 호출자의 빈 그룹과 전사 호출자의 그룹은 식이 통과시키지만 새 함수는 막는다 ( 빈 보기를 조용히 만들지 않으려고 )
        elif (Layer == "팀" and not Group) or (Layer == "전사" and Group is not None):
          self.assertEqual(Actual, ("error",), (Layer, Group))
        else:
          self.assertEqual(Actual, Expected, (Layer, Group))


class NewFormatTest(MembershipTestBase):
  def test_new_format_is_read_as_given(self) -> None:
    Membership_ = self.new()
    self.assertIsNone(Membership_.legacy_team)
    self.assertEqual(Membership_.teams_by_owner["주인E"], frozenset({"팀가", "팀나"}))
    self.assertEqual(Membership_.teams_by_owner["주인C"], frozenset({"팀나"}))

  def test_owner_in_two_teams_sees_both_team_notes(self) -> None:
    Pairs = visible_pairs_for("개인", "주인E", self.new())
    self.assertIn(("팀", "팀가"), Pairs)
    self.assertIn(("팀", "팀나"), Pairs)
    self.assertEqual(Pairs, {("개인", "주인E"), ("팀", "팀가"), ("팀", "팀나"), ("전사", None)})

  def test_owner_of_other_team_sees_neither_other_team_nor_other_owners(self) -> None:
    Pairs = visible_pairs_for("개인", "주인C", self.new())
    self.assertNotIn(("팀", "팀가"), Pairs)
    self.assertEqual([Pair for Pair in Pairs if Pair[0] == "개인" and Pair[1] != "주인C"], [])
    self.assertEqual(Pairs, {("개인", "주인C"), ("팀", "팀나"), ("전사", None)})

  def test_team_and_enterprise_views(self) -> None:
    Membership_ = self.new()
    self.assertEqual(visible_pairs_for("팀", "팀가", Membership_), {("팀", "팀가"), ("전사", None)})
    self.assertEqual(visible_pairs_for("전사", None, Membership_), {("전사", None)})

  def test_team_outside_the_owners_teams_raises_value_error(self) -> None:
    Seg = {"layer": "개인", "group": "주인A", "segment_id": "s1", "team": "팀나"}
    with self.assertRaises(ValueError):
      note_group(Seg, "팀", self.new())

  def test_missing_team_key_raises_value_error(self) -> None:
    Seg = {"layer": "개인", "group": "주인E", "segment_id": "s1"}
    with self.assertRaises(ValueError):
      note_group(Seg, "팀", self.new())
    with self.assertRaises(ValueError):
      personal_team(Seg, self.new())

  def test_note_groups_for_owner_in_two_teams(self) -> None:
    Seg = {"layer": "개인", "group": "주인E", "segment_id": "s1", "team": "팀나"}
    Membership_ = self.new()
    self.assertEqual(note_group(Seg, "팀", Membership_), "팀나")
    self.assertIsNone(note_group(Seg, "전사", Membership_))
    self.assertEqual(note_group(Seg, "개인", Membership_), "주인E")

  def test_unknown_owner_raises_value_error(self) -> None:
    Membership_ = self.new()
    Seg = {"layer": "개인", "group": "주인Z", "segment_id": "s1", "team": "팀가"}
    with self.assertRaises(ValueError):
      note_group(Seg, "팀", Membership_)
    with self.assertRaises(ValueError):
      visible_pairs_for("개인", "주인Z", Membership_)

  def test_legacy_membership_uses_legacy_team_without_team_key(self) -> None:
    Seg = {"layer": "개인", "group": "주인A", "segment_id": "s1"}
    self.assertEqual(personal_team(Seg, self.legacy()), "1조")

  def test_legacy_membership_still_checks_an_explicit_team(self) -> None:
    Seg = {"layer": "개인", "group": "주인A", "segment_id": "s1", "team": "팀가"}
    with self.assertRaises(ValueError):
      personal_team(Seg, self.legacy())


class ViewerArgumentTest(MembershipTestBase):
  def test_invalid_viewer_arguments_raise_value_error(self) -> None:
    Membership_ = self.new()
    for Layer, Group in (("없는층", None), ("팀", None), ("팀", ""), ("전사", "팀가"), ("개인", None)):
      with self.assertRaises(ValueError, msg=(Layer, Group)):
        visible_pairs_for(Layer, Group, Membership_)

  def test_layer_names_come_from_the_layer_rank_table(self) -> None:
    self.assertEqual(sorted(LAYER_RANK), sorted(_LAYERS))


class FormatErrorTest(MembershipTestBase):
  def assert_invalid(self, Obj) -> None:
    with self.assertRaises(ValueError, msg=Obj):
      read_membership(self.write(Obj, "bad.json"))

  def test_both_keys_present(self) -> None:
    self.assert_invalid({"team_1jo_personal_owners": ["주인A"], "personal_owner_teams": {"주인A": ["팀가"]}})

  def test_neither_key_present(self) -> None:
    self.assert_invalid({"purpose": "합성"})

  def test_empty_team_list(self) -> None:
    self.assert_invalid({"personal_owner_teams": {"주인A": []}})

  def test_duplicate_team(self) -> None:
    self.assert_invalid({"personal_owner_teams": {"주인A": ["팀가", "팀가"]}})

  def test_non_string_or_empty_names(self) -> None:
    self.assert_invalid({"personal_owner_teams": {"주인A": [1]}})
    self.assert_invalid({"personal_owner_teams": {"주인A": [""]}})
    self.assert_invalid({"personal_owner_teams": {"": ["팀가"]}})
    self.assert_invalid({"personal_owner_teams": {"주인A": "팀가"}})

  def test_empty_or_non_object_table(self) -> None:
    self.assert_invalid({"personal_owner_teams": {}})
    self.assert_invalid({"personal_owner_teams": ["주인A"]})

  def test_legacy_list_checks_are_the_same_as_read_owners(self) -> None:
    self.assert_invalid({"team_1jo_personal_owners": []})
    self.assert_invalid({"team_1jo_personal_owners": [1]})

  def test_top_level_not_an_object(self) -> None:
    self.assert_invalid(["주인A"])


if __name__ == "__main__":
  unittest.main()
