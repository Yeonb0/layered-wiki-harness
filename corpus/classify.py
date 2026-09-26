# 정답 링크를 autolink 재현 여부로 분류한다
import os, re, sys, json, collections
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
import obsidian_autolink as al

Vault = Path("vault")
Corpus = [l for l in open("pilot.txt").read().split("\n") + open("main.txt").read().split("\n") if l]
Sets = {"pilot": set(l for l in open("pilot.txt").read().split("\n") if l), "main": set(l for l in open("main.txt").read().split("\n") if l)}
WIKI = re.compile(r"(!?)\[\[([^\]]+)\]\]")

# 인덱스는 코퍼스 765개 노트로만 만든다 (MOC 제외)
Notes = []
for rel in Corpus:
  text = (Vault / rel).read_text(encoding="utf-8")
  front, _ = al.split_frontmatter(text)
  Notes.append(al.Note(Vault / rel, rel, Path(rel).stem, al.parse_aliases(front), True, True))
Resolved, Ambiguous = al.build_index(Notes, 2, al.DEFAULT_STOPWORDS)
Names = collections.defaultdict(set)
for n in Notes:
  for t in [n.title] + n.aliases:
    Names[t.strip().lower()].add(n.rel)

def strip_links(text):
  # 임베드는 두고 위키링크는 표시 문자열로 되돌린다
  def repl(m):
    if m.group(1):
      return m.group(0)
    inner = m.group(2).replace("\\|", "|")
    tgt, _, shown = inner.partition("|")
    return shown or tgt.split("#")[0]
  return WIKI.sub(repl, text)

def gold_targets(text, self_rel):
  Out = []
  for m in WIKI.finditer(text):
    if m.group(1):
      continue
    tgt = m.group(2).replace("\\|", "|").split("|")[0].split("#")[0].strip()
    hit = Names.get(os.path.basename(tgt).lower(), set())
    if len(hit) == 1:
      r = next(iter(hit))
      if r != self_rel:
        Out.append(r)
  return Out

Rows = []
for n in Notes:
  text = n.path.read_text(encoding="utf-8")
  Gold = set(gold_targets(text, n.rel))
  plain = strip_links(text)
  Pred = {rel for _, _, _, _, rel in al.find_matches(plain, al.build_mask(plain), Resolved, n, 1, False)}
  for g in sorted(Gold):
    Rows.append({"src": n.rel, "dst": g, "set": "pilot" if n.rel in Sets["pilot"] else "main",
                 "dst_in_same_set": g in Sets["pilot" if n.rel in Sets["pilot"] else "main"],
                 "rule_reproducible": g in Pred})
  for p in sorted(Pred - Gold):
    Rows.append({"src": n.rel, "dst": p, "set": "pilot" if n.rel in Sets["pilot"] else "main",
                 "dst_in_same_set": p in Sets["pilot" if n.rel in Sets["pilot"] else "main"],
                 "rule_only_not_gold": True})
with open("gold_links_classified.jsonl", "w", encoding="utf-8") as f:
  for r in Rows:
    f.write(json.dumps(r, ensure_ascii=False) + "\n")
for s in ("pilot", "main"):
  G = [r for r in Rows if r["set"] == s and "rule_reproducible" in r and r["dst_in_same_set"]]
  rep = sum(r["rule_reproducible"] for r in G)
  extra = sum(1 for r in Rows if r["set"] == s and r.get("rule_only_not_gold") and r["dst_in_same_set"])
  print(s, "gold", len(G), "rule_reproducible", rep, "non_reproducible", len(G) - rep, "rule_extra_not_gold", extra)
print("ambiguous terms", len(Ambiguous))
