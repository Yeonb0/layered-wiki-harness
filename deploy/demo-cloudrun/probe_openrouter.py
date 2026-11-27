# 공개 시연 서버 모델 고르기 : OpenRouter 후보 모델에 분해 단계와 같은 요청을 1건씩 보내 되는지 본다
# 설계 : yeonbora-site docs/superpowers/specs/2026-11-27-layered-wiki-project-page-design.md 9.4, 9.9-2
# 입력은 합성 시연 코퍼스 (스냅샷 900) 문서만 쓴다 : 지침 3절 18 · 21
#
# 실행 (관리자님 터미널, 키는 화면 · 채팅에 남기지 않는다)
#   LAYERED_WIKI_LLM_ENDPOINT=https://openrouter.ai/api/v1/chat/completions \
#   LAYERED_WIKI_LLM_API_KEY=... \
#   python3 deploy/demo-cloudrun/probe_openrouter.py \
#     --run-dir ~/layered-wiki-work/demo/demo900_propose_20261022_193431 \
#     --doc-id 90000000000000000000000000000015 \
#     qwen/qwen3-8b <후보 2> <후보 3>
import argparse
import json
import os
import sys

# 저장소 루트에서 agent · runner 를 가져온다 : 이 파일은 deploy/demo-cloudrun/ 에 있다
REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_DIR not in sys.path:
  sys.path.insert(0, REPO_DIR)

from agent.decompose import DecompositionOutputError, build_segment_labels, parse_assignment
from agent.layer_block import load_layer_block
from agent.llm_client import LLM_API_KEY_ENV, GenerationConfig, chat
from agent.prompts import assign_schema, build_decompose_messages, require_block_in_messages
from runner.v2_sequential import load_source_docs

# 9.9-2 확인용 고정 시드 : 실험 시드와 겹치지 않게 날짜로
PROBE_SEED = 20261127
# 실제 요청 시간 한도 : 라이브 1건 분해 단계가 이 안에 끝나야 시연에 쓸 수 있다
PROBE_TIMEOUT_SECONDS = 180
# 데모 실행 manifest 의 snapshot : 합성 시연 코퍼스만 받는다
DEMO_SNAPSHOT = 900


def _hide_key(Text: str) -> str:
  # 오류 문구에 키가 섞여 나와도 출력에 남기지 않는다
  Key = os.environ.get(LLM_API_KEY_ENV, "")
  return Text.replace(Key, "***") if Key else Text


def probe(model_id: str, doc, layer_block: str, max_tokens: int, chat_fn=chat) -> dict:
  # 분해 단계와 같은 메시지 · 스키마 · 생성 설정 (생각 모드 끔) 으로 1건 보낸다
  LabelMap, Shown = build_segment_labels(doc)
  Labels = list(LabelMap)
  Messages = build_decompose_messages(layer_block, doc.source_layer, Shown, Labels)
  require_block_in_messages(Messages, layer_block)
  Config = GenerationConfig(temperature=0, seed=PROBE_SEED, max_tokens=max_tokens, enable_thinking=False)
  Row = {"model": model_id, "ok": False, "error": None, "finish_reason": None, "prompt_tokens": None, "completion_tokens": None, "elapsed_s": None}
  try:
    Result = chat_fn(Messages, model_id, Config, assign_schema(Labels), timeout_seconds=PROBE_TIMEOUT_SECONDS)
  except Exception as Error:
    # 거절 (chat_template_kwargs · 스키마 미지원) · 생각 누출 · usage 없음은 모두 여기로 : 원인 문구를 그대로 남긴다
    Row["error"] = _hide_key(f"{type(Error).__name__}: {Error}")
    return Row
  Row.update(finish_reason=Result.finish_reason, prompt_tokens=Result.prompt_tokens, completion_tokens=Result.completion_tokens, elapsed_s=round(Result.elapsed_seconds, 2))
  if Result.finish_reason != "stop":
    Row["error"] = f"finish_reason:{Result.finish_reason}"
    return Row
  try:
    parse_assignment(Result.text, LabelMap, {Seg.segment_id: Seg.text for Seg in doc.segments})
  except DecompositionOutputError as Error:
    Row["error"] = _hide_key(f"DecompositionOutputError: {Error}")
    return Row
  Row["ok"] = True
  return Row


def load_demo_input(run_dir: str, doc_id: str):
  # 시연 API 와 같은 방식으로 실행 manifest 에서 문서 · 층 정의를 읽는다
  with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as F:
    Args = json.load(F)["args"]
  if Args.get("snapshot") != DEMO_SNAPSHOT:
    raise ValueError(f"합성 시연 코퍼스 (snapshot {DEMO_SNAPSHOT}) 실행이 아니다: snapshot={Args.get('snapshot')!r}")
  Docs, _ = load_source_docs(Args["segments"], Args["docs"], Args["doc_ids"], Args["split_doc_ids"], Args["selection"])
  ById = {Doc.doc_id: Doc for Doc in Docs}
  if doc_id not in ById:
    raise ValueError(f"실행에 없는 문서: {doc_id}")
  Block, _ = load_layer_block(Args["criteria"], Args["criteria_sha256"])
  return ById[doc_id], Block, Args["decompose_max_tokens"], Args["model_id"]


def main(argv=None) -> None:
  Parser = argparse.ArgumentParser(description="OpenRouter 후보 모델에 분해 요청 1건씩")
  Parser.add_argument("--run-dir", required=True)
  Parser.add_argument("--doc-id", required=True)
  Parser.add_argument("models", nargs="+")
  Args = Parser.parse_args(argv)
  if not os.environ.get(LLM_API_KEY_ENV):
    Parser.error(f"{LLM_API_KEY_ENV} 가 없다")
  Doc, Block, MaxTokens, BaseModel = load_demo_input(os.path.expanduser(Args.run_dir), Args.doc_id)
  print(json.dumps({"doc_id": Doc.doc_id, "segments": len(Doc.segments), "max_tokens": MaxTokens, "base_model_id": BaseModel}, ensure_ascii=False), flush=True)
  for Model in Args.models:
    print(json.dumps(probe(Model, Doc, Block, MaxTokens), ensure_ascii=False), flush=True)


if __name__ == "__main__":
  main()
