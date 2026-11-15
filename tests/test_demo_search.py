import hashlib
import json
import os
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

import serve.demo_api as D
from serve.demo_api import DemoApp, make_server
from tests.test_demo_view import _MODES, _embed_backend, _note, _vault, make_chat, ViewBase

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 노트 7개와 합성 소속 표 ( 샘플가 = 팀가, 샘플나 = 팀나, 샘플다 = 팀가 · 팀나 ) 를 그대로 쓴다
# 픽스처 임베딩은 글자 수 나머지로 만든 2차원 값이라 점수가 겹치는 일이 흔하다 - 정렬 규칙은 점수가 겹쳐도 성립해야 한다


class _StubMinutes:
  # 회의록 저장소 대신 승인된 회의록 노트 한 묶음만 내는 합성 저장소 - 픽스처일 뿐이며 규칙과 무관하다
  def __init__(self, Notes) -> None:
    self.Notes = Notes

  def docs(self):
    return [{"doc_id": "901합성", "mode": "all_layers", "status": "decided", "approved_notes": self.Notes}]


class SearchBase(ViewBase):
  def search(self, App, Mode, Viewer, Query, K=10):
    return App.search(Mode, Viewer, Query, K)

  def viewer_ids(self, App) -> list:
    return [Item["viewer_id"] for Item in App.viewers()["viewers"]]

  def snapshot(self, *Roots) -> dict:
    # 폴더 아래 모든 파일의 상대 경로와 내용 해시 - 파일이 새로 생기거나 바뀌면 달라진다
    Result = {}
    for Root in Roots:
      for Dir, _, Names in os.walk(Root):
        for Name in Names:
          Path = os.path.join(Dir, Name)
          with open(Path, "rb") as File:
            Result[Path] = hashlib.sha256(File.read()).hexdigest()
    return Result


