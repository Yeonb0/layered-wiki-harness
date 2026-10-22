import hashlib
import json
import os
import tempfile
import unittest
import zipfile

from segmentation import segment as sg

# 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
# 새 형식 표 : 팀원A · 팀원B = [팀1], 팀원C · 팀원D = [팀2], 팀원E · 팀원F = [팀1, 팀2]
_TABLE = {"팀원A": ["팀1"], "팀원B": ["팀1"], "팀원C": ["팀2"], "팀원D": ["팀2"], "팀원E": ["팀1", "팀2"], "팀원F": ["팀1", "팀2"]}
_SOURCES = {
  "demo_team1": {"layer": "팀", "group": "팀1", "personal_pages": True},
  "demo_team2": {"layer": "팀", "group": "팀2", "personal_pages": True},
  "demo_lecture": {"layer": "전사", "group": None, "personal_pages": False},
}
_NEW_CFG = {"personal_owner_teams": _TABLE, "sources": _SOURCES}
_LEGACY_CFG = {"team_1jo_personal_owners": ["팀원A"]}
_EXPECTED_LEGACY_TABLE = {
  "lecture_note": ("전사", None, False),
  "team_soft_eng": ("팀", "소공", False),
  "team_1jo": ("팀", "1조", True),
}


def _id(Index: int) -> str:
  return f"{Index:032x}"


def _write_json(Path, Obj) -> None:
  with open(Path, "w", encoding="utf-8") as File:
    json.dump(Obj, File, ensure_ascii=False)


def _read_jsonl(Path) -> list:
  with open(Path, encoding="utf-8") as File:
    return [json.loads(Line) for Line in File]


def _make_corpus(Root, Files, LayerCfg) -> None:
  # tests/test_segmentation.py 의 make_corpus 와 같은 모양이다 - 그 파일은 건드리지 않는다
  os.makedirs(os.path.join(Root, "snapshot1", "raw"))
  os.makedirs(os.path.join(Root, "selection"))
  Mf = []
  for Source, Name, Members in Files:
    Path = os.path.join(Root, "snapshot1", "raw", Name)
    with zipfile.ZipFile(Path, "w") as Zf:
      for Member, Data in Members.items():
        Zf.writestr(Member, Data)
    with open(Path, "rb") as File:
      Digest = hashlib.sha256(File.read()).hexdigest()
    Mf.append({"source": Source, "path": "raw/" + Name, "sha256": Digest})
  _write_json(os.path.join(Root, "snapshot1", "manifest.json"), {"snapshot": 1, "files": Mf})
  _write_json(os.path.join(Root, "selection", "lecture_subjects.json"), {"excluded_pages": {"ids": []}})
  _write_json(os.path.join(Root, "selection", "source_layers.json"), LayerCfg)


def _page(Title: str) -> str:
  return f"# {Title}\n\n{Title} 합성 본문"


def _new_files(Team1Extra=None):
  Team1 = {
    f"팀1/팀원A {_id(1)}.md": _page("A1"),
    f"팀1/팀원E {_id(2)}.md": _page("E1"),
    f"팀1/회의 {_id(3)}.md": _page("회의1"),
  }
  Team1.update(Team1Extra or {})
  return [
    ("demo_team1", "t1.zip", Team1),
    ("demo_team2", "t2.zip", {
      f"팀2/팀원E {_id(4)}.md": _page("E2"),
      f"팀2/팀원C {_id(5)}.md": _page("C2"),
      f"팀2/회의 {_id(6)}.md": _page("회의2"),
    }),
    ("demo_lecture", "lec.zip", {f"강의/강의 {_id(7)}.md": _page("강의")}),
  ]


def _legacy_files():
  return [
    ("lecture_note", "lec.zip", {f"L/강의 {_id(7)}.md": _page("강의")}),
    ("team_soft_eng", "se.zip", {f"소프트웨어 공학/과제/과제 {_id(8)}.md": _page("과제")}),
    ("team_1jo", "jo.zip", {
      f"1조/팀원A {_id(1)}.md": _page("A"),
      f"1조/팀원A/생각 {_id(2)}.md": _page("생각"),
      f"1조/회의 {_id(3)}.md": _page("회의"),
    }),
  ]


