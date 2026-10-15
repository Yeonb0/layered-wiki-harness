"""라벨 TSV → labels jsonl 변환 ( docs/labeling_criteria_v2.md 6 장 )

라벨러가 입력한 TSV 와 _key 대응표를 합쳐 segment_id 단위 라벨 레코드를 만든다
출력은 코퍼스 본문 ( rationale ) 을 담으므로 코퍼스 저장소에만 쓴다
labeler · round · labeled_at 은 정하지 않고 모두 인자로 받는다
"""
import argparse
import datetime
import hashlib
import json
import os

TSV_HEADER = ["doc", "n", "layer", "clause", "also_hit", "confidence", "rationale"]
KEY_FIELDS = ["doc", "n", "doc_id", "segment_id", "view_sha256"]
LAYERS = {"개인", "팀", "전사"}
# 기준 §3 : P 는 개인, T 는 팀, O1 · D0 는 전사. BB 는 층 제한이 없어 여기에 넣지 않는다
CLAUSE_LAYER = {
  "P1": "개인", "P2": "개인", "P3": "개인",
  "T1": "팀", "T2": "팀", "T3": "팀", "T4": "팀",
  "O1": "전사", "D0": "전사",
}
BB_CLAUSES = {"BB1", "BB2", "BB3", "BB4", "BB5", "BB6"}
CLAUSES = set(CLAUSE_LAYER) | BB_CLAUSES
CONFIDENCES = {"1", "2", "3"}
SCRIPT = "labeling/convert_labels.py"


def sha256_file(path):
  with open(path, "rb") as File:
    return hashlib.sha256(File.read()).hexdigest()


def parse_time(name, value):
  Text = value[:-1] + "+00:00" if value.endswith("Z") else value
  try:
    Moment = datetime.datetime.fromisoformat(Text)
  except ValueError:
    raise ValueError(f"{name} 이 ISO 8601 이 아니다: {value!r}") from None
  # 오프셋이 없으면 다른 기록의 시각과 순서를 맞출 수 없다
  if Moment.tzinfo is None or Moment.utcoffset() is None:
    raise ValueError(f"{name} 에 시간대 오프셋이 없다: {value!r}")
  return value


def parse_row_times(items):
  Times = {}
  for Item in items:
    Name, Sep, Value = Item.partition("=")
    # 형식이 어긋난 인자를 조용히 무시하면 시각이 공통값으로 남는다
    if not Sep or not Name:
      raise ValueError(f"--labeled-at-row 형식은 D01-1=ISO 8601 이다: {Item!r}")
    # 같은 행을 두 번 지정하면 어느 값이 맞는지 알 수 없다
    if Name in Times:
      raise ValueError(f"--labeled-at-row 에 같은 행이 두 번 있다: {Name!r}")
    Times[Name] = parse_time(f"--labeled-at-row {Name}", Value)
  return Times


def read_tsv(path):
  with open(path, "rb") as File:
    Raw = File.read()
  # BOM 이 있으면 첫 헤더 이름이 어긋난다
  if Raw.startswith(b"\xef\xbb\xbf"):
    raise ValueError("TSV 에 BOM 이 있다")
  # CR 이 섞이면 마지막 열 값이 달라진다 ( LF 만 허용 )
  if b"\r" in Raw:
    raise ValueError("TSV 에 CR 이 있다")
  Text = Raw.decode("utf-8")
  # 마지막 줄이 잘린 파일을 거른다
  if not Text.endswith("\n"):
    raise ValueError("TSV 가 LF 로 끝나지 않는다")
  Rows = [Line.split("\t") for Line in Text[:-1].split("\n")]
  # 입력 도구 계약 : 헤더가 다르면 열 의미를 믿을 수 없다
  if Rows[0] != TSV_HEADER:
    raise ValueError(f"TSV 헤더가 다르다: {Rows[0]!r}")
  for No, Row in enumerate(Rows, 1):
    # 열 수가 다르면 값이 다른 열로 밀린다
    if len(Row) != len(TSV_HEADER):
      raise ValueError(f"TSV {No} 번째 줄이 {len(TSV_HEADER)} 칸이 아니다: {len(Row)}")
  return Rows[1:]