class SearchRuleTest(SearchBase):
  def test_spy_other_team_notes_never_appear_for_a_one_team_owner(self) -> None:
    App = self.app()
    Owners = [Item for Item in App.viewers()["viewers"] if Item["layer"] == "개인" and len(Item["teams"]) == 1]
    self.assertTrue(Owners, "픽스처에 팀 하나에만 속한 개인이 없다")
    for Owner in Owners:
      Other = [Row for Row in _vault() if Row["layer"] == "팀" and Row["group"] not in Owner["teams"]]
      self.assertTrue(Other, "다른 팀 노트가 픽스처에 없다")
      for Mode in _MODES:
        # 다른 팀 노트가 /view 에도 없다는 전제가 서야 이 검사가 뜻을 가진다
        ViewIds = {Note["note_id"] for Note in App.view(Mode, Owner["viewer_id"], None)[1]["notes"]}
        for Row in Other:
          self.assertNotIn(Row["note_id"], ViewIds)
          Query = Row["title"] + "\n" + Row["body"]
          Status, Body = self.search(App, Mode, Owner["viewer_id"], Query)
          self.assertEqual(Status, 200)
          self.assertTrue(Body["results"])
          Found = {Item["note_id"] for Item in Body["results"]}
          self.assertNotIn(Row["note_id"], Found)
          self.assertNotIn(Row["note_id"], Body["context"])
          self.assertNotIn(Row["title"], Body["context"])

  def test_results_are_subset_of_view_and_considered_equals_view_size(self) -> None:
    App = self.app()
    for Mode in _MODES:
      for Viewer in self.viewer_ids(App):
        ViewStatus, View = App.view(Mode, Viewer, None)
        self.assertEqual(ViewStatus, 200)
        Status, Body = self.search(App, Mode, Viewer, "합성 질문")
        self.assertEqual(Status, 200, (Mode, Viewer))
        ViewIds = {Note["note_id"] for Note in View["notes"]}
        self.assertLessEqual({Item["note_id"] for Item in Body["results"]}, ViewIds)
        self.assertEqual(Body["considered"], len(View["notes"]))

  def test_k_larger_than_candidates_returns_all_and_order_follows_the_rule(self) -> None:
    App = self.app()
    for Mode in _MODES:
      for Viewer in self.viewer_ids(App):
        Count = len(App.view(Mode, Viewer, None)[1]["notes"])
        Body = self.search(App, Mode, Viewer, "합성 질문", 10)[1]
        self.assertEqual(len(Body["results"]), min(10, Count))
        self.assertEqual([Item["rank"] for Item in Body["results"]], list(range(1, len(Body["results"]) + 1)))
        Pairs = [(-Item["score"], Item["note_id"]) for Item in Body["results"]]
        self.assertEqual(Pairs, sorted(Pairs))
        # k 가 후보 수보다 작으면 앞쪽만 남는다
        Small = self.search(App, Mode, Viewer, "합성 질문", 1)[1]
        self.assertEqual([Item["note_id"] for Item in Small["results"]], [Item["note_id"] for Item in Body["results"][:1]])

  def test_equal_scores_are_ordered_by_note_id(self) -> None:
    # 모든 노트가 같은 벡터라 점수가 모두 같다 - 이때 순서는 note_id 오름차순뿐이다
    App = DemoApp(
      self.Demo, chat_fn=make_chat(), embed_backend=lambda Texts: [[1.0, 1.0] for _ in Texts], commit_fn=lambda: "d" * 40,
      work_root=self.DemoWork.name, print_fn=lambda Line: None,
    )
    Body = self.search(App, "all_layers", "개인:샘플다", "합성 질문")[1]
    Ids = [Item["note_id"] for Item in Body["results"]]
    self.assertGreater(len(Ids), 1)
    self.assertEqual(Ids, sorted(Ids))
    self.assertEqual(len({Item["score"] for Item in Body["results"]}), 1)

  def test_unknown_mode_or_viewer_passes_the_view_400_through(self) -> None:
    App = self.app()
    for Mode, Viewer in (("없는모드", "전사"), ("all_layers", "없는사람")):
      Status, Body = self.search(App, Mode, Viewer, "합성 질문")
      self.assertEqual((Status, Body), App.view(Mode, Viewer, None))
      self.assertEqual(Status, 400)

  def test_approved_minutes_note_is_a_candidate_and_its_vector_is_cached(self) -> None:
    Calls = []

    def Backend(Texts):
      Calls.append(list(Texts))
      return _embed_backend(Texts)

    App = DemoApp(
      self.Demo, chat_fn=make_chat(), embed_backend=Backend, commit_fn=lambda: "d" * 40,
      work_root=self.DemoWork.name, print_fn=lambda Line: None,
    )
    Extra = _note("901합성#n0", "전사", None, "901합성", "승인된 회의록 노트")
    App.minutes = _StubMinutes([Extra])
    Body = self.search(App, "all_layers", "전사", "합성 질문")[1]
    self.assertIn("901합성#n0", {Item["note_id"] for Item in Body["results"]})
    self.assertEqual(Body["considered"], len(App.view("all_layers", "전사", None)[1]["notes"]))
    # 색인에 없던 노트만 문장째 한 번 더 임베딩되고 두 번째 호출에서는 캐시를 쓴다
    Before = sum(1 for Call in Calls if Call and "승인된 회의록 노트" in Call[0])
    self.assertEqual(Before, 1)
    self.search(App, "all_layers", "전사", "다른 질문")
    After = sum(1 for Call in Calls if Call and "승인된 회의록 노트" in Call[0])
    self.assertEqual(After, 1)

  def test_a_note_without_a_vector_is_a_500_not_silently_skipped(self) -> None:
    App = self.app()
    # 색인에 없는 노트가 보기에 들어오면 벡터를 구할 수 없다 - 보기 쪽에서 그 노트를 만들어 낸다
    Extra = _note("901합성#n1", "전사", None, "901합성", "벡터 없는 노트")
    App.minutes = _StubMinutes([Extra])
    Original = App._overlay_vector

    def Broken(Mode, NoteId, Backend):
      raise ValueError("벡터를 구할 수 없는 노트: " + NoteId)

    App._overlay_vector = Broken
    try:
      Status, Body = self.search(App, "all_layers", "전사", "합성 질문")
    finally:
      App._overlay_vector = Original
    self.assertEqual(Status, 500)
    self.assertFalse(Body["ok"])

  def test_hidden_bodies_do_not_leak_when_names_are_masked(self) -> None:
    # 실제 코퍼스 모양의 실행 - show_names 가 거짓이라 본문은 글자 수로 가려진다
    App = self.app(RunDir=self.Real)
    self.assertFalse(App.show_names)
    Raw = [Row["body"] for Row in _vault()]
    for Mode in _MODES:
      for Viewer in self.viewer_ids(App):
        Status, Body = self.search(App, Mode, Viewer, "합성 질문")
        self.assertEqual(Status, 200)
        Text = json.dumps(Body, ensure_ascii=False)
        for Item in Body["results"]:
          self.assertRegex(Item["body"], r"^\( 본문 [0-9]+자 가림 \)$")
        for Row in Raw:
          self.assertNotIn(Row, Text)
          self.assertNotIn(Row, Body["context"])


