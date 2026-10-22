"""정답 층 합성 ( docs/labeling_criteria_v2.md 4 장 )

정답 층 = max ( 출처 층, 고유 층 ). Lecture Note 는 라벨 없이 정답 전사, auto = true
출력은 코퍼스 내용에서 나온 파일이므로 코퍼스 저장소에만 쓴다
"""
import argparse
import collections
import hashlib
import json
import os
from dataclasses import dataclass

# 기준 §4 : 층 순서는 개인 < 팀 < 전사. 검색 쪽 상수를 가져오지 않고 이 파일에 따로 둔다
LAYER_RANK = {"개인": 0, "팀": 1, "전사": 2}
LABEL_SOURCES = {"team_1jo", "team_soft_eng"}
SOURCES = LABEL_SOURCES | {"lecture_note"}
TEAM_GROUP = "1조"
LABEL_FIELDS = ["segment_id", "intrinsic_layer", "default_applied", "round", "criteria_sha256"]


def sha256_file(path):
  with open(path, "rb") as File:
    return hashlib.sha256(File.read()).hexdigest()


def read_jsonl(path):
  with open(path, encoding="utf-8") as File:
    return [json.loads(Line) for Line in File]


def read_ids(path):
  with open(path, encoding="utf-8") as File:
    return [Line.strip() for Line in File if Line.strip()]


def read_owners(path):
  with open(path, encoding="utf-8") as File:
    Obj = json.load(File)
  Owners = Obj.get("team_1jo_personal_owners") if isinstance(Obj, dict) else None
  # 주인 목록이 없으면 개인 → 팀 정답의 그룹을 정할 수 없다
  if not isinstance(Owners, list) or not Owners or not all(isinstance(O, str) for O in Owners):
    raise ValueError("source_layers.json 에 team_1jo_personal_owners ( 이름 목록 ) 가 없다")
  return set(Owners)


def group_for(seg, gold_layer, owners):
  # 기준 §4 : 정답 층 = 출처 층이면 출처 그룹
  if gold_layer == seg["layer"]:
    return seg["group"]
  # 기준 §4 : 개인 출처에서 정답이 팀이면 주인이 속한 팀 ( 1조 )
  if seg["layer"] == "개인" and gold_layer == "팀":
    # 주인이 목록에 없으면 어느 팀으로 올릴지 알 수 없다
    if seg["group"] not in owners:
      raise ValueError(f"개인 페이지 주인이 team_1jo_personal_owners 에 없다: {seg['segment_id']}")
    return TEAM_GROUP
  # 기준 §4 : 정답이 전사면 그룹 없음
  return None


@dataclass(frozen=True)
class Membership:
  # 사용자 결정 2026-10-22 : 시연 코퍼스는 팀 2개, 개인은 한 팀 또는 두 팀에 속할 수 있다
  # 사용자 결정 2026-10-22 : 층별 분리 검색과 보기에서 개인은 자기가 속한 모든 팀의 팀 노트를 본다
  teams_by_owner: dict[str, frozenset[str]]
  # 기존 형식 ( 전부 1조 ) 이면 TEAM_GROUP, 새 형식이면 None - 새 형식은 팀 맥락을 호출마다 받아야 한다
  legacy_team: str | None


def _check_name(Value, what):
  # 이름이 문자열이 아니거나 비면 키로 쓸 수 없고 조용히 다른 이름과 섞인다
  if not isinstance(Value, str) or not Value:
    raise ValueError(f"{what} 는 비어 있지 않은 문자열이어야 한다: {Value!r}")