class SourceTableTest(unittest.TestCase):
  def test_legacy_config_gives_the_old_table(self) -> None:
    self.assertEqual(sg.source_table(_LEGACY_CFG), _EXPECTED_LEGACY_TABLE)

  def test_new_config_gives_the_sources_table(self) -> None:
    self.assertEqual(
      sg.source_table(_NEW_CFG),
      {"demo_team1": ("팀", "팀1", True), "demo_team2": ("팀", "팀2", True), "demo_lecture": ("전사", None, False)},
    )

  def test_invalid_tables_raise_value_error(self) -> None:
    def with_source(**Over):
      return {"personal_owner_teams": _TABLE, "sources": {"s": {"layer": "팀", "group": "팀1", "personal_pages": False, **Over}}}

    Cases = {
      "두 형식 키가 섞임": {"team_1jo_personal_owners": ["팀원A"], "personal_owner_teams": _TABLE, "sources": _SOURCES},
      "새 형식에 sources 없음": {"personal_owner_teams": _TABLE},
      "기존 형식에 sources 있음": {"team_1jo_personal_owners": ["팀원A"], "sources": _SOURCES},
      "주인 키 없음": {"sources": _SOURCES},
      "layer 개인": with_source(layer="개인"),
      "팀인데 group 없음": with_source(group=None),
      "팀인데 group 빈 문자열": with_source(group=""),
      "전사인데 group 있음": with_source(layer="전사", group="팀1"),
      "전사에 personal_pages true": with_source(layer="전사", group=None, personal_pages=True),
      "personal_pages 가 불리언이 아님": with_source(personal_pages="true"),
      "빈 sources": {"personal_owner_teams": _TABLE, "sources": {}},
      "필드 빠짐": {"personal_owner_teams": _TABLE, "sources": {"s": {"layer": "팀", "group": "팀1"}}},
      "객체가 아님": ["팀원A"],
    }
    for Name, Cfg in Cases.items():
      with self.assertRaises(ValueError, msg=Name):
        sg.source_table(Cfg)


class NewFormatRunTest(unittest.TestCase):
  def run_corpus(self, Files, LayerCfg=None):
    with tempfile.TemporaryDirectory() as Dir:
      Root = os.path.join(Dir, "corpus")
      _make_corpus(Root, Files, LayerCfg or _NEW_CFG)
      Out = os.path.join(Dir, "out")
      sg.run(Root, Out)
      Docs = {Row["path"]: Row for Row in _read_jsonl(os.path.join(Out, "docs.jsonl"))}
      Segs = _read_jsonl(os.path.join(Out, "segments.jsonl"))
    return Docs, Segs

  def test_personal_rows_carry_the_workspace_team(self) -> None:
    Docs, Segs = self.run_corpus(_new_files())
    Expected = {
      f"팀1/팀원A {_id(1)}.md": ("개인", "팀원A", "팀1"),
      f"팀1/팀원E {_id(2)}.md": ("개인", "팀원E", "팀1"),
      f"팀2/팀원E {_id(4)}.md": ("개인", "팀원E", "팀2"),
      f"팀2/팀원C {_id(5)}.md": ("개인", "팀원C", "팀2"),
    }
    for Path, (Layer, Group, Team) in Expected.items():
      Row = Docs[Path]
      self.assertEqual((Row["layer"], Row["group"], Row["team"]), (Layer, Group, Team), Path)
      Mine = [Seg for Seg in Segs if Seg["doc_id"] == Row["doc_id"]]
      self.assertTrue(Mine)
      for Seg in Mine:
        self.assertEqual((Seg["layer"], Seg["group"], Seg["team"]), (Layer, Group, Team), Path)

  def test_team_and_enterprise_rows_have_no_team_key(self) -> None:
    Docs, Segs = self.run_corpus(_new_files())
    Expected = {
      f"팀1/회의 {_id(3)}.md": ("팀", "팀1"),
      f"팀2/회의 {_id(6)}.md": ("팀", "팀2"),
      f"강의/강의 {_id(7)}.md": ("전사", None),
    }
    for Path, (Layer, Group) in Expected.items():
      Row = Docs[Path]
      self.assertEqual((Row["layer"], Row["group"]), (Layer, Group), Path)
      self.assertNotIn("team", Row)
      for Seg in Segs:
        if Seg["doc_id"] == Row["doc_id"]:
          self.assertEqual((Seg["layer"], Seg["group"]), (Layer, Group), Path)
          self.assertNotIn("team", Seg)

  def test_team_key_comes_after_the_existing_keys(self) -> None:
    Docs, Segs = self.run_corpus(_new_files())
    Row = Docs[f"팀1/팀원A {_id(1)}.md"]
    self.assertEqual(list(Row)[-1], "team")
    self.assertEqual(list(Row)[:-1], ["doc_id", "source", "path", "zip_sha256", "layer", "group", "title", "properties", "raw_sha256", "n_segments"])
    self.assertEqual(
      list(next(Seg for Seg in Segs if Seg["doc_id"] == Row["doc_id"]))[-1], "team"
    )

  def test_personal_page_in_a_workspace_of_a_team_the_owner_is_not_in_raises_value_error(self) -> None:
    Files = _new_files({f"팀1/팀원C {_id(9)}.md": _page("C1")})
    with tempfile.TemporaryDirectory() as Dir:
      Root = os.path.join(Dir, "corpus")
      _make_corpus(Root, Files, _NEW_CFG)
      with self.assertRaises(ValueError):
        sg.run(Root, os.path.join(Dir, "out"))

  def test_source_not_in_the_table_raises_value_error(self) -> None:
    Files = _new_files() + [("demo_unknown", "x.zip", {f"X/페이지 {_id(10)}.md": _page("X")})]
    with tempfile.TemporaryDirectory() as Dir:
      Root = os.path.join(Dir, "corpus")
      _make_corpus(Root, Files, _NEW_CFG)
      with self.assertRaises(ValueError):
        sg.run(Root, os.path.join(Dir, "out"))

  def test_legacy_source_names_are_not_accepted_with_a_new_table(self) -> None:
    Files = [("team_1jo", "jo.zip", {f"1조/회의 {_id(3)}.md": _page("회의")})]
    with tempfile.TemporaryDirectory() as Dir:
      Root = os.path.join(Dir, "corpus")
      _make_corpus(Root, Files, _NEW_CFG)
      with self.assertRaises(ValueError):
        sg.run(Root, os.path.join(Dir, "out"))


