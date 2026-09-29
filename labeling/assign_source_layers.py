import argparse
import json
import os
import random
import unicodedata

from retrieval.search import LAYER_ORDER

# v1 §5.1 - 인자로 바꿀 수 없다
SEED = 20260926


def _read_ids(path: str) -> list[str]:
  with open(path, "r", encoding="utf-8") as File:
    return [Line.rstrip("\n") for Line in File if Line.strip()]


def _read_excluded_ids(exclusions_path: str, split: str) -> set[str]:
  if not os.path.exists(exclusions_path):
    # v1 §1 - 제외 규칙 적용 후 목록만 배정 대상
    raise ValueError(f"exclusions.jsonl 이 없다: {exclusions_path!r}")
  Excluded: set[str] = set()
  with open(exclusions_path, "r", encoding="utf-8") as File:
    for Line in File:
      Line = Line.strip()
      if not Line:
        continue
      Record = json.loads(Line)
      if Record.get("split") == split:
        Excluded.add(Record["doc_id"])
  return Excluded


def _stratum(doc_id: str) -> str:
  return doc_id.split("/", 1)[0]


def _check_no_duplicate_ids(ids: list[str]) -> None:
  Seen: set[str] = set()
  Duplicates: set[str] = set()
  for Id in ids:
    if Id in Seen:
      Duplicates.add(Id)
    Seen.add(Id)
  if Duplicates:
    # 중복 id 가 두 번 배정되면 층화 개수가 어긋난다
    raise ValueError(f"입력 목록에 중복된 id 가 있다: {sorted(Duplicates)!r}")


def _check_exclusions_exist_in_ids(excluded_ids: set[str], ids: list[str]) -> None:
  Missing = sorted(excluded_ids - set(ids))
  if Missing:
    # v1 §1 - 제외 대상이 조용히 무시되면 제외돼야 할 문서가 배정에 남는다
    raise ValueError(f"exclusions.jsonl 의 doc_id 가 입력 목록에 없다: {Missing!r}")


def _check_no_stratum_nfc_collision(by_stratum: dict[str, list[str]]) -> None:
  SeenNfc: dict[str, str] = {}
  for Stratum in by_stratum:
    Nfc = unicodedata.normalize("NFC", Stratum)
    if Nfc in SeenNfc and SeenNfc[Nfc] != Stratum:
      # 같은 폴더가 둘로 갈라지면 v1 §5 폴더 층화가 깨진다
      raise ValueError(f"NFC 정규화 후 충돌하는 stratum 이 있다: {SeenNfc[Nfc]!r}, {Stratum!r}")
    SeenNfc[Nfc] = Stratum


def assign_source_layers(id_list_path: str, exclusions_path: str, split: str, output_path: str) -> None:
  if os.path.exists(output_path):
    # v1 §5.6 재추첨 금지
    raise ValueError(f"출력 파일이 이미 있다: {output_path!r}")

  RawIds = _read_ids(id_list_path)
  _check_no_duplicate_ids(RawIds)

  ExcludedIds = _read_excluded_ids(exclusions_path, split)
  _check_exclusions_exist_in_ids(ExcludedIds, RawIds)
  Ids = [Id for Id in RawIds if Id not in ExcludedIds]

  SeenNfc: dict[str, str] = {}
  for Id in Ids:
    Nfc = unicodedata.normalize("NFC", Id)
    if Nfc in SeenNfc and SeenNfc[Nfc] != Id:
      raise ValueError(f"NFC 정규화 후 충돌하는 id 가 있다: {SeenNfc[Nfc]!r}, {Id!r}")
    SeenNfc[Nfc] = Id

  ByStratum: dict[str, list[str]] = {}
  for Id in Ids:
    ByStratum.setdefault(_stratum(Id), []).append(Id)

  _check_no_stratum_nfc_collision(ByStratum)

  StratumOrder = sorted(ByStratum, key=lambda S: unicodedata.normalize("NFC", S))

  Rng = random.Random(SEED)
  Records: list[dict] = []
  for StratumIndex, Stratum in enumerate(StratumOrder):
    StratumIds = sorted(ByStratum[Stratum], key=lambda I: unicodedata.normalize("NFC", I))
    Rng.shuffle(StratumIds)
    StartIndex = StratumIndex % 3
    for Position, Id in enumerate(StratumIds):
      Layer = LAYER_ORDER[(StartIndex + Position) % 3]
      Records.append(
        {
          "doc_id": Id,
          "stratum": Stratum,
          "source_layer": Layer,
          "seed": SEED,
          # 개인 층 사용자 수 미결정 - v1 §5 사용자 귀속은 빈칸
          "personal_user": None,
        }
      )

  with open(output_path, "w", encoding="utf-8") as File:
    for Record in Records:
      File.write(json.dumps(Record, ensure_ascii=False))
      File.write("\n")


def _parse_args() -> argparse.Namespace:
  Parser = argparse.ArgumentParser(description="출처 층 배정 (라벨링 기준 v1 §5)")
  Parser.add_argument("--ids", required=True, help="문서 id 목록 파일, 한 줄 한 id, corpus 상대 경로")
  Parser.add_argument("--exclusions", required=True, help="exclusions.jsonl 경로")
  Parser.add_argument("--split", required=True, help="split 이름")
  Parser.add_argument("--out", required=True, help="출력 경로")
  return Parser.parse_args()


def main() -> None:
  Args = _parse_args()
  assign_source_layers(Args.ids, Args.exclusions, Args.split, Args.out)


if __name__ == "__main__":
  main()
