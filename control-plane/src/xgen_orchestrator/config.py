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


settings = Settings()
