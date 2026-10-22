import json
import os
import tempfile
import unittest

from agent.placement import build_note_record
from agent.types import NoteDraft, PlacementVerdict, SourceDoc, SourceSegment
from build.public_build import build_view
from labeling.gold import read_membership
from retrieval.search import Retriever
from runner.v2_sequential import load_source_docs
from vault.types import DocumentRecord

# 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
# 새 형식 표 : 주인A · 주인B = [팀가], 주인C · 주인D = [팀나], 주인E · 주인F = [팀가, 팀나]
_TABLE = {"주인A": ["팀가"], "주인B": ["팀가"], "주인C": ["팀나"], "주인D": ["팀나"], "주인E": ["팀가", "팀나"], "주인F": ["팀가", "팀나"]}


def _embed_backend(Texts):
  # 합성 임베딩 - 서버를 부르지 않는다
  return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


class SwitchTestBase(unittest.TestCase):
  def setUp(self) -> None:
    self.Tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.Tmp.cleanup)
    self.Layers = os.path.join(self.Tmp.name, "source_layers.json")
    with open(self.Layers, "w", encoding="utf-8") as File:
      json.dump({"personal_owner_teams": _TABLE}, File, ensure_ascii=False)
    self.Membership = read_membership(self.Layers)


class RunnerTeamTest(SwitchTestBase):
  def corpus(self, Docs, Segments) -> tuple:
    Paths = {}
    for Name, Rows in (("docs.jsonl", Docs), ("segments.jsonl", Segments)):
      Paths[Name] = os.path.join(self.Tmp.name, Name)
      with open(Paths[Name], "w", encoding="utf-8") as File:
        File.write("".join(json.dumps(Row, ensure_ascii=False) + "\n" for Row in Rows))
    Ids = sorted({Row["doc_id"] for Row in Docs})
    Paths["ids"] = os.path.join(self.Tmp.name, "ids.txt")
    with open(Paths["ids"], "w", encoding="utf-8") as File:
      File.write("".join(f"{Id}\n" for Id in Ids))
    Paths["selection"] = os.path.join(self.Tmp.name, "selection.json")
    with open(Paths["selection"], "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"ids": []}}, File)
    return Paths

  def load(self, Docs, Segments):
    Paths = self.corpus(Docs, Segments)
    return load_source_docs(Paths["segments.jsonl"], Paths["docs.jsonl"], Paths["ids"], Paths["ids"], Paths["selection"])

  @staticmethod
  def doc(Id="문서1", Layer="개인", Group="주인E", **Extra):
    return {"doc_id": Id, "title": f"{Id} 제목", "layer": Layer, "group": Group, "raw_sha256": "0" * 64, **Extra}

  @staticmethod
  def segs(Id="문서1", Layer="개인", Group="주인E", Teams=(None,)):
    Rows = []
    for Seq, Team in enumerate(Teams, start=1):
      Row = {"segment_id": f"{Id}-s{Seq}", "doc_id": Id, "seq": Seq, "layer": Layer, "group": Group, "text": f"{Id} 합성 글 {Seq}"}
      if Team is not None:
        Row["team"] = Team
      Rows.append(Row)
    return Rows

  def test_personal_doc_team_reaches_source_doc(self) -> None:
    Docs, _ = self.load([self.doc(team="팀나")], self.segs(Teams=("팀나", "팀나")))
    self.assertEqual(Docs[0].source_team, "팀나")

  def test_doc_without_team_has_none_for_legacy_corpus(self) -> None:
    Docs, _ = self.load([self.doc()], self.segs())
    self.assertIsNone(Docs[0].source_team)

  def test_team_key_on_non_personal_doc_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      self.load([self.doc(Layer="팀", Group="팀가", team="팀가")], self.segs(Layer="팀", Group="팀가", Teams=("팀가",)))
    with self.assertRaises(ValueError):
      self.load([self.doc(Layer="전사", Group=None, team="팀가")], self.segs(Layer="전사", Group=None, Teams=("팀가",)))

  def test_team_key_must_be_a_non_empty_string(self) -> None:
    for Bad in ("", None, 3):
      with self.assertRaises(ValueError, msg=repr(Bad)):
        self.load([self.doc(team=Bad)], self.segs(Teams=("팀나",)))

  def test_segment_teams_must_agree_with_each_other_and_with_docs(self) -> None:
    with self.assertRaises(ValueError):
      self.load([self.doc(team="팀나")], self.segs(Teams=("팀나", "팀가")))
    with self.assertRaises(ValueError):
      self.load([self.doc(team="팀가")], self.segs(Teams=("팀나", "팀나")))
    # docs.jsonl 에는 없고 세그먼트에만 있어도 다르다
    with self.assertRaises(ValueError):
      self.load([self.doc()], self.segs(Teams=("팀나",)))
    # 세그먼트 한쪽에만 team 이 있어도 다르다
    with self.assertRaises(ValueError):
      self.load([self.doc(team="팀나")], self.segs(Teams=("팀나", None)))


class PlacementTeamTest(SwitchTestBase):
  def record(self, Team):
    Doc = SourceDoc(
      doc_id="문서1", title="합성", source_layer="개인", source_group="주인E",
      segments=[SourceSegment(segment_id="문서1-s1", seq=1, text="합성")], source_team=Team,
    )
    Verdict = PlacementVerdict(layer="팀", upward_links=[], downward_target_ids=[], rationale="합성")
    Draft = NoteDraft(title="합성 노트", body="합성 본문", source_segment_ids=["문서1-s1"])
    return build_note_record(Draft, Verdict, Doc, 0, 0, {}, self.Membership)

  def test_personal_doc_in_second_team_workspace_gets_that_team(self) -> None:
    self.assertEqual(self.record("팀나").group, "팀나")
    self.assertEqual(self.record("팀가").group, "팀가")

  def test_new_format_without_source_team_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      self.record(None)

  def test_team_outside_owners_teams_raises_value_error(self) -> None:
    Doc = SourceDoc(
      doc_id="문서1", title="합성", source_layer="개인", source_group="주인A",
      segments=[SourceSegment(segment_id="문서1-s1", seq=1, text="합성")], source_team="팀나",
    )
    Verdict = PlacementVerdict(layer="팀", upward_links=[], downward_target_ids=[], rationale="합성")
    with self.assertRaises(ValueError):
      build_note_record(NoteDraft("합성", "합성", ["문서1-s1"]), Verdict, Doc, 0, 0, {}, self.Membership)


class SearchSpyTest(SwitchTestBase):
  def retriever(self) -> Retriever:
    Retr = Retriever(embed_backend=_embed_backend)
    for Id, Layer, Group in (
      ("팀가노트", "팀", "팀가"), ("팀나노트", "팀", "팀나"), ("주인A노트", "개인", "주인A"), ("전사노트", "전사", None),
    ):
      Retr.add(DocumentRecord(id=Id, layer=Layer, title=Id, body="합성", upward_links=[], downward_conditional_links=[], inserted_at_vault_size=0), group=Group)
    return Retr

  def found(self, Layer, Group) -> set:
    return {Cand.id for Cand in self.retriever().search_visible("질의", 10, "split_by_layer", Layer, Group, self.Membership)}

  def test_owner_of_other_team_does_not_see_first_team_or_other_owner(self) -> None:
    Found = self.found("개인", "주인C")
    self.assertNotIn("팀가노트", Found)
    self.assertNotIn("주인A노트", Found)
    self.assertEqual(Found, {"팀나노트", "전사노트"})

  def test_owner_in_two_teams_sees_both_team_notes(self) -> None:
    Found = self.found("개인", "주인E")
    self.assertTrue({"팀가노트", "팀나노트", "전사노트"} <= Found)
    self.assertNotIn("주인A노트", Found)

  def test_all_layers_mode_is_unchanged(self) -> None:
    Found = {Cand.id for Cand in self.retriever().search_visible("질의", 10, "all_layers", "개인", "주인C", self.Membership)}
    self.assertEqual(Found, {"팀가노트", "팀나노트", "주인A노트", "전사노트"})


class ViewTeamTest(SwitchTestBase):
  def build(self, Layer, Group, Name):
    Vault = os.path.join(self.Tmp.name, "vault.jsonl")
    Rows = [
      ("팀가노트", "팀", "팀가"), ("팀나노트", "팀", "팀나"), ("주인E노트", "개인", "주인E"), ("주인C노트", "개인", "주인C"),
      ("전사노트", "전사", None),
    ]
    with open(Vault, "w", encoding="utf-8") as File:
      for Id, NoteLayer, NoteGroup in Rows:
        File.write(json.dumps({
          "note_id": Id, "layer": NoteLayer, "group": NoteGroup, "title": f"제목_{Id}", "body": f"본문_{Id}",
          "source_doc_id": "문서1", "source_layer": NoteLayer, "source_group": NoteGroup, "source_segment_ids": [f"seg_{Id}"],
          "upward_links": [], "downward_conditional_links": [], "inserted_at_vault_size": 0,
        }, ensure_ascii=False) + "\n")
    Work = os.path.join(self.Tmp.name, "work")
    os.makedirs(Work, exist_ok=True)
    build_view(
      Vault, self.Layers, Layer, Group, os.path.join(Work, Name), work_root=Work, commit_fn=lambda: "c" * 40,
      print_fn=lambda Line: None,
    )
    return sorted(os.listdir(os.path.join(Work, Name, "notes")))

  def test_owner_in_two_teams_sees_both_team_notes_in_view(self) -> None:
    Files = self.build("개인", "주인E", "e")
    self.assertIn("팀가노트.md", Files)
    self.assertIn("팀나노트.md", Files)
    self.assertIn("주인E노트.md", Files)
    self.assertNotIn("주인C노트.md", Files)

  def test_owner_of_other_team_does_not_see_first_team_note_in_view(self) -> None:
    Files = self.build("개인", "주인C", "c")
    self.assertNotIn("팀가노트.md", Files)
    self.assertIn("팀나노트.md", Files)


if __name__ == "__main__":
  unittest.main()
