import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import runner.v2_sequential as V2
from agent.layer_block import MARK
from agent.llm_client import ChatResult
from retrieval.search import Retriever
from runner.v2_sequential import git_head_commit, run_v2

# 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
_CRITERIA = f"## 가 {MARK}\n합성 본문\n## 나\n".encode("utf-8")
_CRITERIA_SHA = hashlib.sha256(_CRITERIA).hexdigest()
_DOC_COUNT = 6


def _embed_backend(Texts: list[str]) -> list[list[float]]:
  # 합성 임베딩 - 글자 수로 만든 2차원 벡터이며 서버를 부르지 않는다
  return [[float(len(Text) % 5 + 1), float(len(Text) % 3 + 1)] for Text in Texts]


def _result(Obj) -> ChatResult:
  return ChatResult(
    text=json.dumps(Obj, ensure_ascii=False), finish_reason="stop", prompt_tokens=10, completion_tokens=5,
    elapsed_seconds=0.1, timings=None, request_body={}, response_body={},
  )


def fake_chat(messages, model_id, config, response_schema, *, timeout_seconds):
  # 스키마 모양으로 어떤 호출인지 알아보고 항상 노트 하나짜리 합성 출력을 낸다
  Props = response_schema["properties"]
  if "notes" in Props:
    Labels = Props["assign"]["required"]
    return _result({
      "assign": {Label: 1 for Label in Labels},
      "notes": [{"title": "합성 노트", "layer": "팀", "upward_links": [], "downward_links": [], "rationale": "합성 근거"}],
    })
  if "assign" in Props:
    return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["합성 노트"]})
  return _result({"layer": "팀", "upward_links": [], "downward_links": [], "rationale": "합성 근거"})


def fake_chat_above_source(messages, model_id, config, response_schema, *, timeout_seconds):
  # 층별 분리 모드에서 출처 위 층을 내는 가짜 출력 - 스키마 enum 을 무시한다
  Props = response_schema["properties"]
  if "notes" in Props:
    return _result({
      "assign": {Label: 1 for Label in Props["assign"]["required"]},
      "notes": [{"title": "합성 노트", "layer": "전사", "upward_links": [], "downward_links": [], "rationale": "합성 근거"}],
    })
  if "assign" in Props:
    return _result({"assign": {Label: 1 for Label in Props["assign"]["required"]}, "titles": ["합성 노트"]})
  return _result({"layer": "전사", "upward_links": [], "downward_links": [], "rationale": "합성 근거"})


class Corpus:
  # 합성 코퍼스를 임시 폴더에 만든다 - 실제 코퍼스는 쓰지 않는다
  def __init__(self, Root: str) -> None:
    self.Root = Root
    self.Ids = [f"문서{Index}" for Index in range(_DOC_COUNT)]
    self.write()

  def path(self, Name: str) -> str:
    return os.path.join(self.Root, Name)

  def write(self, Segments=None, Docs=None, Ids=None, Split=None, Excluded=None) -> None:
    Segments = Segments if Segments is not None else [
      {"segment_id": f"{Id}-s{Seq}", "doc_id": Id, "seq": Seq, "layer": "팀", "group": "그룹A", "text": f"{Id} 합성 글 {Seq}"}
      for Id in self.Ids for Seq in (1, 2)
    ]
    Docs = Docs if Docs is not None else [
      {"doc_id": Id, "title": f"{Id} 제목", "layer": "팀", "group": "그룹A", "raw_sha256": f"{Index:064d}"}
      for Index, Id in enumerate(self.Ids)
    ]
    Ids = Ids if Ids is not None else self.Ids
    Split = Split if Split is not None else self.Ids
    Excluded = Excluded if Excluded is not None else ["제외문서"]
    with open(self.path("segments.jsonl"), "w", encoding="utf-8") as File:
      File.write("".join(json.dumps(Row, ensure_ascii=False) + "\n" for Row in Segments))
    with open(self.path("docs.jsonl"), "w", encoding="utf-8") as File:
      File.write("".join(json.dumps(Row, ensure_ascii=False) + "\n" for Row in Docs))
    with open(self.path("ids.txt"), "w", encoding="utf-8") as File:
      File.write("".join(f"{Id}\n" for Id in Ids))
    with open(self.path("split.txt"), "w", encoding="utf-8") as File:
      File.write("".join(f"{Id}\n" for Id in Split))
    with open(self.path("selection.json"), "w", encoding="utf-8") as File:
      json.dump({"excluded_pages": {"reason": "합성", "ids": Excluded}}, File, ensure_ascii=False)
    with open(self.path("source_layers.json"), "w", encoding="utf-8") as File:
      json.dump({"team_1jo_personal_owners": ["주인A"]}, File, ensure_ascii=False)
    with open(self.path("criteria.md"), "wb") as File:
      File.write(_CRITERIA)


