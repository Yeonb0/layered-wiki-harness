# layered-wiki-harness

권한 층이 존재하는 문서 집합에서 **배치 판정**(새 개념을 어느 층에 만들 것인가)과 **하향 조건부 링크**를 수행하는 에이전트를 만들고, 산출 그래프를 **도달성**과 **누출** 두 축으로 평가하기 위한 파일럿 하니스다.

최종 산출물은 위키 사이트가 아니라 **평가 결과**다. 여기 있는 코드는 실험을 돌리기 위한 수단이며, 사이트 빌드 품질·UI·문서 렌더링은 다루지 않는다. 고정 결정, 용어, 범위, 절대 하지 말 것 등 전체 맥락은 [`CLAUDE.md`](./CLAUDE.md)에 있다.

## 층 구조와 흐름

- 층: 개인 / 팀 / 전사 (3층 고정)
- 링크는 아래에서 위로만(상향 링크), 백링크는 기록하지 않는다
- 하향 경로는 조건부 링크로만 존재하고 로컬 볼트에만 저장한다 (공개 정적 빌드에는 포함하지 않는다)
- 승격은 사람이 명시적으로 전환하며, 에이전트는 후보를 제시하지 않는다 (이 파일럿에서는 구현하지 않는다)

비교하는 조건은 B0(규칙 기반) / B1(단일 프롬프트) / B2(기존 오픈소스 위키 빌더) / 제안 4가지이고, 권한 범위(전 층 열람 단일 에이전트 vs 층별 인스턴스 분리)와 검색 후보 개수 k(4/8/16)가 실험 변수다.

## 디렉터리 구조

| 경로 | 역할 |
| --- | --- |
| `retrieval/` | 검색 레이어. `Retriever.search(query, k, mode, caller_layer)` |
| `vault/` | 볼트. 문서 레코드 저장 — 파일 포맷은 미결정, JSONL 잠정 처리를 `vault/jsonl_backend.py` 한 곳에 격리 |
| `client/` | Dify 워크플로 호출(`DifyClient`)과 응답 검증(`validation.py`). 워크플로 부재 시 배선 테스트용 `FakeDifyClient` |
| `runner/` | 순차 성장 러너 — 빈 볼트에서 시작해 문서를 조건 인터리빙으로 한 건씩 투입, 콜드 스타트 감지 포함 |
| `verdictlog/` | 판정 로그 스키마와 writer. 볼트 외부 JSONL, 사후 재집계를 위해 원본을 최대한 보존 |
| `analysis/` | 집계 스크립트. 로그 JSONL만 읽는다 (볼트·모델 접근 없음), 분산을 평균보다 먼저 낸다, 절대 목표 수치·통과/실패 판정 없음 |
| `config/` | `RunConfig` — 조건/모드/k/모델 식별자와 추론 파라미터 스냅샷 |
| `run_pilot.py` | 위 모듈들을 엮어 실제로 돌리는 진입점 |
| `tests/` | 표준 라이브러리 `unittest` 기반. llama-server·Dify 없이도 전부 돌아간다 |

## 실행 준비

```
pip install -r requirements.txt
export DIFY_ENDPOINT=...   # Dify 워크플로 실행 API 베이스 URL
export DIFY_API_KEY=...
```

임베딩은 `http://localhost:8081/v1/embeddings` (bge-m3, GPU 상주)를 호출한다. 판정 LLM(Qwen3 8B Q4_K_M, CPU 전량 추론)은 Dify 워크플로 안에서 호출되며, 워크플로 자체는 Dify UI에서 사람이 구성한다.

## 파일럿 실행

```
python3 run_pilot.py \
  --docs pilot_docs.jsonl \
  --model-id <실제 로컬 빌드/양자화본 식별자> \
  --threads <물리 코어 - 2> \
  --cold-start-threshold-seconds <실측값> \
  --vault-dir ./vaults/<run명> \
  --log-path ./logs/<run명>/verdict_log.jsonl
```

