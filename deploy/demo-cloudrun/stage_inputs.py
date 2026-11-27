# 공개 시연 서버 빌드 재료 : 미리 돌린 실행 폴더와 그 manifest 가 가리키는 입력 파일을 재료 폴더로 옮긴다
# manifest 의 입력 경로는 관리자님 WSL 의 절대 경로라 컨테이너에 없다 : 복사본 manifest 만 /app/inputs/ 로 고친다 (원본은 그대로)
# 합성 시연 코퍼스 (snapshot 900, run_kind demo) 만 받는다 : 지침 3절 18 · 21, 실제 코퍼스는 이미지에 넣지 않는다
import argparse
import json
import os
import shutil

INPUT_KEYS = ("segments", "docs", "doc_ids", "split_doc_ids", "selection", "source_layers", "criteria")
DEMO_SNAPSHOT = 900
DEMO_RUN_KIND = "demo"
CONTAINER_INPUTS = "/app/inputs"
# 실제 코퍼스 원문이 있는 곳 (harness .gitignore 주석) : 경로에 이 이름이 있으면 멈춘다
REAL_CORPUS_MARK = "layered-wiki-corpus"


def stage(run_dir: str, out_dir: str) -> None:
  # 재료 폴더가 이미 있으면 다른 실행의 찌꺼기가 섞일 수 있다
  if os.path.exists(out_dir):
    raise FileExistsError(f"재료 폴더가 이미 있다: {out_dir}")
  with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as F:
    Manifest = json.load(F)
  Args = Manifest["args"]
  if Args.get("snapshot") != DEMO_SNAPSHOT or Args.get("run_kind") != DEMO_RUN_KIND:
    raise ValueError(f"합성 시연 실행이 아니다: snapshot={Args.get('snapshot')!r} run_kind={Args.get('run_kind')!r}")
  Sources = {}
  for Key in INPUT_KEYS:
    Path = os.path.realpath(os.path.expanduser(Args[Key]))
    if REAL_CORPUS_MARK in Path.split(os.sep):
      raise ValueError(f"실제 코퍼스 경로를 가리킨다: {Key}")
    if not os.path.isfile(Path):
      raise FileNotFoundError(f"입력 파일이 없다: {Key}")
    Sources[Key] = Path
  RunName = os.path.basename(os.path.normpath(run_dir))
  shutil.copytree(run_dir, os.path.join(out_dir, "run", RunName))
  Inputs = os.path.join(out_dir, "inputs")
  os.makedirs(Inputs)
  for Key, Path in Sources.items():
    # 키 이름을 붙여 서로 다른 폴더의 같은 파일 이름이 겹치지 않게
    Name = f"{Key}__{os.path.basename(Path)}"
    shutil.copy2(Path, os.path.join(Inputs, Name))
    Args[Key] = f"{CONTAINER_INPUTS}/{Name}"
  with open(os.path.join(out_dir, "run", RunName, "manifest.json"), "w", encoding="utf-8") as F:
    json.dump(Manifest, F, ensure_ascii=False, indent=2)


def main(argv=None) -> None:
  Parser = argparse.ArgumentParser(description="미리 돌린 시연 실행과 입력 파일을 빌드 재료 폴더로")
  Parser.add_argument("--run-dir", required=True)
  Parser.add_argument("--out-dir", required=True)
  Args = Parser.parse_args(argv)
  stage(os.path.expanduser(Args.run_dir), Args.out_dir)


if __name__ == "__main__":
  main()
