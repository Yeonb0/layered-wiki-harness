import importlib.util
import json
import os
import tempfile
import unittest

# deploy/demo-cloudrun 은 하이픈이 있어 패키지로 가져올 수 없다 : 파일 경로로 불러온다
_PATH = os.path.join(os.path.dirname(__file__), "..", "deploy", "demo-cloudrun", "stage_inputs.py")
_SPEC = importlib.util.spec_from_file_location("stage_inputs", _PATH)
stage_inputs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stage_inputs)

_KEYS = ("segments", "docs", "doc_ids", "split_doc_ids", "selection", "source_layers", "criteria")


class StageInputsTest(unittest.TestCase):
  # 픽스처일 뿐이며 규칙과 무관하다 - 경로 · 내용은 합성
  def setUp(self) -> None:
    self.Tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.Tmp.cleanup)
    self.Src = os.path.join(self.Tmp.name, "inputs_src")
    os.makedirs(self.Src)
    self.Run = os.path.join(self.Tmp.name, "work", "demo", "demo900_run")
    os.makedirs(os.path.join(self.Run, "propose_all_layers"))
    with open(os.path.join(self.Run, "propose_all_layers", "vault.jsonl"), "w") as F:
      F.write("{}\n")
    Args = {"snapshot": 900, "run_kind": "demo", "model_id": "m"}
    for Key in _KEYS:
      Path = os.path.join(self.Src, f"{Key}.dat")
      with open(Path, "w") as F:
        F.write(Key)
      Args[Key] = Path
    # 같은 파일을 두 키가 가리키는 경우 (doc_ids = split_doc_ids)
    Args["split_doc_ids"] = Args["doc_ids"]
    self.write_manifest(Args)
    self.Out = os.path.join(self.Tmp.name, "material")

  def write_manifest(self, Args) -> None:
    with open(os.path.join(self.Run, "manifest.json"), "w") as F:
      json.dump({"status": "completed", "args": Args}, F)

  def test_copies_inputs_and_rewrites_paths(self) -> None:
    stage_inputs.stage(self.Run, self.Out)
    with open(os.path.join(self.Out, "run", "demo900_run", "manifest.json")) as F:
      Args = json.load(F)["args"]
    for Key in _KEYS:
      self.assertTrue(Args[Key].startswith("/app/inputs/"), Key)
      Local = os.path.join(self.Out, "inputs", os.path.basename(Args[Key]))
      with open(Local) as F:
        self.assertEqual(F.read(), "doc_ids" if Key == "split_doc_ids" else Key)
    self.assertTrue(os.path.isfile(os.path.join(self.Out, "run", "demo900_run", "propose_all_layers", "vault.jsonl")))

  def test_original_manifest_is_untouched(self) -> None:
    Before = open(os.path.join(self.Run, "manifest.json")).read()
    stage_inputs.stage(self.Run, self.Out)
    self.assertEqual(open(os.path.join(self.Run, "manifest.json")).read(), Before)

  def test_refuses_non_demo_run(self) -> None:
    for Over in ({"snapshot": 1}, {"run_kind": "experiment"}):
      Args = json.load(open(os.path.join(self.Run, "manifest.json")))["args"]
      Args.update(Over)
      self.write_manifest(Args)
      with self.assertRaises(ValueError, msg=str(Over)):
        stage_inputs.stage(self.Run, os.path.join(self.Out, str(len(Over))))

  def test_refuses_real_corpus_path(self) -> None:
    Real = os.path.join(self.Tmp.name, "layered-wiki-corpus", "segments.jsonl")
    os.makedirs(os.path.dirname(Real))
    open(Real, "w").close()
    Args = json.load(open(os.path.join(self.Run, "manifest.json")))["args"]
    Args["segments"] = Real
    self.write_manifest(Args)
    with self.assertRaises(ValueError):
      stage_inputs.stage(self.Run, self.Out)

  def test_missing_input_raises(self) -> None:
    Args = json.load(open(os.path.join(self.Run, "manifest.json")))["args"]
    Args["criteria"] = os.path.join(self.Src, "없음.md")
    self.write_manifest(Args)
    with self.assertRaises(FileNotFoundError):
      stage_inputs.stage(self.Run, self.Out)

  def test_out_dir_must_not_exist(self) -> None:
    os.makedirs(self.Out)
    with self.assertRaises(FileExistsError):
      stage_inputs.stage(self.Run, self.Out)


if __name__ == "__main__":
  unittest.main()