`--docs`가 가리키는 JSONL은 `{"id", "title", "body"}` 필드를 가진 문서 한 줄씩이다 (몇 건을 넣을지는 실험 설계 미결정 항목이라 하니스가 정하지 않는다). Dify 워크플로가 아직 없으면 `--client fake`로 배선만 먼저 확인할 수 있다. `--conditions` / `--modes` / `--ks`로 CLAUDE.md가 이미 고정한 값의 부분집합만 돌릴 수도 있다.

`examples/sample_docs.jsonl`은 실제 파일럿 코퍼스가 아니라 배선 확인용 샘플 5건이다. llama-server(:8081)가 떠 있는 상태에서 아래처럼 배선만 빠르게 확인할 수 있다.

```
python3 run_pilot.py \
  --docs examples/sample_docs.jsonl \
  --model-id dry-run \
  --threads 2 \
  --cold-start-threshold-seconds 999 \
  --vault-dir /tmp/layered-wiki-dryrun/vaults \
  --log-path /tmp/layered-wiki-dryrun/verdict_log.jsonl \
  --client fake
```

## 테스트

```
python3 -m unittest discover -s tests -v
```

llama-server, Dify, 네트워크 접근 없이 전부 통과해야 한다 (임베딩·Dify 호출부는 주입 가능하게 만들어져 있다).

## 진행 상황

### 완료한 것

1. 하니스 6개 모듈(판정 로그 스키마, 검색 레이어, Dify 클라이언트+응답 검증, 순차 성장 러너, 집계 스크립트) + 진입점(`run_pilot.py`) 구현 — `tests/` 27개 전부 통과 (`FakeDifyClient`·합성 임베딩 벡터로 검증)
2. bge-m3 임베딩 서버를 실제로 기동해서 검증 — `llama-server --port 8081 -ngl 99 --embedding -hf gpustack/bge-m3-GGUF:Q8_0`, GPU 346MB 사용, `/v1/embeddings`가 1024차원 벡터를 정상 반환
3. `run_pilot.py --client fake`로 **실제 bge-m3 서버**를 통한 전체 드라이런 실행 — `examples/sample_docs.jsonl` 5건 × 조건-셀 24개(B0/B1/B2/제안 × all_layers/split_by_layer × k=4/8/16) → 로그 120줄. 볼트별 순차 삽입(`inserted_at_vault_size` 0→4), 검색 후보가 볼트 크기만큼만 늘어나는 것과 k 상한이 실제로 지켜지는 것을 확인
4. 위 실제 로그로 `analysis` 집계(cold_start/retried 제외 처리시간 통계, 조건별 분산, 누출 대조)까지 정상 실행 확인

### 해야 할 것 (순서대로)

1. **Dify 워크플로 구성.** Dify UI에서 사람이 직접 만들어야 하고, 배치 판정 프롬프트의 층 정의 기준부터 먼저 성문화해야 한다 — 이 두 가지는 `CLAUDE.md` "절대 하지 말 것" 1번에 걸려 내가 대신 못 한다.
2. Qwen3 8B Q4_K_M 판정 LLM을 `llama-server`(:8080, `-ngl 0` CPU 전량 추론)로 기동하고 Dify(Docker) 컨테이너와 연동
3. `--client real`로 위 워크플로를 1회 이상 실제 호출해 `DifyClient`의 타임아웃/재시도 경로까지 검증 (지금까지는 `FakeDifyClient` 경로만 통과)
4. 파일럿 문서 코퍼스 준비 — 몇 건을 넣을지는 실험 설계 미결정 항목이라 하니스가 정하지 않는다
5. 머신별 실측값 확정 — `--threads`(물리 코어 - 2), `--cold-start-threshold-seconds`(실측), `--model-id`(실제 로컬 빌드/양자화본 식별자)
6. 위 전부 갖춰지면 실제 파일럿 실행 → 로그 축적 → `analysis`로 집계

## 범위 밖

승격 처리 구현, 다중 소스 자동 수집, 긴 문서의 개념 단위 분해, 실시간 협업 편집, 인증·세션 배관, 위키 사이트 빌드/UI/렌더링. 자세한 이유는 `CLAUDE.md`의 "범위" 절 참고.
