"""CP 진입점 — 단일 프로세스에 gRPC(에이전트 stream) + HTTP(FastAPI) 공존.

설계: docs/design/01-repo-structure.md (CP는 단일 Python 서비스에 http+grpc 공존).
"""
from __future__ import annotations

import time

import uvicorn

from .config import settings
from .db.session import init_db
from .enrollment.ca import InternalCA
from .grpc.server import serve_grpc


def _init_db_with_retry(attempts: int = 30) -> None:
    for i in range(attempts):
        try:
            init_db()
            return
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2)  # Postgres 등 기동 대기


def main() -> None:
    _init_db_with_retry()
    ca = InternalCA.load_or_create(settings.ca_dir)
    grpc_server = serve_grpc(settings.host, settings.grpc_port, ca, settings.grpc_sans)
    print(f"gRPC AgentStream (mTLS) on {settings.host}:{settings.grpc_port}")
    try:
        uvicorn.run("xgen_orchestrator.http.app:app", host=settings.host, port=settings.port)
    finally:
        grpc_server.stop(grace=2)


if __name__ == "__main__":
    main()