class RunV2TestBase(unittest.TestCase):
  def setUp(self) -> None:
    self.Tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.Tmp.cleanup)
    self.Work = os.path.join(self.Tmp.name, "work")
    os.makedirs(self.Work)
    self.Data = os.path.join(self.Tmp.name, "data")
    os.makedirs(self.Data)
    self.Corpus = Corpus(self.Data)
    self.Lines = []
    self.RunCount = 0

  def kwargs(self, **Over) -> dict:
    self.RunCount += 1
    Args = dict(
      segments_path=self.Corpus.path("segments.jsonl"), docs_path=self.Corpus.path("docs.jsonl"),
      doc_ids_path=self.Corpus.path("ids.txt"), split_doc_ids_path=self.Corpus.path("split.txt"),
      selection_path=self.Corpus.path("selection.json"), source_layers_path=self.Corpus.path("source_layers.json"),
      criteria_path=self.Corpus.path("criteria.md"), criteria_sha256=_CRITERIA_SHA,
      conditions=["제안", "B1"], modes=["all_layers", "split_by_layer"], k=4, gen_seed=7, order_seed=11,
      decompose_max_tokens=100, place_max_tokens=50, b1_max_tokens=200, model_id="합성모델", timeout_seconds=9,
      snapshot=1, run_kind="synthetic", out_dir=os.path.join(self.Work, f"run{self.RunCount}"),
      chat_fn=fake_chat, embed_backend=_embed_backend, commit_fn=lambda: "c" * 40, work_root=self.Work,
      print_fn=self.Lines.append,
    )
    Args.update(Over)
    return Args

  def read_json(self, Path: str) -> dict:
    with open(Path, encoding="utf-8") as File:
      return json.load(File)

  def read_jsonl(self, Path: str) -> list:
    with open(Path, encoding="utf-8") as File:
      return [json.loads(Line) for Line in File]

  def cell_names(self) -> list[str]:
    return ["propose_all_layers", "propose_split_by_layer", "b1_all_layers", "b1_split_by_layer"]


class ScheduleTest(RunV2TestBase):
  def test_doc_order_is_same_in_every_cell_and_cell_order_is_shuffled(self) -> None:
    Manifest = run_v2(**self.kwargs())
    Order = Manifest["schedule"]["doc_order"]
    for Name in self.cell_names():
      Log = self.read_jsonl(os.path.join(Manifest["args"]["out_dir"], Name, "log.jsonl"))
      Seen = []
      for Entry in Log:
        if Entry["doc_id"] not in Seen:
          Seen.append(Entry["doc_id"])
      self.assertEqual(Seen, Order)
    # 문서마다 셀 순서를 섞으므로 모든 문서의 셀 순서가 같지는 않다
    self.assertGreater(len({tuple(Cells) for Cells in Manifest["schedule"]["cell_order_per_doc"].values()}), 1)

  def test_same_order_seed_same_schedule_different_seed_different(self) -> None:
    First = run_v2(**self.kwargs())["schedule"]
    Same = run_v2(**self.kwargs())["schedule"]
    Other = run_v2(**self.kwargs(order_seed=12))["schedule"]
    self.assertEqual(First, Same)
    self.assertNotEqual(First, Other)

  def test_vault_size_before_follows_each_cells_own_vault_even_when_cell_order_shuffles(self) -> None:
    Manifest = run_v2(**self.kwargs())
    for Name in self.cell_names():
      Log = self.read_jsonl(os.path.join(Manifest["args"]["out_dir"], Name, "log.jsonl"))
      First = [Entry for Entry in Log if Entry["entry_type"] in ("decompose", "b1_call")]
      self.assertEqual([Entry["vault_size_before"] for Entry in First], list(range(_DOC_COUNT)))


