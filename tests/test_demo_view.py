import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict, replace

import serve.demo_api as D
from agent.layer_block import MARK
from agent.llm_client import ChatResult
from build.public_build import build_view, view_selection
from labeling.gold import read_membership, visible_pairs_for
from runner.v2_sequential import run_v2
from serve.demo_api import DemoApp, make_server

# 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
# 소속 표 : 샘플가 = [팀가], 샘플나 = [팀나], 샘플다 = [팀가, 팀나] ( 각각 주인 A · C · E 에 해당한다 )
# 실제 이름을 가리는 라벨이 주인A … 이라 가림 전 이름과 겹치지 않게 샘플 이름을 쓴다
_TABLE = {"샘플가": ["팀가"], "샘플나": ["팀나"], "샘플다": ["팀가", "팀나"]}
_CRITERIA = f"## 가 {MARK}\n합성 본문\n## 나\n".encode("utf-8")
_CRITERIA_SHA = hashlib.sha256(_CRITERIA).hexdigest()
_MODES = ["all_layers", "split_by_layer"]
_NOTE_KEYS = (
  "note_id", "layer", "group", "title", "body", "source_doc_id", "source_layer", "source_group", "source_segment_ids",
  "upward_links", "downward_conditional_links", "inserted_at_vault_size",
)


def _note(Id, Layer, Group, Doc, Title, Up=None, Down=None):
  return {
    "note_id": Id, "layer": Layer, "group": Group, "title": Title, "body": f"본문 {Id} 합성 글", "source_doc_id": Doc,
    "source_layer": Layer, "source_group": Group, "source_segment_ids": [f"{Doc}-s1"], "upward_links": Up or [],
    "downward_conditional_links": [
      {"target_id": T, "visibility_condition": {"layer": L, "group": G}} for T, L, G in (Down or [])
    ], "inserted_at_vault_size": 0,
  }


def _vault():
  return [
    _note("문서전사#n0", "전사", None, "문서전사", "기존 제목 전사",
          Down=[("문서팀가#n0", "팀", "팀가"), ("문서개인A#n0", "개인", "샘플가")]),
    _note("문서팀가#n0", "팀", "팀가", "문서팀가", "기존 제목 팀가", Up=["문서팀나#n0"]),
    _note("문서팀가#n1", "팀", "팀가", "문서팀가", "기존 제목 팀가 둘째"),
    _note("문서팀나#n0", "팀", "팀나", "문서팀나", "기존 제목 팀나"),
    _note("문서개인A#n0", "개인", "샘플가", "문서개인A", "기존 제목 개인가", Up=["문서팀가#n1"]),
    _note("문서개인C#n0", "개인", "샘플나", "문서개인C", "기존 제목 개인나"),
    _note("문서개인E#n0", "개인", "샘플다", "문서개인E", "기존 제목 개인다"),
  ]


def _result(Obj) -> ChatResult:
  return ChatResult(
    text=json.dumps(Obj, ensure_ascii=False), finish_reason="stop", prompt_tokens=1, completion_tokens=1,
    elapsed_seconds=0.1, timings=None, request_body={}, response_body={},
  )


def make_chat(Title="합성 제목"):
  def chat(messages, model_id, config, response_schema, *, timeout_seconds):
    Props = response_schema["properties"]
    if "assign" in Props:
      return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": [Title]})
    return _result({"layer": Props["layer"]["enum"][0], "upward_links": [], "downward_links": [], "rationale": "합성 근거"})

  return chat


class Gate:
  # 생성 함수를 Event 로 막아 두는 합성 chat_fn
  def __init__(self) -> None:
    self.entered = threading.Event()
    self.release = threading.Event()
    self.inner = make_chat()

  def __call__(self, *Args, **Kwargs):
    self.entered.set()
    if not self.release.wait(10):
      raise RuntimeError("합성 게이트가 풀리지 않았다")
    return self.inner(*Args, **Kwargs)


def _embed_backend(Texts):
  return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


