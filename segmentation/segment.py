"""세그먼트 · 제외 규칙 v1 ( docs/segment_rules_v1.md ) 구현

코퍼스 원문은 로컬 전용 저장소에만 있다. 이 모듈은 공개 저장소에 있으므로
페이지 본문 · 개인 페이지 주인 이름을 상수로 넣지 않는다 ( 주인 목록은 코퍼스 설정 파일 )
"""
import argparse
import collections
import csv
import hashlib
import io
import json
import os
import re
import zipfile

RULES_VERSION = "segment_rules_v1"

PAGE_ID_RE = re.compile(r" ([0-9a-f]{32})\.md$")
CSV_ALL_RE = re.compile(r" [0-9a-f]{32}_all\.csv$")
HEADING_RE = re.compile(r"^#{1,3} ")
FENCE_RE = re.compile(r"^\s*```")
IMG_ALT_RE = re.compile(r"^\s*!\[([^\]]*)\]")

# P3 장식, 15단계 빈도 근거
BANNER_ALT = "하얀리본라인3.png"
INDEX_LINE = "- Index"
FOOTER_RULE = "---"
FOOTER_HEAD = "- 자주 사용하는 특수 문자"

# E2 · E3 확정 제외 경로
TODOS_PREFIX = "1조/TODOs"
SOFT_ENG_KEEP_PREFIX = "소프트웨어 공학/과제/"
SOFT_ENG_KEEP_FILES = {"소프트웨어 공학/00_공용_기준문서.md"}

SOURCES = {"lecture_note", "team_1jo", "team_soft_eng"}


def load_json(path):
  with open(path, encoding="utf-8") as f:
    return json.load(f)


def sha256_text(s):
  return hashlib.sha256(s.encode("utf-8")).hexdigest()


def doc_id_for(path):
  # 파일명 32자리 id, 없으면 첨부로 보고 경로 해시
  m = PAGE_ID_RE.search(path)
  if m:
    return m.group(1)
  return "att-" + sha256_text(path)[:16]


def doc_exclusion(source, path, doc_id, Excluded_ids):
  # E1 ~ E3, 해당 없으면 None
  if doc_id in Excluded_ids:
    return "E1_탐색표본"
  if source == "team_1jo" and path.startswith(TODOS_PREFIX):
    return "E2_TODOs"
  if source == "team_soft_eng":
    if not (path.startswith(SOFT_ENG_KEEP_PREFIX) or path in SOFT_ENG_KEEP_FILES):
      return "E3_소공범위밖"
  return None


def db_property_keys(zf):
  # _all.csv 경로에서 " <id>_all.csv" 를 뗀 폴더 경로 → 첫 열을 뺀 열 이름 목록
  Keys = {}
  for n in zf.namelist():
    if not CSV_ALL_RE.search(n):
      continue
    head = zf.read(n).decode("utf-8-sig", errors="replace").splitlines()[:1]
    if not head:
      continue
    Cols = next(csv.reader(io.StringIO(head[0])))
    Keys[CSV_ALL_RE.sub("", n)] = [c for c in Cols[1:] if c]
  return Keys


def split_title_and_properties(Lines, Prop_keys):
  """P1 · P2. Lines 는 (줄 번호, 원문) 목록. 남은 본문, title, properties 를 돌려준다"""
  Body = list(Lines)
  title = None
  if Body and Body[0][1].startswith("# "):
    title = Body[0][1][2:].strip()
    Body = Body[1:]
  Props = {}
  if Prop_keys:
    i = 0
    while i < len(Body):
      text = Body[i][1]
      if not text.strip():
        i += 1
        continue
      key = next((k for k in Prop_keys if text.startswith(k + ": ") or text == k + ":"), None)
      if key is None:
        break
      Props[key] = text[len(key) + 1:].strip()
      Body.pop(i)
  return Body, title, Props


