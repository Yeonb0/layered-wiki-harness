import os

import requests

from client.types import WorkflowResult

DIFY_USER_ID = "layered-wiki-harness"


class DifyClient:
  def __init__(self, endpoint: str, api_key: str, timeout: float, max_retries: int) -> None:
    self.endpoint = endpoint.rstrip("/")
    self.api_key = api_key
    self.timeout = timeout
    self.max_retries = max_retries

  @classmethod
  def from_env(cls) -> "DifyClient":
    return cls(
      endpoint=os.environ["DIFY_ENDPOINT"],
      api_key=os.environ["DIFY_API_KEY"],
      timeout=float(os.environ.get("DIFY_TIMEOUT_SECONDS", "60")),
      max_retries=int(os.environ.get("DIFY_MAX_RETRIES", "2")),
    )

  def run_workflow(
    self,
    doc: str,
    candidates_json: str,
    vault_size: int,
    mode: str,
    run_config_json: str,
  ) -> tuple[WorkflowResult, bool]:
    Inputs = {
      "Doc": doc,
      "Candidates": candidates_json,
      "VaultSize": vault_size,
      "Mode": mode,
      "RunConfig": run_config_json,
    }
    Retried = False
    LastError: Exception | None = None
    for Attempt in range(self.max_retries + 1):
      if Attempt > 0:
        Retried = True
      try:
        Response = requests.post(
          f"{self.endpoint}/workflows/run",
          headers={"Authorization": f"Bearer {self.api_key}"},
          json={"inputs": Inputs, "response_mode": "blocking", "user": DIFY_USER_ID},
          timeout=self.timeout,
        )
        Response.raise_for_status()
        Body = Response.json()
        Data = Body["data"]
        if Data["status"] != "succeeded":
          raise RuntimeError(Data.get("error") or "workflow_status_not_succeeded")
        Outputs = Data["outputs"]
        return (
          WorkflowResult(
            ok=Outputs.get("ok"),
            errors=Outputs.get("errors"),
            verdict=Outputs.get("verdict"),
            log=Outputs.get("log"),
          ),
          Retried,
        )
      except (requests.RequestException, KeyError, RuntimeError) as Error:
        LastError = Error
    return (
      WorkflowResult(ok=False, errors=[str(LastError)], verdict={}, log=""),
      Retried,
    )