class ViewBase(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.Tmp = tempfile.TemporaryDirectory()
    Data = os.path.join(cls.Tmp.name, "data")
    os.makedirs(Data)
    cls.Data = Data
    Docs = [("문서전사", "전사", None, None), ("문서팀가", "팀", "팀가", None), ("문서개인A", "개인", "샘플가", "팀가")]
    with open(os.path.join(Data, "segments.jsonl"), "w", encoding="utf-8") as File:
      for Id, Layer, Group, Team in Docs:
        for Seq in (1, 2):
          Row = {"segment_id": f"{Id}-s{Seq}", "doc_id": Id, "seq": Seq, "layer": Layer, "group": Group, "text": f"{Id} 합성 글 {Seq}"}
          if Team:
            Row["team"] = Team
          File.write(json.dumps(Row, ensure_ascii=False) + "\n")
    with open(os.path.join(Data, "docs.jsonl"), "w", encoding="utf-8") as File:
      for Index, (Id, Layer, Group, Team) in enumerate(Docs):
        Row = {"doc_id": Id, "title": f"{Id} 제목", "layer": Layer, "group": Group, "raw_sha256": f"{Index:064d}"}
        if Team:
          Row["team"] = Team
        File.write(json.dumps(Row, ensure_ascii=False) + "\n")
    with open(os.path.join(Data, "ids.txt"), "w", encoding="utf-8") as File:
      File.write("".join(f"{Doc[0]}\n" for Doc in Docs))
    with open(os.path.join(Data, "selection.json"), "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"ids": []}}, File)
    cls.SourceLayers = os.path.join(Data, "source_layers.json")
    with open(cls.SourceLayers, "w", encoding="utf-8") as File:
      json.dump({"personal_owner_teams": _TABLE}, File, ensure_ascii=False)
    with open(os.path.join(Data, "criteria.md"), "wb") as File:
      File.write(_CRITERIA)
    cls.Demo = cls.make_run("demo_run", 900, "demo")
    cls.Real = cls.make_run("real_run", 1, "synthetic")

  @classmethod
  def make_run(cls, Name, Snapshot, RunKind) -> str:
    Work = os.path.join(cls.Tmp.name, "work")
    os.makedirs(Work, exist_ok=True)
    Out = os.path.join(Work, Name)
    p = lambda File: os.path.join(cls.Data, File)
    run_v2(
      segments_path=p("segments.jsonl"), docs_path=p("docs.jsonl"), doc_ids_path=p("ids.txt"), split_doc_ids_path=p("ids.txt"),
      selection_path=p("selection.json"), source_layers_path=cls.SourceLayers, criteria_path=p("criteria.md"),
      criteria_sha256=_CRITERIA_SHA, conditions=["제안"], modes=_MODES, k=3, gen_seed=7, order_seed=11,
      decompose_max_tokens=100, place_max_tokens=50, b1_max_tokens=None, model_id="합성모델", timeout_seconds=9,
      snapshot=Snapshot, run_kind=RunKind, out_dir=Out, chat_fn=make_chat(), embed_backend=_embed_backend,
      commit_fn=lambda: "b" * 40, work_root=Work, print_fn=lambda Line: None,
    )
    # 기본 볼트를 손으로 만든 노트로 바꾼다 - 보기 규칙을 정확한 값으로 검사하려고
    for Mode in _MODES:
      with open(os.path.join(Out, f"propose_{Mode}", "vault.jsonl"), "w", encoding="utf-8") as File:
        for Row in _vault():
          File.write(json.dumps(Row, ensure_ascii=False) + "\n")
    return Out

  @classmethod
  def tearDownClass(cls) -> None:
    cls.Tmp.cleanup()

  def setUp(self) -> None:
    self.DemoWork = tempfile.TemporaryDirectory()
    self.addCleanup(self.DemoWork.cleanup)

  def app(self, RunDir=None, Chat=None) -> DemoApp:
    App = DemoApp(
      RunDir or self.Demo, chat_fn=Chat or make_chat(), embed_backend=_embed_backend, commit_fn=lambda: "d" * 40,
      work_root=self.DemoWork.name, print_fn=lambda Line: None,
    )
    # 어떤 테스트든 끝날 때 작업 스레드를 join 해 스레드가 남지 않게 한다
    self.addCleanup(lambda: [Job["thread"].join(10) for Job in list(App.jobs.values())])
    return App

  def masked_run(self, **Remove) -> str:
    # 원본 실행 폴더를 건드리지 않고 manifest 의 args 만 바꾼 복사본을 만든다
    Copy = os.path.join(self.DemoWork.name, "copy_run")
    shutil.copytree(self.Demo, Copy)
    Path = os.path.join(Copy, "manifest.json")
    with open(Path, encoding="utf-8") as File:
      Manifest = json.load(File)
    for Key in Remove.get("drop", []):
      del Manifest["args"][Key]
    for Key, Value in Remove.get("set", {}).items():
      Manifest["args"][Key] = Value
    with open(Path, "w", encoding="utf-8") as File:
      json.dump(Manifest, File, ensure_ascii=False)
    return Copy

  def ids(self, Response) -> set:
    return {Note["note_id"] for Note in Response["notes"]}

  def finish(self, App, Doc="문서팀가", Mode="all_layers"):
    Status, Submitted = App.submit({"doc_id": Doc, "mode": Mode})
    self.assertEqual(Status, 202)
    Job = App.job_status(Submitted["job_id"], 10)[1]
    self.assertEqual(Job["status"], "completed")
    return Submitted["job_id"]


class SelectionTest(ViewBase):
  def test_view_selection_matches_build_view_for_every_viewer(self) -> None:
    Membership = read_membership(self.SourceLayers)
    Vault = os.path.join(self.DemoWork.name, "vault.jsonl")
    with open(Vault, "w", encoding="utf-8") as File:
      for Row in _vault():
        File.write(json.dumps(Row, ensure_ascii=False) + "\n")
    Work = os.path.join(self.DemoWork.name, "work")
    os.makedirs(Work)
    Viewers = [("개인", "샘플가"), ("개인", "샘플나"), ("개인", "샘플다"), ("팀", "팀가"), ("팀", "팀나"), ("전사", None)]
    for Index, (Layer, Group) in enumerate(Viewers):
      Included, Links, Counts = view_selection(_vault(), visible_pairs_for(Layer, Group, Membership))
      Out = os.path.join(Work, f"v{Index}")
      Manifest = build_view(Vault, self.SourceLayers, Layer, Group, Out, work_root=Work, commit_fn=lambda: "c", print_fn=lambda Line: None)
      self.assertEqual(Manifest["notes_written"], len(Included), (Layer, Group))
      for Key, Value in Counts.items():
        self.assertEqual(Manifest[Key], Value, (Layer, Group, Key))
      Written = {}
      for Name in os.listdir(os.path.join(Out, "notes")):
        with open(os.path.join(Out, "notes", Name), encoding="utf-8") as File:
          Text = File.read()
        Id = re.search(r"^- note_id: (.*)$", Text, re.M).group(1)
        Up = Text.split("## 상향 링크")[1].split("## 조건부 링크")[0]
        Down = Text.split("## 조건부 링크 ( 이 보기에서 열림 )")[1]
        Written[Id] = (re.findall(r"\[\[(.*?)\]\]", Up), re.findall(r"\[\[(.*?)\]\]", Down))
      self.assertEqual(Written, {Note["note_id"]: Links[Note["note_id"]] for Note in Included}, (Layer, Group))

  def test_missing_link_target_raises_value_error(self) -> None:
    Notes = _vault()
    Notes[0]["downward_conditional_links"][0]["target_id"] = "없는노트"
    with self.assertRaises(ValueError):
      view_selection(Notes, {("전사", None)})


class ViewersTest(ViewBase):
  def test_demo_snapshot_shows_pseudonyms(self) -> None:
    Response = self.app().viewers()
    self.assertTrue(Response["show_names"])
    Ids = [Item["viewer_id"] for Item in Response["viewers"]]
    self.assertEqual(Ids, ["개인:샘플가", "개인:샘플나", "개인:샘플다", "팀:팀가", "팀:팀나", "전사"])
    Teams = {Item["viewer_id"]: Item["teams"] for Item in Response["viewers"]}
    self.assertEqual(Teams["개인:샘플다"], ["팀가", "팀나"])
    self.assertEqual(Teams["개인:샘플가"], ["팀가"])
    self.assertEqual([Item["layer"] for Item in Response["viewers"]], ["개인"] * 3 + ["팀"] * 2 + ["전사"])

  def test_other_snapshot_masks_labels(self) -> None:
    Response = self.app(self.Real).viewers()
    self.assertFalse(Response["show_names"])
    self.assertEqual([Item["viewer_id"] for Item in Response["viewers"][:3]], ["개인:주인A", "개인:주인B", "개인:주인C"])
    for Name in _TABLE:
      self.assertNotIn(Name, json.dumps(Response, ensure_ascii=False))

  def test_missing_snapshot_or_run_kind_keys_mean_masking(self) -> None:
    # 두 키가 args 에 없으면 가리는 쪽이라 조용한 실패가 아니다
    for Drop in (["snapshot"], ["run_kind"], ["snapshot", "run_kind"]):
      self.assertFalse(self.app(self.masked_run(drop=Drop)).show_names, Drop)
      shutil.rmtree(os.path.join(self.DemoWork.name, "copy_run"))

  def test_run_kind_or_snapshot_mismatch_means_masking(self) -> None:
    self.assertFalse(self.app(self.masked_run(set={"run_kind": "pilot"})).show_names)
    shutil.rmtree(os.path.join(self.DemoWork.name, "copy_run"))
    self.assertFalse(self.app(self.masked_run(set={"snapshot": 1})).show_names)


class ViewTest(ViewBase):
  def test_spy_other_team_owner_does_not_see_first_team_or_other_owners(self) -> None:
    Response = self.app().view("all_layers", "개인:샘플나", None)[1]
    Ids = self.ids(Response)
    self.assertEqual(Ids, {"문서전사#n0", "문서팀나#n0", "문서개인C#n0"})
    self.assertNotIn("문서팀가#n0", Ids)

  def test_owner_in_two_teams_sees_both_team_notes(self) -> None:
    Ids = self.ids(self.app().view("all_layers", "개인:샘플다", None)[1])
    self.assertEqual(Ids, {"문서전사#n0", "문서팀가#n0", "문서팀가#n1", "문서팀나#n0", "문서개인E#n0"})

  def test_downward_links_open_only_when_the_condition_is_visible(self) -> None:
    App = self.app()
    First = App.view("all_layers", "개인:샘플가", None)[1]
    Company = next(Note for Note in First["notes"] if Note["note_id"] == "문서전사#n0")
    self.assertEqual(sorted(Company["opened_downward_links"]), ["문서개인A#n0", "문서팀가#n0"])
    self.assertEqual(First["counts"]["conditional_links_opened"], 2)
    self.assertEqual(First["counts"]["conditional_links_hidden"], 0)
    Second = App.view("all_layers", "개인:샘플나", None)[1]
    Company = next(Note for Note in Second["notes"] if Note["note_id"] == "문서전사#n0")
    self.assertEqual(Company["opened_downward_links"], [])
    self.assertEqual(Second["counts"]["conditional_links_hidden"], 2)
    # 닫힌 링크의 대상 id 가 응답 어디에도 없다
    self.assertNotIn("문서개인A#n0", json.dumps(Second, ensure_ascii=False))

  def test_upward_link_to_invisible_note_is_dropped_and_counted(self) -> None:
    Response = self.app().view("all_layers", "팀:팀가", None)[1]
    Note = next(Note for Note in Response["notes"] if Note["note_id"] == "문서팀가#n0")
    self.assertEqual(Note["upward_links"], [])
    self.assertEqual(Response["counts"]["upward_links_hidden"], 1)
    self.assertEqual(Response["counts"]["conditional_links_opened"], 1)

  def test_response_shape_and_group_labels(self) -> None:
    Response = self.app().view("split_by_layer", "개인:샘플가", None)[1]
    self.assertEqual(sorted(Response), ["counts", "mode", "notes", "show_names", "viewer_id"])
    self.assertEqual(
      sorted(Response["notes"][0]),
      sorted(["note_id", "title", "layer", "group_label", "body", "source_doc_id", "source_layer", "source_segment_ids",
              "upward_links", "opened_downward_links", "inserted_at_vault_size"]),
    )
    Labels = {Note["note_id"]: Note["group_label"] for Note in Response["notes"]}
    self.assertEqual(Labels["문서개인A#n0"], "샘플가")
    self.assertEqual(Labels["문서팀가#n0"], "팀가")
    self.assertIsNone(Labels["문서전사#n0"])
    self.assertIn("본문", next(Note for Note in Response["notes"] if Note["note_id"] == "문서팀가#n0")["body"])

  def test_masked_run_hides_names_bodies_and_model_titles(self) -> None:
    App = self.app(self.Real, Chat=make_chat(Title="샘플가 의 노트"))
    Viewers = App.viewers()["viewers"]
    self.assertIn("개인:주인A", [Item["viewer_id"] for Item in Viewers])
    Id = self.finish(App)
    Response = App.view("all_layers", "개인:주인A", Id)[1]
    Text = json.dumps(Response, ensure_ascii=False)
    for Name in _TABLE:
      self.assertNotIn(Name, Text)
    self.assertFalse(Response["show_names"])
    for Note in Response["notes"]:
      self.assertRegex(Note["body"], r"^\( 본문 \d+자 가림 \)$")
    self.assertIn("주인A 의 노트", [Note["title"] for Note in Response["notes"]])
    # 가린 라벨로만 보는 사람을 고를 수 있다
    self.assertEqual(App.view("all_layers", "개인:샘플가", None)[0], 400)

  def test_bad_mode_or_viewer_is_400(self) -> None:
    App = self.app()
    self.assertEqual(App.view("없는모드", "전사", None)[0], 400)
    self.assertEqual(App.view("all_layers", "개인:샘플라", None)[0], 400)
    self.assertEqual(App.view("all_layers", "팀:팀다", None)[0], 400)
    self.assertEqual(App.view("all_layers", "전사:x", None)[0], 400)


class JobOverlayTest(ViewBase):
  def test_completed_job_replaces_the_documents_base_notes(self) -> None:
    App = self.app()
    Id = self.finish(App)
    Base = App.view("all_layers", "개인:샘플가", None)[1]
    Over = App.view("all_layers", "개인:샘플가", Id)[1]
    Titles = [Note["title"] for Note in Over["notes"]]
    self.assertIn("합성 제목", Titles)
    self.assertNotIn("기존 제목 팀가", Titles)
    self.assertNotIn("기존 제목 팀가 둘째", Titles)
    self.assertIn("기존 제목 팀가", [Note["title"] for Note in Base["notes"]])
    # 다른 문서의 기존 노트는 그대로다
    self.assertIn("기존 제목 전사", Titles)
    # 지워진 기존 노트를 가리키던 링크는 빼고 수를 센다 - 옛 문서팀가#n1 을 가리키던 상향 1건과, 새 노트가 같은 id 를 받은 옛 문서팀가#n0 을 가리키던 문서전사#n0 의 하향 조건부 1건 ( 지침 3절 20 : 옛 노트로 가던 링크는 새 노트로 넘어가지 않는다 )
    Personal = next(Note for Note in Over["notes"] if Note["note_id"] == "문서개인A#n0")
    self.assertEqual(Personal["upward_links"], [])
    self.assertEqual(Over["counts"]["overlay_dangling_links_dropped"], 2)
    Overlaid, _ = App._overlay([asdict(Note) for Note in App.cells["all_layers"]["notes"]], App.jobs[Id])
    Company = next(Note for Note in Overlaid if Note["note_id"] == "문서전사#n0")
    self.assertNotIn("문서팀가#n0", [Link["target_id"] for Link in Company["downward_conditional_links"]])
    self.assertNotIn("overlay_dangling_links_dropped", Base["counts"])
    # 기본 상태는 그대로다
    self.assertEqual(self.ids(App.view("all_layers", "전사", None)[1]), {"문서전사#n0"})
    self.assertEqual(len(App.cells["all_layers"]["notes"]), 7)

  def test_links_to_a_reused_note_id_are_dropped(self) -> None:
    # 픽스처일 뿐이며 규칙과 무관하다 - 작업이 옛 노트와 같은 id ( 문서팀가#n0 ) 의 새 노트를 만든다
    # 다른 문서의 기존 노트 하나가 그 id 를 상향 링크로 가리키게 이 테스트 안에서만 복사본을 쓴다
    Linked = self.app()
    Cell = Linked.cells["all_layers"]
    Cell["notes"] = [
      replace(Note, upward_links=[*Note.upward_links, "문서팀가#n0"]) if Note.note_id == "문서개인E#n0" else Note
      for Note in Cell["notes"]
    ]
    Control = self.app()
    Viewer = "개인:샘플다"
    Base = Linked.view("all_layers", Viewer, None)[1]
    BaseNote = next(Note for Note in Base["notes"] if Note["note_id"] == "문서개인E#n0")
    self.assertIn("문서팀가#n0", BaseNote["upward_links"])
    LinkedOver = Linked.view("all_layers", Viewer, self.finish(Linked))[1]
    ControlOver = Control.view("all_layers", Viewer, self.finish(Control))[1]
    # 새 노트가 같은 id 를 받았어도 옛 노트를 가리키던 링크는 새 노트로 넘어가지 않는다
    Other = next(Note for Note in LinkedOver["notes"] if Note["note_id"] == "문서개인E#n0")
    self.assertNotIn("문서팀가#n0", Other["upward_links"])
    Company = next(Note for Note in LinkedOver["notes"] if Note["note_id"] == "문서전사#n0")
    self.assertNotIn("문서팀가#n0", Company["opened_downward_links"])
    # 뺀 수는 그 링크 하나만큼 늘어난다 : 전사 노트의 조건부 링크 1 + 개인A 의 상향 링크 1 ( 둘 다 옛 노트를 가리켰다 ) 에 더해 위 링크 1
    self.assertEqual(ControlOver["counts"]["overlay_dangling_links_dropped"], 2)
    self.assertEqual(LinkedOver["counts"]["overlay_dangling_links_dropped"], 3)
    # 새 노트 자신은 그대로 보인다
    New = next(Note for Note in LinkedOver["notes"] if Note["note_id"] == "문서팀가#n0")
    self.assertEqual(New["title"], "합성 제목")

  def test_job_status_rules(self) -> None:
    Gate_ = Gate()
    App = self.app(Chat=Gate_)
    self.addCleanup(Gate_.release.set)
    Status, Submitted = App.submit({"doc_id": "문서팀가", "mode": "all_layers"})
    self.assertEqual(Status, 202)
    self.assertTrue(Gate_.entered.wait(5))
    # 실행 중인 작업은 400
    self.assertEqual(App.view("all_layers", "전사", Submitted["job_id"])[0], 400)
    Gate_.release.set()
    self.assertEqual(App.job_status(Submitted["job_id"], 10)[1]["status"], "completed")
    # 다른 mode 는 400, 모르는 job 은 404
    self.assertEqual(App.view("split_by_layer", "전사", Submitted["job_id"])[0], 400)
    self.assertEqual(App.view("all_layers", "전사", "0" * 32)[0], 404)

  def test_failed_job_is_400(self) -> None:
    def Boom(*Args, **Kwargs):
      raise RuntimeError("합성 실패")

    App = self.app(Chat=Boom)
    Status, Submitted = App.submit({"doc_id": "문서팀가", "mode": "all_layers"})
    self.assertEqual(App.job_status(Submitted["job_id"], 10)[1]["status"], "failed")
    self.assertEqual(App.view("all_layers", "전사", Submitted["job_id"])[0], 400)


class HttpTest(ViewBase):
  def serve(self, App, Cors=None) -> str:
    Server = make_server(App, "127.0.0.1", 0, cors_origin=Cors)
    Thread = threading.Thread(target=Server.serve_forever, daemon=True)
    Thread.start()
    self.addCleanup(Thread.join, 5)
    self.addCleanup(Server.server_close)
    self.addCleanup(Server.shutdown)
    return f"http://127.0.0.1:{Server.server_address[1]}"

  def call(self, Base, Path, Method="GET"):
    Request = urllib.request.Request(Base + Path, method=Method)
    try:
      with urllib.request.urlopen(Request, timeout=15) as Response:
        Raw = Response.read()
        return Response.status, (json.loads(Raw.decode("utf-8")) if Raw else None), Response.headers
    except urllib.error.HTTPError as Error:
      with Error:
        Raw = Error.read()
        return Error.code, (json.loads(Raw.decode("utf-8")) if Raw else None), Error.headers

  def test_viewers_and_view_over_http(self) -> None:
    Base = self.serve(self.app())
    Status, Viewers, _ = self.call(Base, "/viewers")
    self.assertEqual((Status, Viewers["show_names"]), (200, True))
    Status, View, _ = self.call(Base, "/view?mode=all_layers&viewer=%EC%A0%84%EC%82%AC")
    self.assertEqual(Status, 200)
    self.assertEqual(self.ids(View), {"문서전사#n0"})
    for Query in ("", "?mode=all_layers", "?viewer=%EC%A0%84%EC%82%AC", "?mode=a&mode=b&viewer=x", "?mode=all_layers&viewer=%EC%A0%84%EC%82%AC&job=a&job=b",
                  "?mode=&viewer=x"):
      self.assertEqual(self.call(Base, "/view" + Query)[0], 400, Query)
    self.assertEqual(self.call(Base, "/view?mode=all_layers&viewer=%EC%A0%84%EC%82%AC&job=" + "0" * 32)[0], 404)

  def test_no_cors_option_means_no_headers_and_options_404(self) -> None:
    Base = self.serve(self.app())
    Status, _, Headers = self.call(Base, "/health")
    self.assertEqual(Status, 200)
    self.assertIsNone(Headers.get("Access-Control-Allow-Origin"))
    self.assertEqual(self.call(Base, "/health", "OPTIONS")[0], 404)

  def test_cors_option_adds_headers_and_options_204(self) -> None:
    Base = self.serve(self.app(), Cors="http://127.0.0.1:8123")
    for Path in ("/health", "/viewers", "/view?mode=bad&viewer=x"):
      Status, _, Headers = self.call(Base, Path)
      self.assertEqual(Headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:8123", Path)
    Status, Body, Headers = self.call(Base, "/view", "OPTIONS")
    self.assertEqual(Status, 204)
    self.assertIsNone(Body)
    self.assertEqual(Headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:8123")
    self.assertEqual(Headers.get("Access-Control-Allow-Methods"), "GET, POST, OPTIONS")
    self.assertEqual(Headers.get("Access-Control-Allow-Headers"), "Content-Type")

  def test_parse_args_cors_origin_is_optional(self) -> None:
    self.assertIsNone(D.parse_args(["--run-dir", "r", "--host", "h", "--port", "1"]).cors_origin)
    self.assertEqual(D.parse_args(["--run-dir", "r", "--host", "h", "--port", "1", "--cors-origin", "http://x"]).cors_origin, "http://x")


if __name__ == "__main__":
  unittest.main()
