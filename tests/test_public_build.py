import contextlib
import io
import json
import os
import tempfile
import unittest

from build.public_build import build_public, build_view, main

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
_OWNERS = ["주인A", "주인B"]


def _note(Id, Layer, Group, Up=None, Down=None, Body=None):
  return {
    "note_id": Id,
    "layer": Layer,
    "group": Group,
    "title": f"제목_{Id}",
    "body": Body if Body is not None else f"본문_{Id}_고유문장",
    "source_doc_id": "d",
    "source_layer": Layer,
    "source_group": Group,
    "source_segment_ids": [f"seg_{Id}"],
    "upward_links": Up or [],
    "downward_conditional_links": [
      {"target_id": T, "visibility_condition": {"layer": L, "group": G}} for T, L, G in (Down or [])
    ],
    "inserted_at_vault_size": 0,
  }


def _notes():
  return [
    _note("pa", "개인", "주인A", Up=["t1", "all1"]),
    _note("pb", "개인", "주인B", Up=["all1"]),
    _note("t1", "팀", "1조", Up=["all1"]),
    _note("ts", "팀", "소공", Up=["all1"]),
    _note("all1", "전사", None, Down=[("pa", "개인", "주인A"), ("pb", "개인", "주인B"), ("t1", "팀", "1조")]),
    _note("all2", "전사", None, Up=["all1"]),
  ]


class BuildTestBase(unittest.TestCase):
  def setUp(self) -> None:
    self.Tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.Tmp.cleanup)
    self.Root = os.path.join(self.Tmp.name, "work")
    os.makedirs(self.Root)
    self.Vault = os.path.join(self.Tmp.name, "vault.jsonl")
    self.Owners = os.path.join(self.Tmp.name, "source_layers.json")
    with open(self.Owners, "w", encoding="utf-8") as File:
      json.dump({"team_1jo_personal_owners": _OWNERS}, File)
    self.Printed = []
    self.write_vault(_notes())

  def write_vault(self, Notes) -> None:
    with open(self.Vault, "w", encoding="utf-8") as File:
      for Note in Notes:
        File.write(json.dumps(Note, ensure_ascii=False) + "\n")

  def out(self, Name="o") -> str:
    return os.path.join(self.Root, Name)

  def public(self, Name="o") -> dict:
    return build_public(
      self.Vault, self.out(Name), work_root=self.Root, commit_fn=lambda: "c" * 40, print_fn=self.Printed.append
    )

  def view(self, Layer, Group, Name="o", Redact=False) -> dict:
    return build_view(
      self.Vault, self.Owners, Layer, Group, self.out(Name), work_root=self.Root, redact_body=Redact,
      commit_fn=lambda: "c" * 40, print_fn=self.Printed.append,
    )

  def files(self, Name="o") -> dict:
    Result = {}
    for Dir, _, Names in os.walk(self.out(Name)):
      for FileName in Names:
        with open(os.path.join(Dir, FileName), encoding="utf-8") as File:
          Result[os.path.relpath(os.path.join(Dir, FileName), self.out(Name))] = File.read()
    return Result

  def note_files(self, Name="o") -> list[str]:
    return sorted(os.listdir(os.path.join(self.out(Name), "notes")))

  def all_text(self, Name="o") -> str:
    return "\n".join(self.files(Name).values())


class PublicBuildTest(BuildTestBase):
  def test_only_company_layer_notes_are_written(self) -> None:
    self.public()
    self.assertEqual(self.note_files(), ["all1.md", "all2.md"])

  def test_lower_layer_notes_do_not_appear_anywhere(self) -> None:
    self.public()
    Text = self.all_text()
    for Id in ("pa", "pb", "t1", "ts"):
      self.assertNotIn(f"제목_{Id}", Text)
      self.assertNotIn(f"본문_{Id}_고유문장", Text)
      self.assertNotIn(f"note_id: {Id}", Text)
    self.assertNotIn("주인A", Text)

  def test_downward_links_and_conditions_do_not_appear_anywhere(self) -> None:
    Manifest = self.public()
    Text = self.all_text()
    self.assertNotIn("[[pa]]", Text)
    self.assertNotIn("[[pb]]", Text)
    self.assertNotIn("[[t1]]", Text)
    self.assertNotIn("1조", Text)
    self.assertNotIn("visibility_condition", Text)
    self.assertNotIn("조건부", Text)
    self.assertEqual(Manifest["downward_conditional_links_removed"], 3)

  def test_manifest_fields(self) -> None:
    self.public()
    Disk = json.loads(self.files()["build_manifest.json"])
    self.assertEqual(Disk["kind"], "public")
    self.assertEqual(Disk["harness_commit"], "c" * 40)
    self.assertEqual(Disk["notes_total"], 6)
    self.assertEqual(Disk["notes_by_layer"], {"개인": 2, "팀": 2, "전사": 2})
    self.assertEqual((Disk["notes_included"], Disk["notes_excluded"]), (2, 4))
    self.assertEqual(len(Disk["vault_sha256"]), 64)
    self.assertTrue(Disk["generated_at_utc"].endswith("+00:00"))

  def test_upward_links_are_written_as_wikilinks(self) -> None:
    self.public()
    self.assertIn("- [[all1]]", self.files()["notes/all2.md"])

  def test_upward_link_outside_public_set_raises_value_error(self) -> None:
    Notes = _notes()
    Notes[5]["upward_links"] = ["t1"]
    self.write_vault(Notes)
    with self.assertRaises(ValueError):
      self.public()
    self.assertFalse(os.path.exists(self.out()))

  def test_screen_output_has_numbers_only(self) -> None:
    self.public()
    Joined = "\n".join(self.Printed)
    self.assertIn("included=2", Joined)
    for Word in ("제목_", "본문_", "주인A", "1조"):
      self.assertNotIn(Word, Joined)