class SearchWriteTest(SearchBase):
  def test_search_does_not_change_any_file(self) -> None:
    for RunDir in (self.Demo, self.Real):
      App = self.app(RunDir=RunDir)
      Before = self.snapshot(RunDir, self.DemoWork.name)
      for Mode in _MODES:
        for Viewer in self.viewer_ids(App):
          self.assertEqual(self.search(App, Mode, Viewer, "합성 질문")[0], 200)
      self.assertEqual(self.snapshot(RunDir, self.DemoWork.name), Before)


class SearchHttpTest(SearchBase):
  def serve(self, App) -> str:
    Server = make_server(App, "127.0.0.1", 0)
    Thread = threading.Thread(target=Server.serve_forever, daemon=True)
    Thread.start()
    self.addCleanup(Thread.join, 5)
    self.addCleanup(Server.server_close)
    self.addCleanup(Server.shutdown)
    return f"http://127.0.0.1:{Server.server_address[1]}"

  def call(self, Base, Query):
    try:
      with urllib.request.urlopen(Base + "/search" + Query, timeout=15) as Response:
        return Response.status, json.loads(Response.read().decode("utf-8"))
    except urllib.error.HTTPError as Error:
      with Error:
        return Error.code, json.loads(Error.read().decode("utf-8"))

  def query(self, **Params) -> str:
    return "?" + urllib.parse.urlencode(Params)

  def test_search_over_http_returns_200(self) -> None:
    Base = self.serve(self.app())
    Status, Body = self.call(Base, self.query(mode="all_layers", viewer="개인:샘플다", q="합성 질문", k="3"))
    self.assertEqual(Status, 200)
    self.assertEqual(
      set(Body), {"mode", "viewer_id", "show_names", "query", "k", "considered", "results", "context"}
    )
    self.assertEqual((Body["mode"], Body["viewer_id"], Body["query"], Body["k"]), ("all_layers", "개인:샘플다", "합성 질문", 3))
    self.assertEqual(len(Body["results"]), 3)
    self.assertEqual(
      set(Body["results"][0]),
      {"rank", "note_id", "title", "layer", "group_label", "source_doc_id", "source_segment_ids", "score", "body"},
    )
    # context 는 결과를 순서대로 "[note_id] (층 · group_label) 제목\n본문" 으로 잇고 사이에 빈 줄 하나를 둔다
    Blocks = Body["context"].split("\n\n")
    self.assertEqual(len(Blocks), 3)
    for Block, Item in zip(Blocks, Body["results"]):
      Head, _, Text = Block.partition("\n")
      self.assertTrue(Head.startswith(f"[{Item['note_id']}] ("))
      self.assertTrue(Head.endswith(") " + Item["title"]))
      self.assertEqual(Text, Item["body"])

  def test_bad_parameters_are_400_and_nothing_is_defaulted(self) -> None:
    Base = self.serve(self.app())
    Good = {"mode": "all_layers", "viewer": "전사", "q": "합성 질문", "k": "3"}
    self.assertEqual(self.call(Base, self.query(**Good))[0], 200)
    Cases = []
    for Key in Good:
      Missing = {Name: Value for Name, Value in Good.items() if Name != Key}
      Cases.append(("빠짐 " + Key, self.query(**Missing)))
      Cases.append(("중복 " + Key, self.query(**Good) + "&" + urllib.parse.urlencode({Key: Good[Key]})))
      Cases.append(("빈 값 " + Key, self.query(**{**Good, Key: ""})))
    for Label, Value in (("k=0", "0"), ("k=11", "11"), ("k=a", "a"), ("k=1.5", "1.5"), ("k=-1", "-1")):
      Cases.append((Label, self.query(**{**Good, "k": Value})))
    Cases.append(("q 501자", self.query(**{**Good, "q": "가" * (D.MAX_QUERY_CHARS + 1)})))
    Cases.append(("모르는 viewer", self.query(**{**Good, "viewer": "없는사람"})))
    Cases.append(("모르는 mode", self.query(**{**Good, "mode": "없는모드"})))
    Cases.append(("매개변수 없음", ""))
    for Label, Query in Cases:
      Status, Body = self.call(Base, Query)
      self.assertEqual(Status, 400, Label)
      self.assertFalse(Body["ok"], Label)

  def test_limits_are_inclusive(self) -> None:
    Base = self.serve(self.app())
    Good = {"mode": "all_layers", "viewer": "전사", "q": "합성 질문", "k": "3"}
    self.assertEqual(self.call(Base, self.query(**{**Good, "k": "1"}))[0], 200)
    self.assertEqual(self.call(Base, self.query(**{**Good, "k": str(D.MAX_SEARCH_K)}))[0], 200)
    self.assertEqual(self.call(Base, self.query(**{**Good, "q": "가" * D.MAX_QUERY_CHARS}))[0], 200)


if __name__ == "__main__":
  unittest.main()
