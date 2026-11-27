# 공개 시연 서버 (Cloud Run)

설계 : yeonbora-site `docs/superpowers/specs/2026-11-27-layered-wiki-project-page-design.md` 9.4 ~ 9.9. 시연 경로 전용이며 실험 경로 (agent · runner · retrieval · labeling) 의 동작은 바꾸지 않는다.

## 구성

| 항목 | 값 |
| --- | --- |
| 서비스 | `layered-wiki-demo`, 리전 `asia-northeast1` (도쿄), 최대 인스턴스 1, 최소 0, CPU 상시 할당 |
| 앞단 | `--front direct` (Dify 없음). 로컬 시연은 `--front dify` 그대로 |
| 라이브 · Q&A 모델 | `qwen/qwen3.5-9b` (OpenRouter). 미리 돌린 볼트는 로컬 Qwen3-8B-Q4_K_M |
| 임베딩 | 같은 컨테이너의 llama-server + bge-m3-Q8_0 (CPU), 미리 돌린 볼트와 같은 파일 |
| 상한 | 시연 API 하루 30회 (서울 자정 기준, LLM 을 부르는 POST 전부 함께), OpenRouter 키 금액 상한 $5 |
| 데이터 | 합성 시연 코퍼스 (스냅샷 900) 만. 하니스의 `corpus/` · `docs/` · `tests/` 등은 이미지에 넣지 않는다 |
| 상태 | 회의 · 회의록 · 라이브 결과는 컨테이너 `/tmp` 에만 있어 재시작하면 시드 상태로 돌아간다 |

## 파일

- `stage_inputs.py` : 미리 돌린 실행 폴더와 manifest 가 가리키는 입력 파일을 재료 폴더로 복사하고, 복사본 manifest 의 경로만 `/app/inputs/` 로 고친다 (원본은 그대로). snapshot 900 · run_kind demo 가 아니면 멈춘다
- `deploy.sh` : 재료 폴더를 만들고 `gcloud run deploy --source` 로 올린다. 작업 트리가 깨끗해야 한다
- `Dockerfile` · `entrypoint.sh` : 이미지와 시작 스크립트
- `probe_openrouter.py` : 후보 모델에 분해 요청 1건씩 (모델 고르기)

## 배포 (관리자님 WSL)

```bash
gcloud auth login
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com --project <프로젝트 id>
read -rs K && printf %s "$K" | gcloud secrets create openrouter-demo-key --data-file=- --project <프로젝트 id> ; unset K
cd ~/layered-wiki && deploy/demo-cloudrun/deploy.sh <프로젝트 id>
```

Cloud Run 서비스 계정에 `roles/secretmanager.secretAccessor` 가 필요하다. 배포 뒤 출력된 주소로 `curl <주소>/health` → `"front": "direct"`, `"model_id": "qwen/qwen3.5-9b"`.

## 데모데이 (12-16 · 12-18) 와 리허설 날

```bash
gcloud run services update layered-wiki-demo --min-instances 1 --region asia-northeast1
# 끝나면
gcloud run services update layered-wiki-demo --min-instances 0 --region asia-northeast1
```

## 로컬에서 이미지 시험 (Docker 가 있을 때)

```bash
deploy/demo-cloudrun/deploy.sh <아무 문자열> --local-only
docker build -t layered-wiki-demo <출력된 재료 폴더>
read -rs K && docker run --rm -p 8090:8080 -e PORT=8080 -e MODEL_ID=qwen/qwen3.5-9b -e DAILY_JOB_LIMIT=30 -e LAYERED_WIKI_LLM_API_KEY="$K" layered-wiki-demo ; unset K
curl -s localhost:8090/health
```
