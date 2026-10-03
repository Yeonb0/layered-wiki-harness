"""파일럿 · 본실험 문서 분리 ( 실행 순서 4, 사용자 승인 2026-10-03 )

단위 : Notion 페이지 하나와 그 하위 페이지 전체. 그룹 루트 ( 1조 루트 페이지, 개인 페이지 주인 허브 ) 는
하위를 묶지 않고 자기만 단위가 된다. DB 폴더는 페이지가 아니므로 단위 루트가 되지 않는다.
층화 : 전사 / 팀|그룹 / 개인|주인. 층마다 k = max ( 1, floor ( 0.15 n + 0.5 ) ) 단위를 파일럿으로 ( n ≥ 2 ).
같은 title 이 파일럿과 본실험에 나뉘면 ValueError
"""
import argparse
import collections
import json
import math
import os
import random

from segmentation.segment import PAGE_ID_RE

SPLIT_VERSION = "split_v1"
PILOT_FRACTION = 0.15


def read_jsonl(path):
  with open(path, encoding="utf-8") as f:
    return [json.loads(l) for l in f]


def stratum(doc):
  if doc["layer"] == "전사":
    return "전사"
  if doc["layer"] in ("팀", "개인") and doc["group"]:
    return f"{doc['layer']}|{doc['group']}"
  raise ValueError(f"층화 불가 {doc['doc_id']}")


def is_group_root(doc):
  # 1조 루트 페이지, 개인 페이지 주인 허브 ( 1조/<주인> <id>.md )
  depth = len(doc["path"].split("/"))
  if doc["source"] == "team_1jo" and depth == 1:
    return True
  return doc["layer"] == "개인" and depth == 2


def unit_roots(Docs):
  """doc_id → 단위 루트 doc_id"""
  By_folder = {}
  for d in Docs:
    m = PAGE_ID_RE.search(d["path"])
    if m and not is_group_root(d):
      By_folder[d["path"][:m.start()]] = d["doc_id"]
  Roots = {}
  for d in Docs:
    Parts = d["path"].split("/")
    root = d["doc_id"]
    for k in range(1, len(Parts)):
      folder = "/".join(Parts[:k])
      if folder in By_folder:
        root = By_folder[folder]
        break
    Roots[d["doc_id"]] = root
  return Roots


def pilot_count(n):
  if n < 2:
    return 0
  return max(1, math.floor(PILOT_FRACTION * n + 0.5))


def split(Docs, seed):
  Roots = unit_roots(Docs)
  By_id = {d["doc_id"]: d for d in Docs}
  Units = collections.defaultdict(list)
  for d in Docs:
    Units[Roots[d["doc_id"]]].append(d["doc_id"])
  Strata = collections.defaultdict(list)
  for root, Members in Units.items():
    S = {stratum(By_id[m]) for m in Members}
    if len(S) != 1:
      raise ValueError(f"단위 안에 층이 섞임 {root} {S}")
    Strata[S.pop()].append(root)

  rng = random.Random(seed)
  Pilot_units = set()
  for s in sorted(Strata):
    Roots_sorted = sorted(Strata[s])
    Pilot_units.update(rng.sample(Roots_sorted, pilot_count(len(Roots_sorted))))

  Assign = {}
  for root, Members in Units.items():
    for m in Members:
      Assign[m] = "pilot" if root in Pilot_units else "main"

  Titles = collections.defaultdict(set)
  for d in Docs:
    if d["title"] is not None:
      Titles[d["title"]].add(Assign[d["doc_id"]])
  Crossing = sorted(t for t, v in Titles.items() if len(v) > 1)
  if Crossing:
    raise ValueError(f"같은 title 이 파일럿 · 본실험에 나뉨 {Crossing}")

  Unit_rows = []
  for root in sorted(Units):
    Members = sorted(Units[root])
    Unit_rows.append({
      "unit_id": root, "stratum": stratum(By_id[root]) if root in By_id else None,
      "split": "pilot" if root in Pilot_units else "main",
      "doc_ids": Members, "n_segments": sum(By_id[m]["n_segments"] for m in Members),
    })
  return Assign, Unit_rows, Strata, Pilot_units


def run(seg_dir, out_dir, seed):
  Docs = read_jsonl(os.path.join(seg_dir, "docs.jsonl"))
  Assign, Unit_rows, Strata, Pilot_units = split(Docs, seed)
  Report = {
    "split_version": SPLIT_VERSION, "seed": seed, "pilot_fraction": PILOT_FRACTION,
    "units_by_stratum": {s: len(v) for s, v in sorted(Strata.items())},
    "pilot_units_by_stratum": {s: sum(1 for r in v if r in Pilot_units) for s, v in sorted(Strata.items())},
    "docs_by_split": collections.Counter(Assign.values()),
    "segments_by_split_stratum": collections.Counter(f"{u['split']}|{u['stratum']}" for u in Unit_rows for _ in range(u["n_segments"])),
  }
  os.makedirs(out_dir, exist_ok=True)
  with open(os.path.join(out_dir, "units.jsonl"), "w", encoding="utf-8") as f:
    for u in Unit_rows:
      f.write(json.dumps(u, ensure_ascii=False) + "\n")
  for name in ("pilot", "main"):
    with open(os.path.join(out_dir, f"{name}_doc_ids.txt"), "w", encoding="utf-8") as f:
      for doc_id in sorted(k for k, v in Assign.items() if v == name):
        f.write(doc_id + "\n")
  with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
    json.dump(Report, f, ensure_ascii=False, indent=2)
    f.write("\n")
  return Report


def main():
  p = argparse.ArgumentParser()
  p.add_argument("--segments", required=True)
  p.add_argument("--out", required=True)
  p.add_argument("--seed", required=True, type=int)
  a = p.parse_args()
  ex = os.path.expanduser
  print(json.dumps(run(ex(a.segments), ex(a.out), a.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