def read_key(path):
  Key = []
  with open(path, encoding="utf-8") as File:
    for No, Line in enumerate(File, 1):
      Record = json.loads(Line)
      # 필드가 빠지면 view_sha256 · segment_id 를 잇지 못한다
      if not isinstance(Record, dict) or any(f not in Record for f in KEY_FIELDS):
        raise ValueError(f"key {No} 번째 줄에 필드가 빠졌다: {KEY_FIELDS!r}")
      # n 이 문자열이면 TSV 의 n 과 비교가 어긋난다
      if not isinstance(Record["n"], int) or isinstance(Record["n"], bool):
        raise ValueError(f"key {No} 번째 줄의 n 이 정수가 아니다: {Record['n']!r}")
      Key.append(Record)
  return Key


def check_row(no, row):
  Doc, N, Layer, Clause, AlsoHit, Confidence, Rationale = row
  Where = f"TSV {no} 번째 줄 ( {Doc}-{N} )"
  # n 은 key 의 정수 n 과 맞춰야 하므로 앞자리 0 없는 정수만 받는다
  if not N.isdigit() or str(int(N)) != N:
    raise ValueError(f"{Where} n 이 정수가 아니다: {N!r}")
  # 기준 §2 : 층은 개인 · 팀 · 전사 셋뿐
  if Layer not in LAYERS:
    raise ValueError(f"{Where} layer 값이 아니다: {Layer!r}")
  # 기준 §6 : 조항 id 는 P1 ~ P3, T1 ~ T4, O1, D0, BB1 ~ BB6
  if Clause not in CLAUSES:
    raise ValueError(f"{Where} clause 값이 아니다: {Clause!r}")
  Also = AlsoHit.split(",") if AlsoHit != "" else []
  for Hit in Also:
    # 기준 §6 : also_hit 도 같은 조항 집합 안의 값
    if Hit not in CLAUSES:
      raise ValueError(f"{Where} also_hit 값이 조항이 아니다: {Hit!r}")
    # 기준 §3 : 부수 조항은 핵심 조항과 다른 조항이다
    if Hit == Clause:
      raise ValueError(f"{Where} also_hit 에 clause 와 같은 값이 있다: {Hit!r}")
  # 같은 조항을 두 번 적으면 부수 조항 개수가 부풀려진다
  if len(set(Also)) != len(Also):
    raise ValueError(f"{Where} also_hit 에 중복이 있다: {AlsoHit!r}")
  # 기준 §3 : 확신도는 1 ~ 3
  if Confidence not in CONFIDENCES:
    raise ValueError(f"{Where} confidence 값이 아니다: {Confidence!r}")
  # 기준 §6 : rationale 은 한 줄, 비어 있으면 판정 근거를 검토할 수 없다
  if not Rationale.strip():
    raise ValueError(f"{Where} rationale 이 비어 있다")
  # 기준 §3 : 판정 순서가 조항에서 층을 정한다 ( BB 는 제한 없음 )
  if Clause in CLAUSE_LAYER and CLAUSE_LAYER[Clause] != Layer:
    raise ValueError(f"{Where} 조항 {Clause} 과 층 {Layer} 가 맞지 않는다")
  # 기준 §3 : D0 는 항상 확신도 1
  if Clause == "D0" and Confidence != "1":
    raise ValueError(f"{Where} D0 의 confidence 는 1 이어야 한다: {Confidence!r}")
  return Also


