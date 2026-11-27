#!/usr/bin/env bash
# 공개 시연 서버 배포 (설계 9.7.1) : 관리자님 WSL 에서 빌드 재료 폴더를 만들고 Cloud Build 로 Cloud Run 에 올린다
# 사용 : deploy/demo-cloudrun/deploy.sh <GCP 프로젝트 id> [--local-only]
#   --local-only : 재료 폴더만 만들고 경로를 출력한다 (docker build 로 직접 시험할 때)
# 키 값은 출력하지 않는다. 키는 Secret Manager 의 openrouter-demo-key 에서 Cloud Run 이 넘긴다
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "사용 : $0 <GCP 프로젝트 id> [--local-only]" >&2
  exit 2
fi
PROJECT_ID="$1"
LOCAL_ONLY="${2:-}"
if [ -n "$LOCAL_ONLY" ] && [ "$LOCAL_ONLY" != "--local-only" ]; then
  echo "두 번째 인자는 --local-only 만 받는다" >&2
  exit 2
fi

# 설계 9.9 결정값 : 바꿀 때는 이 파일을 고쳐 커밋한다 (실행 인자로 덮어쓰지 않는다)
MODEL_ID="qwen/qwen3.5-9b"
DAILY_JOB_LIMIT="30"
REGION="asia-northeast1"
SERVICE="layered-wiki-demo"
SECRET="openrouter-demo-key"
RUN_DIR="$HOME/layered-wiki-work/demo/demo900_propose_20261022_193431"
EMBED_MODEL="$HOME/models/bge-m3-Q8_0.gguf"

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"

# (1) 작업 트리가 깨끗해야 이미지의 코드와 기록되는 커밋이 같다
if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
  echo "하니스 작업 트리가 깨끗하지 않다 : 커밋하거나 되돌린 뒤 다시 실행한다" >&2
  exit 1
fi
for Path in "$RUN_DIR/manifest.json" "$EMBED_MODEL"; do
  if [ ! -f "$Path" ]; then
    echo "없다 : $Path" >&2
    exit 1
  fi
done

# (2) 재료 폴더
STAGE="$(mktemp -d)/material"
python3 "$HERE/stage_inputs.py" --run-dir "$RUN_DIR" --out-dir "$STAGE"
mkdir -p "$STAGE/harness" "$STAGE/models"
# 시연 API 실행에 필요 없는 폴더는 이미지에 넣지 않는다. corpus/ 는 실제 코퍼스의 페이지 경로 · 링크 메타데이터라 특히 뺀다 (지침 3절 18 · 21)
git -C "$REPO" archive HEAD -- . ':(exclude)corpus' ':(exclude)docs' ':(exclude)tests' ':(exclude)demo_ui' ':(exclude)demo_dify' \
  ':(exclude)analysis' ':(exclude)examples' ':(exclude)client' ':(exclude)deploy' | tar -x -C "$STAGE/harness"
git -C "$REPO" rev-parse HEAD > "$STAGE/HARNESS_COMMIT"
cp "$EMBED_MODEL" "$STAGE/models/bge-m3-Q8_0.gguf"
cp "$HERE/Dockerfile" "$HERE/entrypoint.sh" "$HERE/.dockerignore" "$STAGE/"

# (3) 실제 코퍼스 · 다른 실행이 섞이지 않았는지 확인 (지침 3절 18 · 21)
if find "$STAGE" -path '*layered-wiki-corpus*' | grep -q .; then
  echo "재료 폴더에 실제 코퍼스 경로가 있다" >&2
  exit 1
fi
if [ -e "$STAGE/harness/corpus" ]; then
  echo "재료 폴더에 harness/corpus 가 남아 있다" >&2
  exit 1
fi
# 이미지 안에서 시연 API 를 불러올 수 있는지 미리 본다 (뺀 폴더에 의존하면 여기서 멈춘다)
(cd "$STAGE/harness" && python3 -c "import serve.demo_api")
if [ "$(find "$STAGE/run" -mindepth 1 -maxdepth 1 -type d | wc -l)" != "1" ]; then
  echo "재료 폴더의 run/ 에 실행이 하나가 아니다" >&2
  exit 1
fi
echo "재료 폴더 : $STAGE ($(du -sh "$STAGE" | cut -f1))"

if [ "$LOCAL_ONLY" = "--local-only" ]; then
  echo "docker build -t layered-wiki-demo \"$STAGE\""
  exit 0
fi

# (4) Cloud Build 로 이미지를 만들고 Cloud Run 에 올린다
gcloud run deploy "$SERVICE" --source "$STAGE" --region "$REGION" --project "$PROJECT_ID" \
  --max-instances 1 --min-instances 0 --no-cpu-throttling --cpu 2 --memory 4Gi --timeout 900 --concurrency 20 \
  --allow-unauthenticated \
  --set-env-vars "MODEL_ID=$MODEL_ID,DAILY_JOB_LIMIT=$DAILY_JOB_LIMIT" \
  --set-secrets "LAYERED_WIKI_LLM_API_KEY=$SECRET:latest"