def read_membership(path):
  with open(path, encoding="utf-8") as File:
    Obj = json.load(File)
  if not isinstance(Obj, dict):
    raise ValueError("source_layers.json 이 객체가 아니다")
  HasLegacy = "team_1jo_personal_owners" in Obj
  HasNew = "personal_owner_teams" in Obj
  # 두 형식이 함께 있거나 둘 다 없으면 어느 쪽이 맞는지 정할 수 없다
  if HasLegacy == HasNew:
    raise ValueError("source_layers.json 에 team_1jo_personal_owners 와 personal_owner_teams 중 정확히 하나가 있어야 한다")
  if HasLegacy:
    # 기존 형식은 read_owners 와 같은 검사를 그대로 거친다 - 결과가 지금과 같아야 한다
    return Membership({Owner: frozenset({TEAM_GROUP}) for Owner in read_owners(path)}, TEAM_GROUP)
  Raw = Obj["personal_owner_teams"]
  # 소속 표가 비면 개인 → 팀 정답의 그룹을 정할 수 없다
  if not isinstance(Raw, dict) or not Raw:
    raise ValueError("personal_owner_teams 는 비어 있지 않은 객체 ( 주인 : 팀 목록 ) 여야 한다")
  Teams = {}
  for Owner, TeamList in Raw.items():
    _check_name(Owner, "주인 이름")
    # 팀 목록이 비면 그 주인의 팀 노트 그룹이 없다
    if not isinstance(TeamList, list) or not TeamList:
      raise ValueError(f"소속 팀 목록이 비었거나 목록이 아니다: 주인 {Owner!r}")
    for Team in TeamList:
      _check_name(Team, "팀 이름")
    # 같은 팀을 두 번 적으면 오타를 가려낼 수 없다
    if len(set(TeamList)) != len(TeamList):
      raise ValueError(f"소속 팀 목록에 중복이 있다: 주인 {Owner!r}")
    Teams[Owner] = frozenset(TeamList)
  return Membership(Teams, None)


def personal_team(seg, membership):
  Owner = seg["group"]
  # 주인이 소속 표에 없으면 어느 팀으로 올릴지 알 수 없다
  if Owner not in membership.teams_by_owner:
    raise ValueError(f"개인 페이지 주인이 소속 표에 없다: {seg['segment_id']}")
  # 사용자 결정 2026-10-22 : 개인 문서가 팀 층에 놓이면 그 문서가 놓인 팀 워크스페이스의 팀이 그룹이다
  if "team" in seg:
    # 주인이 속하지 않은 팀의 워크스페이스에는 놓을 수 없다
    if seg["team"] not in membership.teams_by_owner[Owner]:
      raise ValueError(f"문서가 놓인 팀이 주인의 소속 팀이 아니다: {seg['segment_id']}")
    return seg["team"]
  if membership.legacy_team is not None:
    return membership.legacy_team
  # 새 형식에서 팀 맥락 없이 고르면 두 팀 소속 주인의 노트가 임의의 팀에 들어간다
  raise ValueError(f"새 형식에서는 개인 문서에 team 이 있어야 한다: {seg['segment_id']}")


def note_group(seg, gold_layer, membership):
  # group_for 와 같은 규칙이고 개인 → 팀만 소속 표로 정한다 - group_for 는 기존 호출부 때문에 그대로 둔다
  if gold_layer == seg["layer"]:
    return seg["group"]
  if seg["layer"] == "개인" and gold_layer == "팀":
    return personal_team(seg, membership)
  return None


def visible_pairs_for(caller_layer, caller_group, membership):
  # 사용자 결정 2026-10-22 : 층별 분리 검색과 보기에서 개인은 자기가 속한 모든 팀의 팀 노트를 본다
  if caller_layer not in LAYER_RANK:
    raise ValueError(f"알 수 없는 caller_layer: {caller_layer!r}")
  if caller_layer == "개인":
    # 주인이 표에 없으면 보이는 팀을 정할 수 없다
    if caller_group not in membership.teams_by_owner:
      raise ValueError("개인 호출자의 주인이 소속 표에 없다")
    return {("개인", caller_group)} | {("팀", Team) for Team in membership.teams_by_owner[caller_group]} | {("전사", None)}
  if caller_layer == "팀":
    # 팀 그룹이 비면 아무 팀 노트도 맞지 않는 빈 보기가 조용히 만들어진다
    if not isinstance(caller_group, str) or not caller_group:
      raise ValueError("팀 호출자는 caller_group 이 필요하다")
    return {("팀", caller_group), ("전사", None)}
  # 전사 노트의 그룹은 None 이라 다른 값은 어떤 노트와도 맞지 않는다
  if caller_group is not None:
    raise ValueError("전사 호출자는 caller_group 을 받지 않는다")
  return {("전사", None)}