class CellIsolationTest(RunV2TestBase):
  def test_cells_do_not_share_vault_or_retriever(self) -> None:
    Made = []

    class SpyRetriever(Retriever):
      def __init__(self, embed_backend) -> None:
        super().__init__(embed_backend=embed_backend)
        Made.append(self)

    with mock.patch.object(V2, "Retriever", SpyRetriever):
      Manifest = run_v2(**self.kwargs())
    self.assertEqual(len(Made), 4)
    self.assertEqual(len({id(Retr) for Retr in Made}), 4)
    # 각 Retriever 의 색인 크기가 그 셀 볼트 행 수와 같다 - 다른 셀 노트가 섞이지 않았다
    for Name, Retr in zip(self.cell_names(), Made):
      Rows = self.read_jsonl(os.path.join(Manifest["args"]["out_dir"], Name, "vault.jsonl"))
      self.assertEqual(len(Retr.Index), len(Rows))
    # 후보 수가 그 셀 볼트 크기를 넘지 않는다
    for Name in self.cell_names():
      for Entry in self.read_jsonl(os.path.join(Manifest["args"]["out_dir"], Name, "log.jsonl")):
        if Entry["entry_type"] == "place":
          self.assertLessEqual(len(Entry["candidates"]), min(4, Entry["vault_size_before"]))


class ModeCallTest(RunV2TestBase):
  def test_modes_reach_the_run_functions_per_cell_on_same_doc_list(self) -> None:
    Calls = []
    RealPropose = V2.run_propose_doc
    RealB1 = V2.run_b1_doc

    def SpyPropose(doc, mode, *Rest):
      Calls.append(("제안", mode, doc.doc_id))
      return RealPropose(doc, mode, *Rest)

    def SpyB1(doc, mode, *Rest):
      Calls.append(("B1", mode, doc.doc_id))
      return RealB1(doc, mode, *Rest)

    with mock.patch.object(V2, "run_propose_doc", SpyPropose), mock.patch.object(V2, "run_b1_doc", SpyB1):
      run_v2(**self.kwargs())
    for Condition in ("제안", "B1"):
      for Mode in ("all_layers", "split_by_layer"):
        Docs = [DocId for C, M, DocId in Calls if C == Condition and M == Mode]
        self.assertEqual(sorted(Docs), sorted(self.Corpus.Ids))
    self.assertEqual({M for _, M, _ in Calls}, {"all_layers", "split_by_layer"})


