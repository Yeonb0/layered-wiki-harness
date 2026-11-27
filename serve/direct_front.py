# 공개 시연 서버 (설계 9.7) : Dify 를 빼고 서버 안에서 같은 일을 하는 대신 함수
# demo_api 는 Dify 호출을 주입받는 함수 (dify_fn, dify_chat_fn) 로 쓰므로 같은 모양의 함수를 넣어 나머지 경로를 바꾸지 않는다
import json
import re
import uuid
from collections.abc import Callable, Iterator

from agent.llm_client import GenerationConfig


def make_direct_live_fn(App, wait_seconds: float) -> Callable[[dict, str], Iterator[dict]]:
  # Dify 워크플로가 하던 일 : /jobs 에 작업 제출 → 끝날 때까지 대기. 이벤트 모양은 Dify 스트림과 같다 (_live_main 은 고치지 않는다)
  def live(inputs: dict, user: str) -> Iterator[dict]:
    yield {"event": "workflow_started", "data": {"workflow_run_id": f"direct-{uuid.uuid4().hex}"}}
    Status, Body = App.submit({"doc_id": inputs.get("doc_id"), "mode": inputs.get("mode")})
    if Status != 202:
      # 제출이 거절되면 (409 Busy, 400 · 404) 바로 실패로 끝낸다 : 화면이 running 으로 남지 않게
      yield {"event": "workflow_finished", "data": {"status": "failed", "outputs": {"error": Body}}}
      return
    JobId = Body["job_id"]
    Job = App.jobs[JobId]
    # 기다리는 한도를 넘기면 작업은 뒤에서 계속 돌지만 라이브는 실패로 끝낸다
    Done = Job["event"].wait(wait_seconds)
    JobStatus = Job["status"] if Done else "running"
    yield {
      "event": "workflow_finished",
      "data": {"status": "succeeded" if JobStatus == "completed" else "failed", "outputs": {"job_id": JobId, "job_status": JobStatus}},
    }

  return live


# demo_dify/layered_qa_chatflow.yml "근거 답변" 노드의 시스템 프롬프트를 글자 그대로 옮긴다. 노트 자리만 {context}
QA_SYSTEM_PROMPT = '너는 가상 게임 스튜디오의 사내 노트만 근거로 답하는 도우미다.\n규칙\n1. 아래 <노트> 안의 내용만 근거로 쓴다. 노트에 없는 내용은 추측하지 않는다\n2. 근거가 없으면 "주어진 노트에서 찾을 수 없습니다." 한 문장만 답한다\n3. 근거로 쓴 문장 끝에 그 노트의 id 를 대괄호로 적는다. 예 : … 이다 [노트 id]\n4. 대괄호 안에는 노트 id 만 쓴다\n5. 한국어로 짧게 답한다\n<노트>\n{context}\n</노트>'
# 챗플로우의 "보기 안 검색" 노드와 같은 k
QA_SEARCH_K = 4
QA_MAX_TOKENS = 1024
# 챗플로우의 "검색 결과 풀기" 노드가 실패 본문을 자르는 길이
_SEARCH_ERROR_CHARS = 300
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_CITE = re.compile(r"\[([^\[\]]+)\]")


def format_answer(text: str, allowed_ids: list[str]) -> dict:
  # 챗플로우의 "인용 검사" 코드 노드와 같은 결과 : 생각 블록 제거, 검색 결과에 있던 노트만 근거로 인정
  Text = _THINK_BLOCK.sub("", text).strip()
  Cited = []
  for Id in _CITE.findall(Text):
    if Id not in Cited:
      Cited.append(Id)
  Valid = [Id for Id in Cited if Id in allowed_ids]
  Invalid = [Id for Id in Cited if Id not in allowed_ids]
  Lines = [Text, "", "근거 노트 : " + (", ".join(Valid) if Valid else "없음")]
  if Invalid:
    Lines.append("검색 결과에 없는 인용 (무효) : " + ", ".join(Invalid))
  return {"answer": "\n".join(Lines), "valid_count": len(Valid), "invalid_count": len(Invalid)}


def make_direct_chat_fn(App, chat_fn, model_id: str) -> Callable[[dict, str, str], dict]:
  # Dify 챗플로우가 하던 일 : 보는 사람의 보기 안에서 검색 → 노트만 근거로 답 → 인용 검사
  def ask(inputs: dict, query: str, user: str) -> dict:
    Status, Found = App.search(inputs["mode"], inputs["viewer"], query, QA_SEARCH_K)
    if Status != 200:
      # 챗플로우는 검색이 실패하면 그 응답을 답으로 드러낸다
      Body = json.dumps(Found, ensure_ascii=False)[:_SEARCH_ERROR_CHARS]
      return {"answer": f"검색 실패 ({Status}) : {Body}", "message_id": None, "conversation_id": None}
    Allowed = [Item["note_id"] for Item in Found["results"]]
    # str.format 을 쓰지 않는다 : 노트 본문의 중괄호가 자리표시로 읽히지 않게
    System = QA_SYSTEM_PROMPT.replace("{context}", Found["context"])
    # 생각 모드는 enable_thinking=False 로 끈다 (챗플로우의 /no_think 는 붙이지 않는다)
    Config = GenerationConfig(temperature=0, seed=App.gen_seed, max_tokens=QA_MAX_TOKENS, enable_thinking=False)
    Result = chat_fn(
      [{"role": "system", "content": System}, {"role": "user", "content": query}], model_id, Config, None,
      timeout_seconds=App.timeout_seconds,
    )
    return {"answer": format_answer(Result.text, Allowed)["answer"], "message_id": None, "conversation_id": None}

  return ask