def heading_flags(Body):
  # 코드 블록 밖 0열 # · ## · ### 만 경계
  Flags = []
  in_fence = False
  for _, text in Body:
    if FENCE_RE.match(text):
      in_fence = not in_fence
      Flags.append(False)
      continue
    Flags.append((not in_fence) and bool(HEADING_RE.match(text)))
  return Flags


def strip_decorations(Body, Stats):
  """P3. 배너 이미지, 첫 경계 앞 - Index, 꼬리말 블록"""
  Out = []
  for ln, text in Body:
    m = IMG_ALT_RE.match(text)
    if m and m.group(1) == BANNER_ALT:
      Stats["banner"] += 1
      continue
    Out.append((ln, text))

  Flags = heading_flags(Out)
  first_heading = next((i for i, f in enumerate(Flags) if f), len(Out))
  Kept = []
  for i, (ln, text) in enumerate(Out):
    if i < first_heading and text.strip() == INDEX_LINE:
      Stats["index"] += 1
      continue
    Kept.append((ln, text))

  Result = []
  i = 0
  while i < len(Kept):
    text = Kept[i][1]
    if text.strip() == FOOTER_RULE:
      j = i + 1
      while j < len(Kept) and not Kept[j][1].strip():
        j += 1
      if j < len(Kept) and Kept[j][1].strip() == FOOTER_HEAD:
        Stats["footer"] += 1
        k = j + 1
        while k < len(Kept) and (not Kept[k][1].strip() or Kept[k][1][:1] in (" ", "\t")):
          k += 1
        if k < len(Kept):
          Stats["footer_trailing_content"] += 1
        i = k
        continue
    Result.append(Kept[i])
    i += 1
  return Result


def trim(Seg):
  while Seg and not Seg[0][1].strip():
    Seg = Seg[1:]
  while Seg and not Seg[-1][1].strip():
    Seg = Seg[:-1]
  return Seg


def split_segments(Body):
  """B1 ~ B6. 세그먼트별 (줄 번호, 원문) 목록의 목록"""
  Flags = heading_flags(Body)
  Raw = [[]]
  for (ln, text), is_head in zip(Body, Flags):
    if is_head:
      Raw.append([])
    Raw[-1].append((ln, text))
  Segs = [s for s in (trim(r) for r in Raw) if s]

  def heading_only(s):
    return len([1 for _, t in s if t.strip()]) == 1 and bool(HEADING_RE.match(s[0][1]))

  # B4 헤딩만 있는 세그먼트는 다음 세그먼트 앞에, 마지막이면 직전 세그먼트 끝에
  Merged = []
  Carry = []
  for s in Segs:
    if heading_only(s):
      Carry += s
      continue
    Merged.append(Carry + s)
    Carry = []
  if Carry:
    if Merged:
      Merged[-1] = Merged[-1] + Carry
    else:
      Merged.append(Carry)
  return Merged


def source_layer(source, path, Owners):
  if source == "lecture_note":
    return "전사", None
  if source == "team_soft_eng":
    return "팀", "소공"
  if source == "team_1jo":
    Parts = path.split("/")
    if len(Parts) >= 2:
      owner = PAGE_ID_RE.sub("", Parts[1])
      if owner.endswith(".md"):
        owner = owner[:-3]
      if owner in Owners:
        return "개인", owner
    return "팀", "1조"
  raise ValueError(f"알 수 없는 출처 {source}")


def process_doc(raw_text, Prop_keys, Stats):
  Lines = list(enumerate(raw_text.splitlines(), 1))
  Body, title, Props = split_title_and_properties(Lines, Prop_keys)
  Body = strip_decorations(Body, Stats)
  return title, Props, split_segments(Body)