def build(segments_path, split_dir, split_name, labels_path, source_layers_path):
  Segs = read_jsonl(segments_path)
  SegIds = [S["segment_id"] for S in Segs]
  # segment_id 가 겹치면 정답 행이 두 번 생긴다
  if len(set(SegIds)) != len(SegIds):
    raise ValueError("segments.jsonl 에 segment_id 중복이 있다")
  Owners = read_owners(source_layers_path)

  for S in Segs:
    # 알 수 없는 source 는 라벨 대상인지 판정할 수 없다
    if S["source"] not in SOURCES:
      raise ValueError(f"알 수 없는 source: {S['source']!r} ( {S['segment_id']} )")
    # 기준 §4 : 층 순서에 없는 값은 max 를 계산할 수 없다
    if S["layer"] not in LAYER_RANK:
      raise ValueError(f"알 수 없는 layer: {S['layer']!r} ( {S['segment_id']} )")
  # 정답 그룹 "1조" 는 코드에 박힌 값이므로 데이터의 팀 그룹명이 전부 같은지 확인한다
  TeamGroups = {S["group"] for S in Segs if S["source"] == "team_1jo" and S["layer"] == "팀"}
  if TeamGroups - {TEAM_GROUP}:
    raise ValueError(f"team_1jo 팀 세그먼트의 group 이 전부 {TEAM_GROUP!r} 가 아니다: {sorted(TeamGroups, key=str)}")

  DocIds = set(read_ids(os.path.join(split_dir, f"{split_name}_doc_ids.txt")))
  # 분리 문서가 조용히 빠지면 정답 행 수가 줄어든다
  NoSegs = sorted(DocIds - {S["doc_id"] for S in Segs})
  if NoSegs:
    raise ValueError(f"분리 파일의 doc_id 중 세그먼트가 없는 것이 있다: {NoSegs[:3]}")
  Target = [S for S in Segs if S["doc_id"] in DocIds]
  TargetIds = {S["segment_id"] for S in Target}

  LabelRows = read_jsonl(labels_path)
  # 빈 라벨 파일로는 팀 출처 정답을 만들 수 없고 회차 · 기준판도 확인할 수 없다
  if not LabelRows:
    raise ValueError("라벨 파일이 비어 있다")
  Labels = collections.defaultdict(list)
  for L in LabelRows:
    # 필드가 빠진 라벨은 고유 층 · D0 여부를 읽을 수 없다
    if any(F not in L for F in LABEL_FIELDS):
      raise ValueError(f"라벨에 필드가 빠졌다: {LABEL_FIELDS!r}")
    # 분리 밖 세그먼트의 라벨이 섞이면 다른 분리의 정답이 오염된다
    if L["segment_id"] not in TargetIds:
      raise ValueError(f"라벨의 segment_id 가 대상 밖이다: {L['segment_id']!r}")
    # 기준 §4 : 고유 층이 층 순서 밖이면 max 를 계산할 수 없다
    if L["intrinsic_layer"] not in LAYER_RANK:
      raise ValueError(f"라벨의 intrinsic_layer 가 층이 아니다: {L['intrinsic_layer']!r}")
    # default_applied 가 불리언이 아니면 D0 건수가 틀어진다
    if not isinstance(L["default_applied"], bool):
      raise ValueError(f"라벨의 default_applied 가 불리언이 아니다: {L['segment_id']}")
    Labels[L["segment_id"]].append(L)
  # 다른 회차 · 다른 기준판 라벨이 섞이면 정답이 오염된다
  Rounds = [L["round"] for L in LabelRows]
  if any(R != Rounds[0] for R in Rounds):
    raise ValueError("라벨 파일에 round 값이 여럿이다")
  CriteriaShas = [L["criteria_sha256"] for L in LabelRows]
  if any(C != CriteriaShas[0] for C in CriteriaShas):
    raise ValueError("라벨 파일에 criteria_sha256 값이 여럿이다")

  Golds, Applied = [], []
  for S in Target:
    Mine = Labels.get(S["segment_id"], [])
    if S["source"] == "lecture_note":
      # 기준 §1 : Lecture Note 는 라벨링하지 않는다
      if Mine:
        raise ValueError(f"Lecture Note 세그먼트에 라벨이 있다: {S['segment_id']}")
      # 기준 §4 : Lecture Note 는 출처 층이 전사여야 정답 전사가 맞다
      if S["layer"] != "전사":
        raise ValueError(f"Lecture Note 세그먼트의 layer 가 전사가 아니다: {S['segment_id']}")
      Golds.append(
        {
          "segment_id": S["segment_id"], "intrinsic_layer": None, "source_layer": S["layer"], "source_group": S["group"],
          "gold_layer": S["layer"], "gold_group": None, "clamped": False, "auto": True,
        }
      )
      Applied.append(None)
    else:
      # 기준 §1 : 팀 출처 세그먼트는 라벨이 정확히 1개여야 한다
      if len(Mine) != 1:
        raise ValueError(f"라벨이 정확히 1개가 아니다: {S['segment_id']} ( {len(Mine)} 개 )")
      Intrinsic = Mine[0]["intrinsic_layer"]
      # 기준 §4 : 정답 층 = max ( 출처 층, 고유 층 )
      Gold = max(S["layer"], Intrinsic, key=LAYER_RANK.__getitem__)
      Golds.append(
        {
          "segment_id": S["segment_id"], "intrinsic_layer": Intrinsic, "source_layer": S["layer"], "source_group": S["group"],
          "gold_layer": Gold, "gold_group": group_for(S, Gold, Owners),
          # 기준 §4 : 고유 층이 출처 층보다 낮아 올라간 세그먼트만 clamped
          "clamped": LAYER_RANK[Intrinsic] < LAYER_RANK[S["layer"]], "auto": False,
        }
      )
      Applied.append(Mine[0]["default_applied"])
  return Target, Golds, Applied, Rounds[0], CriteriaShas[0]


