import argparse
import hashlib
import re

MARK = "⟨이식⟩"

# 제목 줄 - # 뒤에 공백이 오거나 줄이 끝나야 한다 ( #태그 같은 줄을 제목으로 보지 않는다 )
_HEADING = re.compile(r"^(#+)(?=\s|$)")


def _heading_levels(Lines: list[str]) -> list[int | None]:
  # 코드 블록 ( ``` 로 둘러싼 구간 ) 안의 # 는 제목이 아니다
  Levels = []
  InCode = False
  for Line in Lines:
    if Line.lstrip().startswith("```"):
      InCode = not InCode
      Levels.append(None)
    elif InCode:
      Levels.append(None)
    else:
      Match = _HEADING.match(Line)
      Levels.append(len(Match.group(1)) if Match else None)
  return Levels


def _extract_intervals(text: str) -> tuple[list[list[str]], list[int]]:
  Lines = text.split("\n")
  Levels = _heading_levels(Lines)
  Intervals = []
  # 건너뛴 표시 줄의 번호 ( 1부터 ) - 조용히 버리지 않고 호출자에게 돌려준다
  Skipped = []
  # 직전에 조항 앞에 넣은 제목 줄의 번호 - 같은 제목 아래 조항이 이어지면 다시 넣지 않는다
  LastHeading = None
  Index = 0
  while Index < len(Lines):
    Line = Lines[Index]
    if MARK in Line and Levels[Index] is not None:
      # 표시된 제목은 같거나 더 높은 단계 ( # 개수가 같거나 적은 ) 의 다음 제목 직전까지 포함한다
      End = Index + 1
      while End < len(Lines) and not (Levels[End] is not None and Levels[End] <= Levels[Index]):
        End += 1
      Intervals.append(Lines[Index:End])
      # 구간 안의 표시 줄이 두 번 들어가지 않게 구간 끝으로 건너뛴다
      Index = End
    elif MARK in Line and Line.lstrip().startswith("- "):
      # 기준 문서의 조항은 모두 목록 항목이다 - 구간 밖 표시 줄은 목록 항목일 때만 그 줄 하나를 포함한다
      # 정의 · 반례가 어느 층 것인지 블록만으로 알 수 있게 가장 가까운 앞 제목 줄을 원문 그대로 앞에 붙인다
      Heading = next((Back for Back in range(Index - 1, -1, -1) if Levels[Back] is not None), None)
      if Heading is not None and Heading != LastHeading:
        Intervals.append([Lines[Heading], Line])
        LastHeading = Heading
      else:
        Intervals.append([Line])
      Index += 1
    elif MARK in Line:
      # §0 의 ⟨이식⟩ 설명 문단은 조항이 아니다 - 블록 생성 방법 설명이 프롬프트에 섞이지 않게 뺀다
      Skipped.append(Index + 1)
      Index += 1
    else:
      Index += 1
  return Intervals, Skipped


def extract_layer_block_with_skipped(text: str) -> tuple[str, list[int]]:
  Intervals, Skipped = _extract_intervals(text)
  # 포함할 것이 없으면 빈 블록이 조용히 해시된다
  if not Intervals:
    raise ValueError(f"{MARK} 조항이 하나도 없다 ( 건너뛴 표시 줄 번호: {Skipped} )")
  Lines = [Line for Interval in Intervals for Line in Interval]
  # 블록 끝의 빈 줄만 제거한다 - 중간 빈 줄은 원문 그대로 둔다
  while Lines and Lines[-1].strip() == "":
    Lines.pop()
  return "\n".join(Lines), Skipped


def extract_layer_block(text: str) -> str:
  Block, _ = extract_layer_block_with_skipped(text)
  return Block


def _read_verified(criteria_path: str, criteria_sha256: str) -> str:
  with open(criteria_path, "rb") as File:
    Raw = File.read()
  Actual = hashlib.sha256(Raw).hexdigest()
  # 기준 §0 : 해시가 다른 기준으로 블록을 만들지 않는다
  if Actual != criteria_sha256:
    raise ValueError(f"기준 파일 sha256 불일치: 기대 {criteria_sha256}, 실제 {Actual}")
  return Raw.decode("utf-8")


def load_layer_block(criteria_path: str, criteria_sha256: str) -> tuple[str, str]:
  Block = extract_layer_block(_read_verified(criteria_path, criteria_sha256))
  return Block, hashlib.sha256(Block.encode("utf-8")).hexdigest()


def main() -> None:
  Parser = argparse.ArgumentParser()
  Parser.add_argument("--criteria", required=True)
  Parser.add_argument("--criteria-sha256", required=True)
  Args = Parser.parse_args()
  Block, BlockSha = load_layer_block(Args.criteria, Args.criteria_sha256)
  Intervals, Skipped = _extract_intervals(_read_verified(Args.criteria, Args.criteria_sha256))
  print(f"layer_block_sha256 : {BlockSha}")
  print(f"lines : {len(Block.split(chr(10)))}")
  print(f"intervals : {len(Intervals)}")
  print(f"skipped_mark_lines : {Skipped}")
  print("--- block ---")
  print(Block)


if __name__ == "__main__":
  main()
