"""라벨링 뷰 · 빈 라벨 표 생성 ( docs/labeling_criteria_v2.md 1 장 )

뷰 : 문서 단위, title 한 줄 + 세그먼트 텍스트에 [n] 표지. 경로 · doc_id · 출처 · 층 · 그룹 · properties 는 넣지 않는다
대상 : 지정한 분리 ( pilot / main ) 문서 중 출처가 team_1jo · team_soft_eng 인 문서. Lecture Note 는 라벨링하지 않는다
문서 순서 : 시드 고정 무작위. 대응표 ( 문서 순번 · n → doc_id · segment_id ) 는 _key 폴더에 따로 둔다
출력은 코퍼스 본문을 담으므로 코퍼스 저장소에만 쓴다
"""
import argparse
import collections
import hashlib
import json
import os
import random

LABEL_SOURCES = {"team_1jo", "team_soft_eng"}
TSV_HEADER = ["doc", "n", "layer", "clause", "also_hit", "confidence", "rationale"]


def read_jsonl(path):
  with open(path, encoding="utf-8") as f:
    return [json.loads(l) for l in f]


def read_ids(path):
  with open(path, encoding="utf-8") as f:
    return [l.strip() for l in f if l.strip()]


def doc_view(doc_no, title, Segs):
  Parts = [f"## 문서 {doc_no}", f"제목 : {title if title is not None else '( 제목 없음 )'}", ""]
  for s in Segs:
    Parts += [f"[{s['seq']}]", s["text"], ""]
  return "\n".join(Parts)


def build(seg_dir, split_dir, split_name, seed):
  Docs = {d["doc_id"]: d for d in read_jsonl(os.path.join(seg_dir, "docs.jsonl"))}
  Segs = collections.defaultdict(list)
  for s in read_jsonl(os.path.join(seg_dir, "segments.jsonl")):
    Segs[s["doc_id"]].append(s)
  Ids = read_ids(os.path.join(split_dir, f"{split_name}_doc_ids.txt"))
  Missing = [i for i in Ids if i not in Docs]
  if Missing:
    raise ValueError(f"docs.jsonl 에 없는 doc_id {Missing[:3]}")
  Target = sorted(i for i in Ids if Docs[i]["source"] in LABEL_SOURCES)
  if not Target:
    raise ValueError("라벨링 대상 문서가 없음")
  random.Random(seed).shuffle(Target)

  Views, Rows, Key = [], [], []
  width = max(2, len(str(len(Target))))
  for k, doc_id in enumerate(Target, 1):
    doc_no = f"D{k:0{width}d}"
    S = sorted(Segs[doc_id], key=lambda s: s["seq"])
    if not S:
      raise ValueError(f"세그먼트 없는 문서 {doc_id}")
    view = doc_view(doc_no, Docs[doc_id]["title"], S)
    Views.append(view)
    vsha = hashlib.sha256(view.encode("utf-8")).hexdigest()
    for s in S:
      Rows.append([doc_no, str(s["seq"]), "", "", "", "", ""])
      Key.append({"doc": doc_no, "n": s["seq"], "doc_id": doc_id, "segment_id": s["segment_id"], "view_sha256": vsha})
  return Views, Rows, Key


def run(seg_dir, split_dir, split_name, seed, out_dir):
  Views, Rows, Key = build(seg_dir, split_dir, split_name, seed)
  os.makedirs(os.path.join(out_dir, "_key"), exist_ok=True)
  with open(os.path.join(out_dir, "view.md"), "w", encoding="utf-8") as f:
    f.write("\n\n".join(Views) + "\n")
  with open(os.path.join(out_dir, "labels_template.tsv"), "w", encoding="utf-8") as f:
    f.write("\t".join(TSV_HEADER) + "\n")
    for r in Rows:
      f.write("\t".join(r) + "\n")
  with open(os.path.join(out_dir, "_key", "key.jsonl"), "w", encoding="utf-8") as f:
    for k in Key:
      f.write(json.dumps(k, ensure_ascii=False) + "\n")
  Meta = {"split": split_name, "order_seed": seed, "docs": len(Views), "segments": len(Rows)}
  with open(os.path.join(out_dir, "_key", "meta.json"), "w", encoding="utf-8") as f:
    json.dump(Meta, f, ensure_ascii=False, indent=2)
    f.write("\n")
  return Meta


def main():
  p = argparse.ArgumentParser()
  p.add_argument("--segments", required=True)
  p.add_argument("--split-dir", required=True)
  p.add_argument("--split", required=True, choices=["pilot", "main"])
  p.add_argument("--seed", required=True, type=int)
  p.add_argument("--out", required=True)
  a = p.parse_args()
  ex = os.path.expanduser
  print(json.dumps(run(ex(a.segments), ex(a.split_dir), a.split, a.seed, ex(a.out)), ensure_ascii=False))


if __name__ == "__main__":
  main()