class LegacyFormatRunTest(unittest.TestCase):
  def test_legacy_rows_have_no_team_key(self) -> None:
    with tempfile.TemporaryDirectory() as Dir:
      Root = os.path.join(Dir, "corpus")
      _make_corpus(Root, _legacy_files(), _LEGACY_CFG)
      Out = os.path.join(Dir, "out")
      sg.run(Root, Out)
      Docs = _read_jsonl(os.path.join(Out, "docs.jsonl"))
      Segs = _read_jsonl(os.path.join(Out, "segments.jsonl"))
    self.assertTrue(Docs)
    self.assertTrue(Segs)
    self.assertNotIn("개인", [Row["layer"] for Row in Docs if Row["source"] != "team_1jo"])
    self.assertIn("개인", [Row["layer"] for Row in Docs])
    for Row in Docs + Segs:
      self.assertNotIn("team", Row)
    self.assertEqual(
      list(Docs[0]), ["doc_id", "source", "path", "zip_sha256", "layer", "group", "title", "properties", "raw_sha256", "n_segments"]
    )
    self.assertEqual(
      list(Segs[0]),
      ["segment_id", "doc_id", "seq", "source", "layer", "group", "line_start", "line_end", "text", "text_sha256"],
    )

  def test_legacy_placement_matches_source_layer(self) -> None:
    Table = sg.source_table(_LEGACY_CFG)
    from labeling.gold import Membership

    Membership_ = Membership({"팀원A": frozenset({"1조"})}, "1조")
    for Source, Path in (
      ("team_1jo", f"1조/팀원A {_id(1)}.md"), ("team_1jo", f"1조/팀원A/생각 {_id(2)}.md"), ("team_1jo", f"1조/회의/p {_id(3)}.md"),
      ("team_soft_eng", "소프트웨어 공학/과제/p.md"), ("lecture_note", "L/p.md"),
    ):
      Layer, Group, Team = sg.source_placement(Source, Path, Table, Membership_)
      self.assertEqual((Layer, Group), sg.source_layer(Source, Path, {"팀원A"}), Path)
      self.assertIsNone(Team)
    with self.assertRaises(ValueError):
      sg.source_placement("unknown", "p.md", Table, Membership_)


if __name__ == "__main__":
  unittest.main()
