"""CP 진입점 — 1차 슬라이스는 FastAPI(HTTP)만 기동. gRPC stream은 다음 단계.

설계: docs/design/01-repo-structure.md (CP는 단일 Python 서비스에 http+grpc 공존).
"""
from __future__ import annotations

import uvicorn

from .config import settings


def main() -> None:
    uvicorn.run("xgen_orchestrator.http.app:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
