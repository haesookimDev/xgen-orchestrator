"""DB 엔진/세션. 1차 구동은 SQLite, Postgres로 전환 가능(이식 모델).

설계: docs/design/04-data-model.md. 정식 마이그레이션은 alembic(TODO);
1차는 create_all 로 부트스트랩.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from .models import Base

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
