from client.types import WorkflowResult

# Dify 워크플로가 아직 없다 - DifyClient 와 동일 인터페이스의 고정 응답으로 러너 개발/테스트를 진행한다
FIXED_VERDICT = {
  "layer": "개인",
  "upward_links": [],
  "downward_conditional_links": [],
  "rationale": "fake_client 고정 응답",
}


class FakeDifyClient:
  @classmethod
  def from_env(cls) -> "FakeDifyClient":
    return cls()

  def run_workflow(
    self,
    doc: str,
    candidates_json: str,
    vault_size: int,
    mode: str,
    run_config_json: str,
  ) -> tuple[WorkflowResult, bool]:
    return (
      WorkflowResult(ok=True, errors=[], verdict=dict(FIXED_VERDICT), log="fake_client_log"),
      False,
    )
