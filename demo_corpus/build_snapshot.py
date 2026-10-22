"""합성 시연 코퍼스 ( 스냅샷 900 ) 를 Notion 내보내기 모양의 코퍼스 루트로 빌드한다

사용자 결정 2026-10-22 : 합성 시연 코퍼스는 시연 경로 전용이며 실험 코퍼스 · 정답셋 · 평가 결과와 섞지 않는다
사용자 결정 2026-10-22 : Notion 내보내기 모양으로 만들고 세그먼트 규칙 v1.1 을 그대로 거친다
같은 입력이면 같은 바이트가 나온다 ( zip 시각 · 권한 · 압축 방식 고정 )
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import zipfile

from segmentation.segment import doc_id_for

CORPUS_DIR = os.path.dirname(os.path.abspath(__file__))
# 사용자 결정 2026-10-22 : 합성 시연 코퍼스의 스냅샷 번호는 실험 코퍼스 ( 1 ) 와 겹치지 않게 900 이다
SNAPSHOT = 900
# zip 안의 시각을 고정해야 같은 입력이 같은 바이트가 된다
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
# 권한 비트도 고정한다 ( 만든 환경의 umask 가 바이트에 들어가지 않게 )
ZIP_EXTERNAL_ATTR = 0o644 << 16
# 만든 운영체제 표지도 고정한다 ( 플랫폼마다 기본값이 다르다 )
ZIP_CREATE_SYSTEM = 3
SELECTION_FILES = ("source_layers.json", "lecture_subjects.json")


def _read_json(path):
  with open(path, encoding="utf-8") as File:
    return json.load(File)


def _source_dir_files(source_dir):
  # pages/<출처>/ 기준 상대 경로 ( / 구분 ) 를 정렬 순서로
  Paths = []
  for Root, _, Names in os.walk(source_dir):
    for Name in Names:
      Paths.append(os.path.relpath(os.path.join(Root, Name), source_dir).replace(os.sep, "/"))
  return sorted(Paths)


def _zip_bytes(source_dir, Paths):
  Buffer = io.BytesIO()
  with zipfile.ZipFile(Buffer, "w", zipfile.ZIP_STORED) as Zf:
    for Path in Paths:
      Info = zipfile.ZipInfo(Path, date_time=ZIP_DATE_TIME)
      Info.external_attr = ZIP_EXTERNAL_ATTR
      Info.create_system = ZIP_CREATE_SYSTEM
      Info.compress_type = zipfile.ZIP_STORED
      with open(os.path.join(source_dir, *Path.split("/")), "rb") as File:
        Zf.writestr(Info, File.read())
  return Buffer.getvalue()


def build(out_root):
  # 이미 있는 폴더에 쓰면 이전 빌드와 섞인다
  if os.path.exists(out_root):
    raise ValueError(f"out_root 가 이미 있다: {out_root}")
  Layer_cfg = _read_json(os.path.join(CORPUS_DIR, "selection", "source_layers.json"))
  Sources = Layer_cfg.get("sources") if isinstance(Layer_cfg, dict) else None
  # 출처 목록은 설정 파일의 sources 에서만 나온다 - 코드에 기본 목록을 두지 않는다
  if not isinstance(Sources, dict) or not Sources:
    raise ValueError("source_layers.json 에 sources 가 없다")
  Names = sorted(Sources)
  Pages_root = os.path.join(CORPUS_DIR, "pages")
  # pages/ 아래의 폴더 · 파일이 sources 에 없으면 어느 출처에 속하는지 알 수 없다
  Extra = sorted(set(os.listdir(Pages_root)) - set(Names))
  if Extra:
    raise ValueError(f"pages/ 아래에 sources 에 없는 항목이 있다: {Extra}")

  Zips = {}
  Ids = []
  for Name in Names:
    Source_dir = os.path.join(Pages_root, Name)
    # 출처 폴더가 없거나 문서가 없으면 빈 출처가 조용히 스냅샷에 들어간다
    if not os.path.isdir(Source_dir):
      raise ValueError(f"pages/{Name}/ 가 없다")
    Paths = _source_dir_files(Source_dir)
    Mds = [P for P in Paths if P.lower().endswith(".md")]
    if not Mds:
      raise ValueError(f"pages/{Name}/ 에 .md 문서가 없다")
    Ids += [doc_id_for(P) for P in Mds]
    Zips[Name] = _zip_bytes(Source_dir, Paths)
  # 문서 id 가 겹치면 정답 · 로그 행이 서로 덮인다
  if len(set(Ids)) != len(Ids):
    raise ValueError("문서 id 가 겹친다")

  Raw_dir = os.path.join(out_root, "snapshot1", "raw")
  os.makedirs(Raw_dir)
  Files = []
  for Name in Names:
    with open(os.path.join(Raw_dir, Name + ".zip"), "xb") as File:
      File.write(Zips[Name])
    Files.append({"source": Name, "path": f"raw/{Name}.zip", "sha256": hashlib.sha256(Zips[Name]).hexdigest()})
  Manifest = {"snapshot": SNAPSHOT, "files": Files}
  with open(os.path.join(out_root, "snapshot1", "manifest.json"), "x", encoding="utf-8") as File:
    json.dump(Manifest, File, ensure_ascii=False, indent=2)
    File.write("\n")
  os.makedirs(os.path.join(out_root, "selection"))
  for Name in SELECTION_FILES:
    shutil.copyfile(os.path.join(CORPUS_DIR, "selection", Name), os.path.join(out_root, "selection", Name))
  # 시연 코퍼스는 전부 시연용이라 투입 목록과 분할 목록이 같다
  for Name in ("doc_ids.txt", "split_doc_ids.txt"):
    with open(os.path.join(out_root, Name), "x", encoding="utf-8") as File:
      File.write("".join(f"{Id}\n" for Id in sorted(Ids)))
  return Manifest


def main(argv=None):
  Parser = argparse.ArgumentParser(description="합성 시연 코퍼스 ( 스냅샷 900 ) 빌드")
  # 기본 출력 경로를 두지 않는다 - 실험 코퍼스 폴더에 잘못 쓰는 일을 막는다
  Parser.add_argument("--out", required=True)
  Args = Parser.parse_args(argv)
  Manifest = build(os.path.expanduser(Args.out))
  print(f"built snapshot={Manifest['snapshot']} sources={len(Manifest['files'])}")


if __name__ == "__main__":
  main()