def convert(tsv_path, key_path, criteria_path, criteria_sha256, labeler, round_no, labeled_at, labeled_at_rows, out_path, meta_out_path):
  # 라벨 원본은 한 번만 만든다 ( 덮어쓰기 금지 )
  for Path in (out_path, meta_out_path):
    if os.path.exists(Path):
      raise ValueError(f"출력 파일이 이미 있다: {Path!r}")
  # 두 출력이 같은 경로면 뒤의 파일이 앞의 파일을 덮는다
  if os.path.abspath(out_path) == os.path.abspath(meta_out_path):
    raise ValueError("--out 과 --meta-out 이 같은 경로다")
  # 기준 §0 : 봉인본 해시와 다른 기준으로 변환하지 않는다
  CriteriaSha = sha256_file(criteria_path)
  if CriteriaSha != criteria_sha256:
    raise ValueError(f"기준 파일 sha256 이 다르다: {CriteriaSha}")
  # 기준 §6 : labeler 가 비면 누가 라벨했는지 남지 않는다
  if not labeler.strip():
    raise ValueError("--labeler 가 비어 있다")
  # 기준 §5 : 회차는 1 부터
  if round_no < 1:
    raise ValueError(f"--round 는 1 이상이다: {round_no}")
  CommonTime = parse_time("--labeled-at", labeled_at)
  RowTimes = parse_row_times(labeled_at_rows)

  Rows = read_tsv(tsv_path)
  Key = read_key(key_path)
  Alsos = [check_row(No, Row) for No, Row in enumerate(Rows, 2)]

  TsvIndex = {}
  for Row, Also in zip(Rows, Alsos):
    Id = (Row[0], int(Row[1]))
    # 같은 ( doc, n ) 이 두 번이면 어느 라벨이 맞는지 알 수 없다
    if Id in TsvIndex:
      raise ValueError(f"TSV 에 ( doc, n ) 중복이 있다: {Row[0]}-{Row[1]}")
    TsvIndex[Id] = (Row, Also)
  KeyIds = [(K["doc"], K["n"]) for K in Key]
  # key 가 같은 ( doc, n ) 을 두 번 가지면 대응이 하나로 정해지지 않는다
  if len(set(KeyIds)) != len(KeyIds):
    raise ValueError("key 에 ( doc, n ) 중복이 있다")
  # TSV 와 key 는 정확히 1 : 1 이어야 한다 ( 빠짐 · 남는 행 모두 금지 )
  Missing = sorted(set(KeyIds) - set(TsvIndex))
  if Missing:
    raise ValueError(f"key 에 있고 TSV 에 없는 행이 있다: {Missing[:3]}")
  Extra = sorted(set(TsvIndex) - set(KeyIds))
  if Extra:
    raise ValueError(f"TSV 에 있고 key 에 없는 행이 있다: {Extra[:3]}")
  Names = {f"{D}-{N}" for D, N in TsvIndex}
  for Name in RowTimes:
    # 없는 행의 시각을 받으면 오타가 조용히 사라진다
    if Name not in Names:
      raise ValueError(f"--labeled-at-row 의 행이 TSV 에 없다: {Name!r}")

  Records = []
  for K in Key:
    Row, Also = TsvIndex[(K["doc"], K["n"])]
    Name = f"{K['doc']}-{K['n']}"
    Records.append(
      {
        "segment_id": K["segment_id"],
        "view_sha256": K["view_sha256"],
        "intrinsic_layer": Row[2],
        "applied_clause": Row[3],
        "also_hit": Also,
        "default_applied": Row[3] == "D0",
        "rationale": Row[6],
        "confidence": int(Row[5]),
        "boundary_note": None,
        "labeler": labeler,
        "round": round_no,
        "labeled_at": RowTimes.get(Name, CommonTime),
        "criteria_sha256": CriteriaSha,
      }
    )
  Meta = {
    "tsv_sha256": sha256_file(tsv_path),
    "key_sha256": sha256_file(key_path),
    "criteria_sha256": CriteriaSha,
    "rows": len(Records),
    "labeler": labeler,
    "round": round_no,
    "script": SCRIPT,
  }
  with open(out_path, "x", encoding="utf-8") as File:
    for Record in Records:
      File.write(json.dumps(Record, ensure_ascii=False) + "\n")
  with open(meta_out_path, "x", encoding="utf-8") as File:
    json.dump(Meta, File, ensure_ascii=False, indent=2)
    File.write("\n")
  return Meta


def main():
  Parser = argparse.ArgumentParser()
  Parser.add_argument("--tsv", required=True)
  Parser.add_argument("--key", required=True)
  Parser.add_argument("--criteria", required=True, help="라벨링 기준 파일 경로")
  Parser.add_argument("--criteria-sha256", required=True, help="기준 파일의 기대 해시")
  Parser.add_argument("--labeler", required=True)
  Parser.add_argument("--round", required=True, type=int)
  Parser.add_argument("--labeled-at", required=True, help="전 행 공통 시각, ISO 8601, 시간대 오프셋 필수")
  Parser.add_argument("--labeled-at-row", action="append", default=[], help="D01-1=ISO 8601, 해당 행만 덮어쓴다")
  Parser.add_argument("--out", required=True, help="labels jsonl 출력 경로")
  Parser.add_argument("--meta-out", required=True, help="메타 json 출력 경로")
  Args = Parser.parse_args()
  ex = os.path.expanduser
  Meta = convert(
    ex(Args.tsv), ex(Args.key), ex(Args.criteria), Args.criteria_sha256, Args.labeler, Args.round,
    Args.labeled_at, Args.labeled_at_row, ex(Args.out), ex(Args.meta_out),
  )
  print(json.dumps(Meta, ensure_ascii=False))


if __name__ == "__main__":
  main()
