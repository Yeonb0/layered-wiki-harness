#!/bin/sh
# 공개 시연 서버 시작 : 임베딩 서버를 뒤에서 띄우고 준비되면 시연 API 로 넘어간다
# MODEL_ID · DAILY_JOB_LIMIT 은 Cloud Run 환경 변수, LAYERED_WIKI_LLM_API_KEY 는 Secret. 값은 출력하지 않는다
set -eu

: "${PORT:?PORT 가 없다}"
: "${MODEL_ID:?MODEL_ID 가 없다}"
: "${DAILY_JOB_LIMIT:?DAILY_JOB_LIMIT 이 없다}"
: "${LAYERED_WIKI_LLM_API_KEY:?LAYERED_WIKI_LLM_API_KEY 가 없다}"

RUN_DIR=$(find /app/run -mindepth 1 -maxdepth 1 -type d | head -n 1)
mkdir -p /tmp/demo/meetings /tmp/demo/minutes

llama-server -m /app/models/bge-m3-Q8_0.gguf --host 127.0.0.1 --port 8082 --embedding -ngl 0 -c 8192 -b 8192 -ub 8192 -np 1 -t 2 &

# 임베딩 서버가 준비될 때까지 최대 120초 기다린다 (시연 API 가 시작할 때 노트를 임베딩한다)
python - <<'PY'
import json, sys, time, urllib.request
End = time.monotonic() + 120
while time.monotonic() < End:
  try:
    with urllib.request.urlopen("http://127.0.0.1:8082/health", timeout=2) as R:
      if json.load(R).get("status") == "ok":
        sys.exit(0)
  except Exception:
    pass
  time.sleep(1)
print("임베딩 서버가 120초 안에 준비되지 않았다", flush=True)
sys.exit(1)
PY

exec python -m serve.demo_api --run-dir "$RUN_DIR" --host 0.0.0.0 --port "$PORT" \
  --cors-origin https://yeonbora.dev --front direct --model-id "$MODEL_ID" --daily-job-limit "$DAILY_JOB_LIMIT" \
  --harness-commit "$(cat /app/HARNESS_COMMIT)" \
  --meetings-file /tmp/demo/meetings/meetings.json --meetings-seed /app/harness/demo_corpus/meetings/seed_meetings.json \
  --minutes-dir /tmp/demo/minutes