class LocalViewTest(BuildTestBase):
  def test_owner_a_view(self) -> None:
    Manifest = self.view("개인", "주인A")
    self.assertEqual(self.note_files(), ["all1.md", "all2.md", "pa.md", "t1.md"])
    self.assertEqual(Manifest["conditional_links_opened"], 2)
    self.assertEqual(Manifest["conditional_links_hidden"], 1)
    Text = self.all_text()
    self.assertIn("[[pa]]", self.files()["notes/all1.md"])
    self.assertIn("[[t1]]", self.files()["notes/all1.md"])
    self.assertNotIn("[[pb]]", Text)
    self.assertNotIn("note_id: pb", Text)
    self.assertNotIn("제목_pb", Text)
    self.assertNotIn("본문_pb_고유문장", Text)

  def test_team_1jo_view(self) -> None:
    Manifest = self.view("팀", "1조")
    self.assertEqual(self.note_files(), ["all1.md", "all2.md", "t1.md"])
    self.assertEqual(Manifest["conditional_links_opened"], 1)
    self.assertEqual(Manifest["conditional_links_hidden"], 2)
    self.assertIn("[[t1]]", self.files()["notes/all1.md"])
    self.assertNotIn("[[pa]]", self.all_text())

  def test_other_team_view_opens_no_conditional_links(self) -> None:
    Manifest = self.view("팀", "소공")
    self.assertEqual(self.note_files(), ["all1.md", "all2.md", "ts.md"])
    self.assertEqual(Manifest["conditional_links_opened"], 0)
    self.assertEqual(Manifest["conditional_links_hidden"], 3)

  def test_company_view_opens_no_conditional_links(self) -> None:
    Manifest = self.view("전사", None)
    self.assertEqual(self.note_files(), ["all1.md", "all2.md"])
    self.assertEqual(Manifest["conditional_links_opened"], 0)

  def test_hidden_upward_links_are_counted_not_written(self) -> None:
    Manifest = self.view("팀", "소공")
    # 소공 보기에서 ts 의 상향 링크는 all1 하나라 가려지지 않는다
    self.assertEqual(Manifest["upward_links_hidden"], 0)
    Manifest = self.view("개인", "주인B", Name="o2")
    self.assertEqual(Manifest["upward_links_hidden"], 0)
    Notes = _notes()
    Notes[4]["upward_links"] = ["ts"]
    self.write_vault(Notes)
    Manifest = self.view("팀", "1조", Name="o3")
    self.assertEqual(Manifest["upward_links_hidden"], 1)
    self.assertNotIn("[[ts]]", self.all_text("o3"))

  def test_manifest_fields(self) -> None:
    self.view("개인", "주인A")
    Disk = json.loads(self.files()["view_manifest.json"])
    self.assertEqual(Disk["kind"], "local_view")
    self.assertEqual(Disk["viewer"], {"layer": "개인", "group": "주인A"})
    self.assertEqual(Disk["notes_written"], 4)
    self.assertTrue(Disk["do_not_deploy"])
    self.assertFalse(Disk["redact_body"])
    self.assertEqual(Disk["harness_commit"], "c" * 40)

  def test_conditional_section_lists_only_opened_links(self) -> None:
    self.view("개인", "주인A")
    Text = self.files()["notes/all1.md"]
    Section = Text.split("## 조건부 링크 ( 이 보기에서 열림 )")[1]
    self.assertIn("[[pa]]", Section)
    self.assertIn("[[t1]]", Section)
    self.assertNotIn("[[pb]]", Section)

  def test_screen_output_has_numbers_only(self) -> None:
    self.view("개인", "주인A")
    Joined = "\n".join(self.Printed)
    self.assertIn("written=4", Joined)
    for Word in ("제목_", "본문_", "주인A", "1조"):
      self.assertNotIn(Word, Joined)


