"""SQLAlchemy 모델 — 1차 슬라이스(관측) 중심 + 핵심 후속 테이블.

설계: docs/design/04-data-model.md (+ 10 스키마 델타, 11 클러스터, 12 시크릿).
1차 슬라이스에 필수: nodes, node_certs, join_tokens, node_inventory(+history), node_gpus.
설치/운영 테이블(jobs, commands, job_logs, bundles, clusters, secrets, operators, audit_log)도
계약 고정을 위해 선언해 둔다.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 이식 가능한 타입(SQLite·Postgres 공용). Postgres 전용 JSONB/UUID/TIMESTAMP 대신
# JSON / String(36) / DateTime 을 쓴다 — 스키마 의미는 04-data-model.md 와 동일.


class Base(DeclarativeBase):
    pass


# ---- 1차 슬라이스: 등록 + 인벤토리 ----

class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    machine_id: Mapped[str] = mapped_column(String, unique=True)
    hostname: Mapped[str | None] = mapped_column(String)
    # online|offline|disabled|revoked|pending_reenroll
    status: Mapped[str] = mapped_column(String)
    os: Mapped[str | None] = mapped_column(String)
    arch: Mapped[str | None] = mapped_column(String)
    agent_version: Mapped[str | None] = mapped_column(String)
    cert_serial: Mapped[str | None] = mapped_column(String)
    labels: Mapped[dict | None] = mapped_column(JSON)
    cluster_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("clusters.id"))
    cluster_role: Mapped[str | None] = mapped_column(String)  # server|worker|null
    enrolled_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))


class NodeCert(Base):  # 인증서 발급/폐기 이력 (P0-2, 감사)
    __tablename__ = "node_certs"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"))
    serial: Mapped[str] = mapped_column(String)
    spiffe_uri: Mapped[str] = mapped_column(String)  # spiffe://xgen/node/<node_id>
    issued_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String)


class JoinToken(Base):
    __tablename__ = "join_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    type: Mapped[str] = mapped_column(String)  # shared|one_time|re_enroll
    expires_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))


class NodeInventory(Base):
    __tablename__ = "node_inventory"
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True
    )
    content_hash: Mapped[str | None] = mapped_column(String)
    data: Mapped[dict | None] = mapped_column(JSON)  # 전체 InventoryReport
    collected_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))


class NodeInventoryHistory(Base):  # content_hash 변경 시 append
    __tablename__ = "node_inventory_history"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"))
    content_hash: Mapped[str | None] = mapped_column(String)
    data: Mapped[dict | None] = mapped_column(JSON)
    collected_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))


class NodeGPU(Base):  # 비정규화 (조회·집계)
    __tablename__ = "node_gpus"
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True
    )
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str | None] = mapped_column(String)
    vram_bytes: Mapped[int | None] = mapped_column(BigInteger)
    driver_version: Mapped[str | None] = mapped_column(String)
    cuda_version: Mapped[str | None] = mapped_column(String)
    mig_enabled: Mapped[bool | None] = mapped_column(Boolean)


# ---- 설치/운영 (2차 슬라이스~, 계약 고정용 선언) ----

class Cluster(Base):
    __tablename__ = "clusters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    runtime: Mapped[str | None] = mapped_column(String)  # k3s
    solution_id: Mapped[str | None] = mapped_column(String)
    version: Mapped[str | None] = mapped_column(String)
    server_url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)  # forming|ready|degraded
    plan: Mapped[dict | None] = mapped_column(JSON)  # {runtime,bundle,server_node,workers,job ids}
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("nodes.id"))
    command_id: Mapped[str] = mapped_column(String, unique=True)  # at-least-once 멱등
    kind: Mapped[str | None] = mapped_column(String)  # run_job|push_bundle|refresh_inventory|status
    phase: Mapped[str | None] = mapped_column(String)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int | None] = mapped_column(Integer)
    phase_seq: Mapped[int | None] = mapped_column(Integer)
    bundle_ref: Mapped[str | None] = mapped_column(String)
    params: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    # 노드당 mutating Job 1개 락(P1-2)은 alembic에서 partial unique index로 생성:
    #   CREATE UNIQUE INDEX one_mutating_job_per_node ON jobs(node_id)
    #     WHERE phase IN ('pending','running') AND kind <> 'status';


class Command(Base):  # 하행 명령 상태 영속 (CP 재시작 복원, P0-3)
    __tablename__ = "commands"
    command_id: Mapped[str] = mapped_column(String, primary_key=True)
    node_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("nodes.id"))
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jobs.id"))
    sent_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int | None] = mapped_column(Integer)


class JobLog(Base):  # 무손실, (job_id, source, offset) 중복 제거 (P0-3)
    __tablename__ = "job_logs"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"))
    ts_unix_ms: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str | None] = mapped_column(String)
    stream: Mapped[str | None] = mapped_column(String)  # stdout|stderr
    offset: Mapped[int | None] = mapped_column("offset", BigInteger)
    text: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("job_id", "source", "offset", name="uq_job_log_offset"),)


class Bundle(Base):
    __tablename__ = "bundles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    solution_id: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False)
    sha256: Mapped[str | None] = mapped_column(String)
    cosign_bundle: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict | None] = mapped_column(JSON)
    storage_uri: Mapped[str | None] = mapped_column(String)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    built_from: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("solution_id", "version", name="uq_bundle_version"),)
    # latest 단일 보장(정합성 #5)은 alembic partial unique index:
    #   CREATE UNIQUE INDEX one_latest_per_solution ON bundles(solution_id) WHERE is_latest;


class Secret(Base):  # app-level 암호화 (P1-3, 12)
    __tablename__ = "secrets"
    ref: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str | None] = mapped_column(String)  # cluster:<id>|global|node:<id>
    value_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    dek_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))


class Operator(Base):  # 운영자 인증 (P0-4)
    __tablename__ = "operators"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    pw_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)  # viewer|operator


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    actor: Mapped[str | None] = mapped_column(String)
    action: Mapped[str | None] = mapped_column(String)
    target: Mapped[str | None] = mapped_column(String)
    detail: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
