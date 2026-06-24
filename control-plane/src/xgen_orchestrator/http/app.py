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
from ..grpc.hub import hub
from ..pb import job_pb2, stream_pb2

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


class JobCreate(BaseModel):
    action: str = "exec"  # install|uninstall|status|exec (1차: exec, 번들 액션은 후속)
    params: dict[str, str] = {}


@app.post("/v1/nodes/{node_id}/jobs")
def create_job(node_id: str, body: JobCreate) -> dict:
    """노드에 Job 생성 → 보안 stream으로 RunJob 명령 push (at-least-once)."""
    now = dt.datetime.now(dt.timezone.utc)
    job_id = str(uuid.uuid4())
    command_id = str(uuid.uuid4())
    with SessionLocal() as db:
        node = db.get(models.Node, node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="unknown node")
        if node.status != "online":
            raise HTTPException(status_code=409, detail="node not online")
        db.add(models.Job(
            id=job_id, node_id=node_id, command_id=command_id, kind="run_job",
            phase="pending", params=body.params, created_at=now))
        db.add(models.Command(
            command_id=command_id, node_id=node_id, job_id=job_id, sent_at=now, attempt=1))
        db.commit()

    cmd = job_pb2.Command(
        command_id=command_id,
        run_job=job_pb2.RunJob(job_id=job_id, action=body.action, params=body.params),
    )
    if not hub.send(node_id, stream_pb2.ServerMessage(command=cmd)):
        raise HTTPException(status_code=409, detail="node not connected to stream")
    return {"job_id": job_id, "command_id": command_id, "phase": "pending"}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with SessionLocal() as db:
        j = db.get(models.Job, job_id)
        if j is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return {
            "job_id": j.id, "node_id": j.node_id, "kind": j.kind, "phase": j.phase,
            "exit_code": j.exit_code, "params": j.params,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }


@app.get("/v1/jobs/{job_id}/logs")
def get_job_logs(job_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(models.JobLog).where(models.JobLog.job_id == job_id)
            .order_by(models.JobLog.offset)
        ).all()
        return [
            {"offset": r.offset, "stream": r.stream, "ts_unix_ms": r.ts_unix_ms, "text": r.text}
            for r in rows
        ]


@app.get("/v1/nodes/{node_id}/inventory")
def node_inventory(node_id: str) -> dict:
    with SessionLocal() as db:
        inv = db.get(models.NodeInventory, node_id)
        if inv is None:
            raise HTTPException(status_code=404, detail="no inventory yet")
        gpus = db.scalars(select(models.NodeGPU).where(models.NodeGPU.node_id == node_id)).all()
        return {
            "node_id": node_id,
            "content_hash": inv.content_hash,
            "collected_at": inv.collected_at.isoformat() if inv.collected_at else None,
            "data": inv.data,
            "gpus": [
                {
                    "index": g.index,
                    "model": g.model,
                    "vram_bytes": g.vram_bytes,
                    "driver_version": g.driver_version,
                    "cuda_version": g.cuda_version,
                    "mig_enabled": g.mig_enabled,
                }
                for g in gpus
            ],
        }


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
