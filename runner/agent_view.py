def build_agent_view(title: str, body: str) -> str:
  # 라벨링 기준 v1 §1 - 라벨러 입력 ⊆ 에이전트 입력. 라벨링 도구도 이 함수로 뷰를 만든다
  return title + "\n\n" + body