class RedactBodyTest(BuildTestBase):
  def test_redact_on_hides_every_body_and_writes_length_line(self) -> None:
    self.view("개인", "주인A", Redact=True)
    Text = self.all_text()
    for Id in ("pa", "t1", "all1", "all2"):
      self.assertNotIn(f"본문_{Id}_고유문장", Text)
      self.assertIn(f"( 본문 {len(f'본문_{Id}_고유문장')}자 가림 )", self.files()[f"notes/{Id}.md"])
    self.assertIn("제목_pa", Text)
    self.assertIn("note_id: pa", Text)
    self.assertTrue(json.loads(self.files()["view_manifest.json"])["redact_body"])

  def test_redact_off_keeps_bodies(self) -> None:
    self.view("개인", "주인A")
    self.assertIn("본문_pa_고유문장", self.files()["notes/pa.md"])
    self.assertNotIn("가림", self.all_text())


class CommonChecksTest(BuildTestBase):
  def test_existing_out_dir_raises_value_error(self) -> None:
    os.makedirs(self.out())
    with self.assertRaises(ValueError):
      self.public()
    with self.assertRaises(ValueError):
      self.view("전사", None)

  def test_out_dir_outside_work_root_raises_value_error(self) -> None:
    Outside = os.path.join(self.Tmp.name, "outside")
    with self.assertRaises(ValueError):
      build_public(self.Vault, Outside, work_root=self.Root, commit_fn=lambda: "c", print_fn=print)
    self.assertFalse(os.path.exists(Outside))

  def test_unknown_layer_raises_value_error(self) -> None:
    Notes = _notes()
    Notes[0]["layer"] = "없는층"
    self.write_vault(Notes)
    with self.assertRaises(ValueError):
      self.public()
    with self.assertRaises(ValueError):
      self.view("전사", None)

  def test_colliding_file_names_raise_value_error(self) -> None:
    Notes = _notes()
    Notes[4]["note_id"] = "a/b"
    Notes[5]["note_id"] = "a_b"
    Notes[5]["upward_links"] = []
    Notes[0]["upward_links"] = []
    Notes[1]["upward_links"] = []
    Notes[2]["upward_links"] = []
    Notes[3]["upward_links"] = []
    Notes[4]["downward_conditional_links"] = []
    self.write_vault(Notes)
    with self.assertRaises(ValueError):
      self.public()

  def test_viewer_owner_not_in_list_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      self.view("개인", "주인C")

  def test_viewer_group_rules_raise_value_error(self) -> None:
    with self.assertRaises(ValueError):
      self.view("팀", None)
    with self.assertRaises(ValueError):
      self.view("전사", "1조")
    with self.assertRaises(ValueError):
      self.view("없는층", "x")

  def test_note_id_without_vault_entry_raises_value_error_in_view(self) -> None:
    Notes = _notes()
    Notes[4]["upward_links"] = ["없는노트"]
    self.write_vault(Notes)
    with self.assertRaises(ValueError):
      self.view("전사", None)

  def test_duplicate_note_id_raises_value_error(self) -> None:
    self.write_vault(_notes() + [_note("all1", "전사", None)])
    with self.assertRaises(ValueError):
      self.public()


class CliTest(BuildTestBase):
  def test_view_cli_passes_redact_flag(self) -> None:
    import build.public_build as P

    Seen = {}

    def Fake(*Args, **Kwargs):
      Seen["args"] = Args
      Seen["kwargs"] = Kwargs

    Original = P.build_view
    P.build_view = Fake
    try:
      main([
        "view", "--vault", "v", "--source-layers", "s", "--viewer-layer", "팀", "--viewer-group", "1조",
        "--out-dir", "o", "--redact-body",
      ])
    finally:
      P.build_view = Original
    self.assertEqual(Seen["args"], ("v", "s", "팀", "1조", "o"))
    self.assertEqual(Seen["kwargs"], {"redact_body": True})

  def test_help_exits_zero(self) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
      for Argv in (["--help"], ["view", "--help"], ["public", "--help"]):
        with self.assertRaises(SystemExit) as Ctx:
          main(Argv)
        self.assertEqual(Ctx.exception.code, 0)


if __name__ == "__main__":
  unittest.main()