def make_report(golds, applied, split_name, segments_sha, labels_sha, label_round, label_criteria_sha):
  Pairs = collections.Counter(f"{G['source_layer']}>{G['gold_layer']}" for G in golds)
  Up = [LAYER_RANK[G["gold_layer"]] > LAYER_RANK[G["source_layer"]] for G in golds]
  return {
    "segments_sha256": segments_sha,
    "labels_sha256": labels_sha,
    # 위에서 확인한 라벨 파일의 단일 회차 · 기준판 값
    "label_round": label_round,
    "label_criteria_sha256": label_criteria_sha,
    "split": split_name,
    "segments": len(golds),
    "source_layer_x_gold_layer": dict(sorted(Pairs.items())),
    "clamped": sum(1 for G in golds if G["clamped"]),
    "gold_gt_source": sum(Up),
    "auto": sum(1 for G in golds if G["auto"]),
    # 기준 §3 : D0 건수와 그중 정답 > 출처 건수를 따로 보고한다
    "d0": sum(1 for A in applied if A is True),
    "d0_gold_gt_source": sum(1 for A, U in zip(applied, Up) if A is True and U),
  }


def run(segments_path, split_dir, split_name, labels_path, source_layers_path, out_path, report_path):
  # 정답 파일은 한 번만 만든다 ( 덮어쓰기 금지 )
  for Path in (out_path, report_path):
    if os.path.exists(Path):
      raise ValueError(f"출력 파일이 이미 있다: {Path!r}")
  # 두 출력이 같은 경로면 뒤의 파일이 앞의 파일을 덮는다
  if os.path.abspath(out_path) == os.path.abspath(report_path):
    raise ValueError("--out 과 --report-out 이 같은 경로다")
  Target, Golds, Applied, LabelRound, LabelCriteriaSha = build(segments_path, split_dir, split_name, labels_path, source_layers_path)
  Report = make_report(Golds, Applied, split_name, sha256_file(segments_path), sha256_file(labels_path), LabelRound, LabelCriteriaSha)
  with open(out_path, "x", encoding="utf-8") as File:
    for G in Golds:
      File.write(json.dumps(G, ensure_ascii=False) + "\n")
  with open(report_path, "x", encoding="utf-8") as File:
    json.dump(Report, File, ensure_ascii=False, indent=2)
    File.write("\n")
  return Report


def main():
  Parser = argparse.ArgumentParser()
  Parser.add_argument("--segments", required=True)
  Parser.add_argument("--split-dir", required=True)
  Parser.add_argument("--split", required=True)
  Parser.add_argument("--labels", required=True, help="convert_labels 의 labels jsonl")
  Parser.add_argument("--source-layers", required=True, help="selection/source_layers.json")
  Parser.add_argument("--out", required=True, help="정답 jsonl 출력 경로")
  Parser.add_argument("--report-out", required=True, help="보고 json 출력 경로")
  Args = Parser.parse_args()
  ex = os.path.expanduser
  Report = run(ex(Args.segments), ex(Args.split_dir), Args.split, ex(Args.labels), ex(Args.source_layers), ex(Args.out), ex(Args.report_out))
  print(json.dumps(Report, ensure_ascii=False))


if __name__ == "__main__":
  main()
