"""CP 진입점 — 단일 프로세스에 gRPC(에이전트 stream) + HTTP(FastAPI) 공존.

설계: docs/design/01-repo-structure.md (CP는 단일 Python 서비스에 http+grpc 공존).
"""
from __future__ import annotations

import uvicorn

from .config import settings
from .db.session import init_db
from .enrollment.ca import InternalCA
from .grpc.server import serve_grpc


def main() -> None:
    init_db()
    ca = InternalCA.load_or_create(settings.ca_dir)
    grpc_server = serve_grpc(settings.host, settings.grpc_port, ca, settings.grpc_sans)
    print(f"gRPC AgentStream (mTLS) on {settings.host}:{settings.grpc_port}")
    try:
        uvicorn.run("xgen_orchestrator.http.app:app", host=settings.host, port=settings.port)
    finally:
        grpc_server.stop(grace=2)


if __name__ == "__main__":
    main()
