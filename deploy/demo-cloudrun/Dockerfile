# 공개 시연 서버 이미지 (설계 9.4) : 시연 API + bge-m3 임베딩 llama-server (CPU) 를 한 컨테이너에
# 빌드 재료 폴더 (deploy.sh 가 만든다) 를 문맥으로 쓴다 : harness/ · run/ · inputs/ · models/ · HARNESS_COMMIT
# 키는 이미지에 넣지 않는다 : LAYERED_WIKI_LLM_API_KEY 는 Cloud Run 이 Secret Manager 에서 넘긴다

# 1단계 : llama.cpp 를 CPU 로 빌드 (llama-server 만)
FROM python:3.12-slim-bookworm AS llama
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates && rm -rf /var/lib/apt/lists/*
# 로컬 시연 · 실험과 같은 llama.cpp 빌드 (agent/prompts.py 주석의 b10453)
ARG LLAMA_CPP_REF=b10453
RUN git clone --depth 1 --branch "$LLAMA_CPP_REF" https://github.com/ggml-org/llama.cpp /src/llama.cpp
WORKDIR /src/llama.cpp
# 특정 CPU 명령에 묶지 않는다 : Cloud Run 의 CPU 종류를 고를 수 없다
# 웹 UI 는 끈다 : 임베딩 전용이라 필요 없고, 켜 두면 빌드 중 UI 자산 내려받기가 실패한다 (Cloud Build 070b194f)
RUN cmake -B build -DGGML_NATIVE=OFF -DBUILD_SHARED_LIBS=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_UI=OFF -DCMAKE_BUILD_TYPE=Release \
  && cmake --build build --target llama-server -j "$(nproc)"

# 2단계 : 실행 이미지
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=llama /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY harness/requirements.txt /app/harness/requirements.txt
# tzdata : 하루 상한의 서울 자정 (zoneinfo) 이 slim 이미지에서도 동작하게
RUN pip install --no-cache-dir -r /app/harness/requirements.txt tzdata
COPY harness/ /app/harness/
COPY run/ /app/run/
COPY inputs/ /app/inputs/
COPY models/ /app/models/
COPY HARNESS_COMMIT /app/HARNESS_COMMIT
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
WORKDIR /app/harness
ENV PYTHONHASHSEED=0 \
  PYTHONUNBUFFERED=1 \
  HOME=/tmp \
  LAYERED_WIKI_LLM_ENDPOINT=https://openrouter.ai/api/v1/chat/completions \
  LAYERED_WIKI_EMBED_ENDPOINT=http://127.0.0.1:8082/v1/embeddings
CMD ["/app/entrypoint.sh"]