class InputValidationTest(RunV2TestBase):
  def _expect_value_error(self, **Over) -> None:
    with self.assertRaises(ValueError):
      run_v2(**self.kwargs(**Over))

  def test_empty_id_list(self) -> None:
    self.Corpus.write(Ids=[])
    self._expect_value_error()

  def test_duplicate_ids(self) -> None:
    self.Corpus.write(Ids=[self.Corpus.Ids[0], self.Corpus.Ids[0]])
    self._expect_value_error()

  def test_id_not_in_split(self) -> None:
    self.Corpus.write(Split=self.Corpus.Ids[:-1])
    self._expect_value_error()

  def test_id_in_excluded_pages(self) -> None:
    self.Corpus.write(Excluded=[self.Corpus.Ids[0]])
    self._expect_value_error()

  def test_doc_without_segments(self) -> None:
    Segments = [
      {"segment_id": f"{Id}-s1", "doc_id": Id, "seq": 1, "layer": "팀", "group": "그룹A", "text": "합성"}
      for Id in self.Corpus.Ids[1:]
    ]
    self.Corpus.write(Segments=Segments)
    self._expect_value_error()

  def test_segments_with_different_layer_or_group(self) -> None:
    for Field, Value in (("layer", "전사"), ("group", "그룹B")):
      with self.subTest(Field):
        Segments = [
          {"segment_id": f"{Id}-s{Seq}", "doc_id": Id, "seq": Seq, "layer": "팀", "group": "그룹A", "text": "합성"}
          for Id in self.Corpus.Ids for Seq in (1, 2)
        ]
        Segments[1][Field] = Value
        self.Corpus.write(Segments=Segments)
        self._expect_value_error()

  def test_segments_differ_from_docs_jsonl(self) -> None:
    Docs = [
      {"doc_id": Id, "title": "합성", "layer": "전사", "group": None, "raw_sha256": "0" * 64} for Id in self.Corpus.Ids
    ]
    self.Corpus.write(Docs=Docs)
    self._expect_value_error()

  def test_title_not_string(self) -> None:
    Docs = [
      {"doc_id": Id, "title": 123, "layer": "팀", "group": "그룹A", "raw_sha256": "0" * 64} for Id in self.Corpus.Ids
    ]
    self.Corpus.write(Docs=Docs)
    self._expect_value_error()

  def test_unimplemented_conditions_and_unknown_mode(self) -> None:
    for Conditions in (["B0"], ["B2"], ["제안", "B2"], ["없는조건"]):
      with self.subTest(Conditions):
        self._expect_value_error(conditions=Conditions)
    self._expect_value_error(modes=["other_mode"])
    self._expect_value_error(conditions=[])

  def test_missing_max_tokens_only_for_cells_that_need_them(self) -> None:
    self._expect_value_error(decompose_max_tokens=None)
    self._expect_value_error(place_max_tokens=None)
    self._expect_value_error(conditions=["B1"], b1_max_tokens=None)
    # 쓰지 않는 상한이 비어 있는 것은 허용한다
    run_v2(**self.kwargs(conditions=["B1"], decompose_max_tokens=None, place_max_tokens=None))
    run_v2(**self.kwargs(conditions=["제안"], b1_max_tokens=None))

  def test_out_dir_outside_work_root_or_existing(self) -> None:
    self._expect_value_error(out_dir=os.path.join(self.Tmp.name, "밖"))
    Existing = os.path.join(self.Work, "있음")
    os.makedirs(Existing)
    self._expect_value_error(out_dir=Existing)
    self._expect_value_error(out_dir=self.Work)

  def test_commit_fn_value_error_propagates_before_any_output(self) -> None:
    def Dirty() -> str:
      raise ValueError("커밋 안 된 변경")

    Kwargs = self.kwargs(commit_fn=Dirty)
    with self.assertRaises(ValueError):
      run_v2(**Kwargs)
    self.assertFalse(os.path.exists(Kwargs["out_dir"]))


