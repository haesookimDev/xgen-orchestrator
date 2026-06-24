"""CP 설정 — env 기반. 1차 구동은 SQLite + 단일 공유 join token(데모용).

설계: docs/design/02-enrollment-security.md, 04-data-model.md, 12-operational-policies.md.
정식 운영에서는 join_tokens 테이블/마스터키/Postgres로 승격(TODO).
"""
from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv("XGEN_DATABASE_URL", "sqlite:///./cp.db")
        self.join_token = os.getenv("XGEN_JOIN_TOKEN", "test-token")  # TODO: join_tokens 테이블
        self.ca_dir = os.getenv("XGEN_CA_DIR", "./cp-ca")
        self.host = os.getenv("XGEN_HOST", "0.0.0.0")
        self.port = int(os.getenv("XGEN_PORT", "18080"))  # HTTP (REST)
        self.grpc_port = int(os.getenv("XGEN_GRPC_PORT", "18081"))  # gRPC (agent stream)
        # gRPC 서버 cert SAN (에이전트가 접속하는 주소). IP/DNS 콤마 구분.
        self.grpc_sans = os.getenv("XGEN_GRPC_SAN", "127.0.0.1,localhost").split(",")
        # 번들 아티팩트 저장 디렉토리 + 에이전트가 fetch할 공개 베이스 URL.
        self.bundle_dir = os.getenv("XGEN_BUNDLE_DIR", "./cp-bundles")
        self.public_url = os.getenv("XGEN_PUBLIC_URL", f"http://127.0.0.1:{self.port}")


settings = Settings()