def run(corpus_root, out_dir):
  Manifest = load_json(os.path.join(corpus_root, "snapshot1", "manifest.json"))
  Selection = load_json(os.path.join(corpus_root, "selection", "lecture_subjects.json"))
  Layer_cfg = load_json(os.path.join(corpus_root, "selection", "source_layers.json"))
  Excluded_ids = set(Selection["excluded_pages"]["ids"])
  Owners = set(Layer_cfg["team_1jo_personal_owners"])
  if not Owners:
    raise ValueError("개인 페이지 주인 목록이 비어 있음")

  Segments, Docs, Excluded = [], [], []
  Seen_docs = set()
  Stats = {s: collections.Counter() for s in SOURCES}
  for F in Manifest["files"]:
    source = F["source"]
    if source not in SOURCES:
      raise ValueError(f"알 수 없는 출처 {source}")
    zpath = os.path.join(corpus_root, "snapshot1", F["path"])
    with open(zpath, "rb") as f:
      digest = hashlib.sha256(f.read()).hexdigest()
    if digest != F["sha256"]:
      raise ValueError(f"zip 해시 불일치 {F['path']}")
    with zipfile.ZipFile(zpath) as zf:
      Keys = db_property_keys(zf)
      for path in sorted(n for n in zf.namelist() if n.lower().endswith(".md")):
        doc_id = doc_id_for(path)
        if doc_id in Seen_docs:
          raise ValueError(f"doc_id 중복 {doc_id}")
        Seen_docs.add(doc_id)
        reason = doc_exclusion(source, path, doc_id, Excluded_ids)
        if reason:
          Excluded.append({"doc_id": doc_id, "source": source, "path": path, "reason": reason})
          continue
        raw = zf.read(path).decode("utf-8")
        title, Props, Segs = process_doc(raw, Keys.get(os.path.dirname(path)), Stats[source])
        if not Segs:
          Excluded.append({"doc_id": doc_id, "source": source, "path": path, "reason": "E4_빈문서"})
          continue
        layer, group = source_layer(source, path, Owners)
        Docs.append({
          "doc_id": doc_id, "source": source, "path": path, "zip_sha256": F["sha256"],
          "layer": layer, "group": group, "title": title, "properties": Props,
          "raw_sha256": sha256_text(raw), "n_segments": len(Segs),
        })
        for n, s in enumerate(Segs, 1):
          text = "\n".join(t for _, t in s)
          Segments.append({
            "segment_id": f"{doc_id}#s{n}", "doc_id": doc_id, "seq": n,
            "source": source, "layer": layer, "group": group,
            "line_start": s[0][0], "line_end": s[-1][0],
            "text": text, "text_sha256": sha256_text(text),
          })

  Titles = collections.Counter(d["title"] for d in Docs)
  Report = {
    "rules_version": RULES_VERSION,
    "docs_by_source_layer": collections.Counter(f"{d['source']}|{d['layer']}|{d['group']}" for d in Docs),
    "segments_by_source_layer": collections.Counter(f"{s['source']}|{s['layer']}|{s['group']}" for s in Segments),
    "excluded_by_source_reason": collections.Counter(f"{e['source']}|{e['reason']}" for e in Excluded),
    "decoration_by_source": {k: dict(v) for k, v in Stats.items()},
    "docs_with_properties_by_source": collections.Counter(d["source"] for d in Docs if d["properties"]),
    "duplicate_titles": {t: c for t, c in Titles.items() if c > 1},
    "e1_matched": sum(1 for e in Excluded if e["reason"] == "E1_탐색표본"),
  }
  os.makedirs(out_dir, exist_ok=True)
  for name, Rows in (("segments.jsonl", Segments), ("docs.jsonl", Docs), ("excluded.jsonl", Excluded)):
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
      for r in Rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
  with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
    json.dump(Report, f, ensure_ascii=False, indent=2)
    f.write("\n")
  return Report


def main():
  p = argparse.ArgumentParser()
  p.add_argument("--corpus", required=True)
  p.add_argument("--out", required=True)
  a = p.parse_args()
  print(json.dumps(run(os.path.expanduser(a.corpus), os.path.expanduser(a.out)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
