"""세그먼트 · 제외 규칙 v1.1 ( docs/segment_rules_v1.md ) 구현

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

from labeling.gold import read_membership

RULES_VERSION = "segment_rules_v1.1"

PAGE_ID_RE = re.compile(r" ([0-9a-f]{32})\.md$")
CSV_ALL_RE = re.compile(r" [0-9a-f]{32}_all\.csv$")
HEADING_RE = re.compile(r"^#{1,3} ")
FENCE_RE = re.compile(r"^\s*```")
IMG_ALT_RE = re.compile(r"^\s*!\[([^\]]*)\]")
# B7 글자 판정 ( 한글 · 영문 · 숫자 )
LETTER_RE = re.compile(r"[0-9A-Za-z\uac00-\ud7a3\u3131-\u318e]")

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

# 기존 형식 ( team_1jo_personal_owners ) 의 출처 표 - 출처 id : ( 층, 그룹, 개인 페이지 판정 대상 )
_LEGACY_TABLE = {
  "lecture_note": ("전사", None, False),
  "team_soft_eng": ("팀", "소공", False),
  "team_1jo": ("팀", "1조", True),
}


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


def split_segments(Body, Stats=None):
  """B1 ~ B7. 세그먼트별 (줄 번호, 원문) 목록의 목록"""
  if Stats is None:
    Stats = collections.Counter()
  Flags = heading_flags(Body)
  Raw = [[]]
  for (ln, text), is_head in zip(Body, Flags):
    if is_head:
      Raw.append([])
    Raw[-1].append((ln, text))
  Segs = [s for s in (trim(r) for r in Raw) if s]

  def heading_only(s):
    return len([1 for _, t in s if t.strip()]) == 1 and bool(HEADING_RE.match(s[0][1]))

  def letterless(s):
    return not any(LETTER_RE.search(t) for _, t in s)

  # B4 헤딩만 있는 세그먼트, B7 글자 없는 세그먼트는 다음 세그먼트 앞에, 마지막이면 직전 세그먼트 끝에
  Merged = []
  Carry = []
  for s in Segs:
    if heading_only(s) or letterless(s):
      Stats["heading_only_merged" if heading_only(s) else "letterless_merged"] += 1
      Carry += s
      continue
    Merged.append(Carry + s)
    Carry = []
  if Carry:
    if Merged:
      Merged[-1] = Merged[-1] + Carry
    elif not letterless(Carry):
      Merged.append(Carry)
    # 남은 것이 전부 글자 없는 줄이면 세그먼트 없음 ( E4 )
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


def source_table(Layer_cfg):
  # 사용자 결정 2026-10-22 : 합성 시연 코퍼스도 Notion 내보내기 모양으로 만들고 같은 세그먼트 규칙을 거친다 - 출처 표를 설정에서 읽는다
  if not isinstance(Layer_cfg, dict):
    raise ValueError("source_layers.json 이 객체가 아니다")
  HasLegacy = "team_1jo_personal_owners" in Layer_cfg
  HasNew = "personal_owner_teams" in Layer_cfg
  HasSources = "sources" in Layer_cfg
  # 두 형식의 키가 섞이면 어느 쪽 표를 써야 할지 알 수 없다
  if HasLegacy and HasNew:
    raise ValueError("source_layers.json 에 두 형식의 주인 키가 함께 있다")
  if HasLegacy:
    # 기존 형식에 sources 가 있으면 기존 표와 새 표 중 어느 쪽인지 알 수 없다
    if HasSources:
      raise ValueError("기존 형식 source_layers.json 에 sources 가 있다")
    # 기존 형식 표는 SOURCES 와 같은 출처만 갖는다
    if set(_LEGACY_TABLE) != SOURCES:
      raise ValueError("기존 출처 표와 SOURCES 가 다르다")
    return {s: _LEGACY_TABLE[s] for s in sorted(SOURCES)}
  if not HasNew:
    raise ValueError("source_layers.json 에 주인 키가 없다")
  # 새 형식에 sources 가 없으면 출처 표를 코드의 기본값으로 채우게 된다 - 기본값은 넣지 않는다
  if not HasSources:
    raise ValueError("새 형식 source_layers.json 에 sources 가 없다")
  Sources = Layer_cfg["sources"]
  if not isinstance(Sources, dict) or not Sources:
    raise ValueError("sources 는 비어 있지 않은 객체여야 한다")
  Table = {}
  for Name, Entry in Sources.items():
    if not isinstance(Name, str) or not Name:
      raise ValueError(f"출처 id 가 비어 있지 않은 문자열이 아니다: {Name!r}")
    if not isinstance(Entry, dict) or any(Key not in Entry for Key in ("layer", "group", "personal_pages")):
      raise ValueError(f"출처 {Name} 에 layer · group · personal_pages 가 모두 있어야 한다")
    Layer, Group, Personal = Entry["layer"], Entry["group"], Entry["personal_pages"]
    # 개인은 출처 층이 될 수 없다 - 개인 페이지는 팀 출처 안에서 가려낸다
    if Layer not in ("팀", "전사"):
      raise ValueError(f"출처 {Name} 의 layer 는 팀 또는 전사여야 한다: {Layer!r}")
    if Layer == "팀" and (not isinstance(Group, str) or not Group):
      raise ValueError(f"팀 출처 {Name} 의 group 은 비어 있지 않은 문자열이어야 한다")
    if Layer == "전사" and Group is not None:
      raise ValueError(f"전사 출처 {Name} 의 group 은 null 이어야 한다")
    if not isinstance(Personal, bool):
      raise ValueError(f"출처 {Name} 의 personal_pages 는 불리언이어야 한다")
    if Personal and Layer != "팀":
      raise ValueError(f"전사 출처 {Name} 은 personal_pages 가 true 일 수 없다")
    Table[Name] = (Layer, Group, Personal)
  return Table


def source_placement(source, path, Table, Membership_):
  # 사용자 결정 2026-10-22 : 개인 페이지는 그 페이지가 놓인 워크스페이스의 팀을 팀 맥락으로 가진다 - source_layer 는 기존 호출부 때문에 그대로 둔다
  if source not in Table:
    raise ValueError(f"알 수 없는 출처 {source}")
  Layer, Group, Personal = Table[source]
  if Personal:
    Parts = path.split("/")
    if len(Parts) >= 2:
      owner = PAGE_ID_RE.sub("", Parts[1])
      if owner.endswith(".md"):
        owner = owner[:-3]
      if owner in Membership_.teams_by_owner:
        # 기존 형식은 출력에 team 키를 만들지 않으려고 None 을 돌려준다
        if Membership_.legacy_team is not None:
          return "개인", owner, None
        # 사용자 결정 2026-10-22 : 주인이 속하지 않은 팀의 워크스페이스에 그 주인의 개인 페이지가 있으면 멈춘다
        if Group not in Membership_.teams_by_owner[owner]:
          raise ValueError(f"개인 페이지가 주인의 소속 팀이 아닌 워크스페이스에 있다: {path}")
        return "개인", owner, Group
  return Layer, Group, None


def process_doc(raw_text, Prop_keys, Stats):
  Lines = list(enumerate(raw_text.splitlines(), 1))
  Body, title, Props = split_title_and_properties(Lines, Prop_keys)
  Body = strip_decorations(Body, Stats)
  return title, Props, split_segments(Body, Stats)


def run(corpus_root, out_dir):
  Manifest = load_json(os.path.join(corpus_root, "snapshot1", "manifest.json"))
  Selection = load_json(os.path.join(corpus_root, "selection", "lecture_subjects.json"))
  Layer_cfg = load_json(os.path.join(corpus_root, "selection", "source_layers.json"))
  Excluded_ids = set(Selection["excluded_pages"]["ids"])
  # 사용자 결정 2026-10-22 : 주인 목록은 소속 팀 표에서 읽는다 - 기존 설정은 출력이 바이트 단위로 같다
  Table = source_table(Layer_cfg)
  Membership_ = read_membership(os.path.join(corpus_root, "selection", "source_layers.json"))

  Segments, Docs, Excluded = [], [], []
  Seen_docs = set()
  Stats = {s: collections.Counter() for s in Table}
  for F in Manifest["files"]:
    source = F["source"]
    if source not in Table:
      raise ValueError(f"알 수 없는 출처 {source}")
    zpath = os.path.join(corpus_root, "snapshot1", F["path"])
    with open(zpath, "rb") as f:
      digest = hashlib.sha256(f.read()).hexdigest()
    if digest != F["sha256"]:
      raise ValueError(f"zip 해시 불일치 {F['path']}")
    with zipfile.ZipFile(zpath) as zf:
      Keys = db_property_keys(zf)
      Pending = []
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
        Pending.append((doc_id, path, raw, title, Props, Segs))

      # E5 같은 폴더에 title 이 같은 Notion 페이지가 있는 첨부 md
      Page_titles = {(os.path.dirname(p), t) for d, p, _, t, _, _ in Pending if not d.startswith("att-") and t is not None}
      for doc_id, path, raw, title, Props, Segs in Pending:
        if doc_id.startswith("att-") and title is not None and (os.path.dirname(path), title) in Page_titles:
          Excluded.append({"doc_id": doc_id, "source": source, "path": path, "reason": "E5_첨부중복"})
          continue
        layer, group, team = source_placement(source, path, Table, Membership_)
        Doc_row = {
          "doc_id": doc_id, "source": source, "path": path, "zip_sha256": F["sha256"],
          "layer": layer, "group": group, "title": title, "properties": Props,
          "raw_sha256": sha256_text(raw), "n_segments": len(Segs),
        }
        # team 은 새 형식 개인 행에만 기존 키 다음 맨 끝에 더한다
        if team is not None:
          Doc_row["team"] = team
        Docs.append(Doc_row)
        for n, s in enumerate(Segs, 1):
          text = "\n".join(t for _, t in s)
          Seg_row = {
            "segment_id": f"{doc_id}#s{n}", "doc_id": doc_id, "seq": n,
            "source": source, "layer": layer, "group": group,
            "line_start": s[0][0], "line_end": s[-1][0],
            "text": text, "text_sha256": sha256_text(text),
          }
          if team is not None:
            Seg_row["team"] = team
          Segments.append(Seg_row)

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
