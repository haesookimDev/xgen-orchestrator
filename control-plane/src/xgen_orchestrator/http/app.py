"""FastAPI — 운영자 REST + 에이전트 등록(REST).

1차 슬라이스: /v1/enroll (내부 CA가 CSR 서명) + /v1/nodes + /healthz.
gRPC(에이전트 stream)는 grpc/server.py (다음 단계). 설계: 02-enrollment-security.md, 07.
"""
from __future__ import annotations

import datetime as dt
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..db import models
from ..db.session import SessionLocal, init_db
from ..enrollment.ca import InternalCA

_ca: InternalCA | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ca
    init_db()
    _ca = InternalCA.load_or_create(settings.ca_dir)
    yield


app = FastAPI(title="xgen-orchestrator control-plane", lifespan=lifespan)


class NodeInfo(BaseModel):
    hostname: str = ""
    machine_id: str
    os: str = ""
    arch: str = ""


class EnrollRequest(BaseModel):
    join_token: str
    csr: str  # PEM
    node_info: NodeInfo


class EnrollResponse(BaseModel):
    node_id: str
    client_cert: str  # PEM
    ca_bundle: str  # PEM


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/enroll", response_model=EnrollResponse)
def enroll(req: EnrollRequest) -> EnrollResponse:
    if req.join_token != settings.join_token:
        raise HTTPException(status_code=401, detail="invalid join token")

    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        node = db.scalar(
            select(models.Node).where(models.Node.machine_id == req.node_info.machine_id)
        )
        if node is None:
            node = models.Node(
                id=str(uuid.uuid4()),
                machine_id=req.node_info.machine_id,
                hostname=req.node_info.hostname,
                status="online",
                os=req.node_info.os,
                arch=req.node_info.arch,
                enrolled_at=now,
                last_seen_at=now,
            )
            db.add(node)
        else:
            # TODO(P0-2): 중복 machine_id -> pending_reenroll + 재등록 토큰.
            # 1차 구현은 멱등 재등록(기존 node_id 재사용).
            node.hostname = req.node_info.hostname
            node.last_seen_at = now
        node_id = node.id

        try:
            cert_pem = _ca.sign_csr(req.csr.encode(), node_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        db.add(models.NodeCert(
            node_id=node_id,
            serial="",
            spiffe_uri=f"spiffe://xgen/node/{node_id}",
            issued_at=now,
        ))
        db.commit()

    return EnrollResponse(
        node_id=node_id,
        client_cert=cert_pem.decode(),
        ca_bundle=_ca.pem.decode(),
    )


@app.get("/v1/nodes")
def list_nodes() -> list[dict]:
    with SessionLocal() as db:
        nodes = db.scalars(select(models.Node)).all()
        return [
            {
                "node_id": n.id,
                "hostname": n.hostname,
                "machine_id": n.machine_id,
                "status": n.status,
                "os": n.os,
                "arch": n.arch,
                "enrolled_at": n.enrolled_at.isoformat() if n.enrolled_at else None,
            }
            for n in nodes
        ]
