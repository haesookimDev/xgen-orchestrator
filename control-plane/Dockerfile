# Control Plane 이미지. 빌드 컨텍스트 = 레포 루트 (proto/ + agent/ + control-plane/ 필요).
#   docker build -f control-plane/Dockerfile -t xgen-cp .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# buf (proto codegen) — 이미지 arch에 맞춰 다운로드
RUN curl -fsSL "https://github.com/bufbuild/buf/releases/latest/download/buf-Linux-$(uname -m)" \
    -o /usr/local/bin/buf && chmod +x /usr/local/bin/buf

WORKDIR /app
# agent/ 는 buf.gen이 ../agent/gen 에도 출력하므로 경로 확보용으로 포함
COPY proto/ ./proto/
COPY agent/ ./agent/
COPY control-plane/ ./control-plane/
RUN cd proto && buf generate
RUN pip install --no-cache-dir -e ./control-plane

ENV XGEN_HOST=0.0.0.0
EXPOSE 18080 18081
CMD ["python", "-m", "xgen_orchestrator.main"]