class GitHeadCommitTest(unittest.TestCase):
  def test_dirty_tracked_file_raises_value_error_and_clean_returns_hash(self) -> None:
    with tempfile.TemporaryDirectory() as Repo:
      Git = ["git", "-C", Repo, "-c", "user.name=합성", "-c", "user.email=synthetic@example.invalid"]
      subprocess.run(["git", "-C", Repo, "init", "-q"], check=True)
      with open(os.path.join(Repo, "파일.txt"), "w", encoding="utf-8") as File:
        File.write("합성 1")
      subprocess.run(Git + ["add", "파일.txt"], check=True)
      subprocess.run(Git + ["commit", "-q", "-m", "합성 커밋"], check=True)
      Head = subprocess.run(["git", "-C", Repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
      self.assertEqual(git_head_commit(Repo), Head)
      with open(os.path.join(Repo, "파일.txt"), "w", encoding="utf-8") as File:
        File.write("합성 2")
      with self.assertRaises(ValueError):
        git_head_commit(Repo)
      with open(os.path.join(Repo, "파일.txt"), "w", encoding="utf-8") as File:
        File.write("합성 1")
      self.assertEqual(git_head_commit(Repo), Head)
      # 미추적 파일도 import 되면 실행 코드라 막는다
      Untracked = os.path.join(Repo, "새파일.py")
      with open(Untracked, "w", encoding="utf-8") as File:
        File.write("합성 = 1")
      with self.assertRaises(ValueError):
        git_head_commit(Repo)
      os.remove(Untracked)
      self.assertEqual(git_head_commit(Repo), Head)


class OutputFilesTest(RunV2TestBase):
  def test_manifest_log_and_vault_contents(self) -> None:
    Manifest = run_v2(**self.kwargs())
    Out = Manifest["args"]["out_dir"]
    Disk = self.read_json(os.path.join(Out, "manifest.json"))
    self.assertEqual(Disk["status"], "completed")
    self.assertIsNone(Disk["error"])
    for Key in (
      "trial_id", "args", "schedule", "harness_commit", "input_sha256", "layer_block_sha256", "model_id", "endpoints",
      "embed_max_chars", "excerpt_length", "pythonhashseed", "python_version", "started_at_utc", "ended_at_utc",
    ):
      self.assertIn(Key, Disk)
    self.assertEqual(Disk["harness_commit"], "c" * 40)
    self.assertEqual(
      sorted(Disk["input_sha256"]),
      ["criteria", "doc_ids", "docs", "segments", "selection", "source_layers", "split_doc_ids"],
    )
    self.assertEqual(Disk["embed_max_chars"], 4000)
    self.assertEqual(len(Disk["schedule"]["entries"]), _DOC_COUNT * 4)
    BaseKeys = (
      "trial_id", "run_kind", "snapshot", "harness_commit", "model_id", "criteria_sha256", "condition", "mode", "k",
      "gen_seed", "order_seed", "decompose_max_tokens", "place_max_tokens", "b1_max_tokens", "doc_order_index",
      "schedule_index", "raw_sha256",
    )
    for Name in self.cell_names():
      Log = self.read_jsonl(os.path.join(Out, Name, "log.jsonl"))
      Rows = self.read_jsonl(os.path.join(Out, Name, "vault.jsonl"))
      for Entry in Log:
        for Key in BaseKeys:
          self.assertIn(Key, Entry)
        self.assertEqual(Entry["trial_id"], Disk["trial_id"])
        if Name.startswith("b1_"):
          self.assertIsNone(Entry["decompose_max_tokens"])
          self.assertIsNone(Entry["place_max_tokens"])
          self.assertEqual(Entry["b1_max_tokens"], 200)
        else:
          self.assertEqual(Entry["decompose_max_tokens"], 100)
          self.assertEqual(Entry["place_max_tokens"], 50)
          self.assertIsNone(Entry["b1_max_tokens"])
      # 볼트 행 수 = 성공한 노트 수
      self.assertEqual(len(Rows), sum(1 for Entry in Log if Entry["entry_type"] == "place" and Entry["ok"]))
      self.assertEqual(len(Rows), _DOC_COUNT)

  def test_screen_lines_have_only_numbers_and_ids(self) -> None:
    run_v2(**self.kwargs())
    self.assertEqual(len(self.Lines), _DOC_COUNT * 4)
    for Line in self.Lines:
      self.assertNotIn("합성 노트", Line)
      self.assertNotIn("합성 근거", Line)
      self.assertRegex(Line, r"^\d+ \w+ 문서\d entries=\d+ ok=\d+ elapsed_s=\d+\.\d$")


class ManifestStatusTest(RunV2TestBase):
  def test_manifest_is_running_at_first_chat_call_and_completed_at_end(self) -> None:
    Kwargs = self.kwargs(conditions=["제안"], modes=["all_layers"])
    Seen = []

    def Spy(messages, model_id, config, response_schema, *, timeout_seconds):
      # 첫 호출 시점에 manifest 를 읽어 기록한다
      if not Seen:
        Seen.append(self.read_json(os.path.join(Kwargs["out_dir"], "manifest.json")))
      return fake_chat(messages, model_id, config, response_schema, timeout_seconds=timeout_seconds)

    Kwargs["chat_fn"] = Spy
    run_v2(**Kwargs)
    self.assertEqual(Seen[0]["status"], "running")
    self.assertIsNone(Seen[0]["ended_at_utc"])
    for Key in ("trial_id", "schedule", "harness_commit", "input_sha256", "layer_block_sha256"):
      self.assertIn(Key, Seen[0])
    Final = self.read_json(os.path.join(Kwargs["out_dir"], "manifest.json"))
    self.assertEqual(Final["status"], "completed")
    self.assertEqual(Final["trial_id"], Seen[0]["trial_id"])


class AbortTest(RunV2TestBase):
  def test_value_error_during_run_writes_aborted_manifest_and_reraises(self) -> None:
    Kwargs = self.kwargs(conditions=["제안"], modes=["split_by_layer"], chat_fn=fake_chat_above_source)
    with self.assertRaises(ValueError):
      run_v2(**Kwargs)
    Disk = self.read_json(os.path.join(Kwargs["out_dir"], "manifest.json"))
    self.assertEqual(Disk["status"], "aborted")
    self.assertEqual(Disk["error"]["type"], "ValueError")
    self.assertIn("split_by_layer", Disk["error"]["message"])
    self.assertIsNotNone(Disk["ended_at_utc"])


if __name__ == "__main__":
  unittest.main()
