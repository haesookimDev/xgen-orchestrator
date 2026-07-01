"""FastAPI — 운영자 REST + 에이전트 등록(REST).

1차 슬라이스: /v1/enroll (내부 CA가 CSR 서명) + /v1/nodes + /healthz.
gRPC(에이전트 stream)는 grpc/server.py (다음 단계). 설계: 02-enrollment-security.md, 07.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import secrets
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import auth, bundlesign, clusters, storage
from ..config import settings
from ..db import models
from ..db.session import SessionLocal, init_db
from ..enrollment.ca import InternalCA
from ..grpc.hub import hub
from ..pb import job_pb2, stream_pb2

_ca: InternalCA | None = None
_signer: bundlesign.BundleSigner | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ca, _signer
    init_db()
    auth.seed_admin()
    _ca = InternalCA.load_or_create(settings.ca_dir)
    _signer = bundlesign.BundleSigner.load_or_create(settings.ca_dir)
    yield


app = FastAPI(title="xgen-orchestrator control-plane", lifespan=lifespan)

# 운영자 대시보드 (경량 정적 SPA, REST 소비). 프로덕션 Next.js는 후속(07-operator-surface).
_STATIC = os.path.join(os.path.dirname(__file__), "static")
app.mount("/ui", StaticFiles(directory=_STATIC, html=True), name="ui")


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
    bundle_pubkey: str = ""  # 번들 서명 검증용 공개키(PEM)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/v1/login")
def login(body: LoginRequest) -> dict:
    with SessionLocal() as db:
        op = db.scalar(select(models.Operator).where(models.Operator.username == body.username))
        if op is None or not auth.verify_pw(body.password, op.pw_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        return {"token": auth.make_token(op.username, op.role), "role": op.role}


# ---- join token 관리 (P0-2/07) ----

class TokenCreate(BaseModel):
    type: str = "shared"  # shared | one_time
    ttl_hours: int | None = 24
    max_uses: int | None = None


@app.post("/v1/tokens")
def create_token(body: TokenCreate, op: dict = Depends(auth.require_operator)) -> dict:
    token = secrets.token_hex(16)
    now = dt.datetime.now(dt.timezone.utc)
    exp = now + dt.timedelta(hours=body.ttl_hours) if body.ttl_hours else None
    tid = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(models.JoinToken(
            id=tid, token_hash=hashlib.sha256(token.encode()).hexdigest(), type=body.type,
            expires_at=exp, max_uses=body.max_uses, used_count=0, revoked=False,
            created_by=op["sub"], created_at=now))
        db.commit()
    auth.audit(op["sub"], "token.create", tid, {"type": body.type})
    return {"id": tid, "token": token, "type": body.type,
            "expires_at": exp.isoformat() if exp else None, "max_uses": body.max_uses}


@app.get("/v1/tokens")
def list_tokens(_v: dict = Depends(auth.require_viewer)) -> list[dict]:
    with SessionLocal() as db:
        return [
            {"id": t.id, "type": t.type, "revoked": t.revoked, "max_uses": t.max_uses,
             "used_count": t.used_count, "created_by": t.created_by,
             "expires_at": t.expires_at.isoformat() if t.expires_at else None}
            for t in db.scalars(select(models.JoinToken)).all()
        ]


@app.post("/v1/tokens/{token_id}/revoke")
def revoke_token(token_id: str, op: dict = Depends(auth.require_operator)) -> dict:
    with SessionLocal() as db:
        t = db.get(models.JoinToken, token_id)
        if t is None:
            raise HTTPException(status_code=404, detail="unknown token")
        t.revoked = True
        db.commit()
    auth.audit(op["sub"], "token.revoke", token_id, None)
    return {"id": token_id, "revoked": True}


# ---- 노드 액션 (disable/enable/revoke) — 서버측 상태 게이트가 stream 차단 ----

def _set_node_status(node_id: str, status: str, actor: str, action: str) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        n = db.get(models.Node, node_id)
        if n is None:
            raise HTTPException(status_code=404, detail="unknown node")
        n.status = status
        if status == "revoked":
            for c in db.scalars(select(models.NodeCert).where(
                    models.NodeCert.node_id == node_id)).all():
                if c.revoked_at is None:
                    c.revoked_at = now
                    c.reason = action
        db.commit()
    auth.audit(actor, action, node_id, {"status": status})
    return {"node_id": node_id, "status": status}


@app.post("/v1/nodes/{node_id}/disable")
def disable_node(node_id: str, op: dict = Depends(auth.require_operator)) -> dict:
    return _set_node_status(node_id, "disabled", op["sub"], "node.disable")


@app.post("/v1/nodes/{node_id}/enable")
def enable_node(node_id: str, op: dict = Depends(auth.require_operator)) -> dict:
    return _set_node_status(node_id, "offline", op["sub"], "node.enable")


@app.post("/v1/nodes/{node_id}/revoke")
def revoke_node(node_id: str, op: dict = Depends(auth.require_operator)) -> dict:
    return _set_node_status(node_id, "revoked", op["sub"], "node.revoke")


# ---- WebSocket 라이브 로그 tail (07) ----

@app.websocket("/v1/jobs/{job_id}/logs/ws")
async def job_logs_ws(ws: WebSocket, job_id: str, token: str = Query(default="")) -> None:
    try:
        auth._claims("Bearer " + token)  # 쿼리 토큰(JWT) 인증
    except Exception:
        await ws.close(code=1008)
        return
    await ws.accept()
    sent = -1
    try:
        while True:
            with SessionLocal() as db:
                job = db.get(models.Job, job_id)
                if job is None:
                    await ws.close()
                    return
                phase = job.phase
                rows = db.scalars(select(models.JobLog).where(
                    models.JobLog.job_id == job_id, models.JobLog.offset > sent
                ).order_by(models.JobLog.offset)).all()
                data = [{"offset": r.offset, "stream": r.stream, "text": r.text} for r in rows]
            for d in data:
                await ws.send_json(d)
                sent = d["offset"]
            if phase in ("succeeded", "failed", "cancelled", "interrupted") and not data:
                await ws.send_json({"event": "end", "phase": phase})
                await ws.close()
                return
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


def _consume_join_token(db, token: str) -> bool:
    """부트스트랩 정적 토큰 또는 join_tokens 테이블 검증(+소진). caller가 commit."""
    if token and token == settings.join_token:
        return True
    if not token:
        return False
    th = hashlib.sha256(token.encode()).hexdigest()
    now = dt.datetime.now(dt.timezone.utc)
    jt = db.scalar(select(models.JoinToken).where(models.JoinToken.token_hash == th))
    if jt is None or jt.revoked:
        return False
    exp = jt.expires_at
    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=dt.timezone.utc)
        if exp < now:
            return False
    if jt.max_uses is not None and (jt.used_count or 0) >= jt.max_uses:
        return False
    jt.used_count = (jt.used_count or 0) + 1
    if jt.type == "one_time":
        jt.revoked = True
    return True


@app.post("/v1/enroll", response_model=EnrollResponse)
def enroll(req: EnrollRequest) -> EnrollResponse:
    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        if not _consume_join_token(db, req.join_token):
            raise HTTPException(status_code=401, detail="invalid join token")
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
        db.flush()  # Node 먼저 INSERT (Postgres FK: node_certs.node_id -> nodes.id)

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
        bundle_pubkey=_signer.pub_pem(),
    )


class BundleCreate(BaseModel):
    solution_id: str
    version: str
    manifest: dict  # {"runtimes": {"docker": {"requires": {...}, "actions": {"install": {"cmd": "..."}}}}}


@app.post("/v1/bundles")
def register_bundle(body: BundleCreate, op: dict = Depends(auth.require_operator)) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    bid = str(uuid.uuid4())
    with SessionLocal() as db:
        if db.scalar(select(models.Bundle).where(
                models.Bundle.solution_id == body.solution_id,
                models.Bundle.version == body.version)):
            raise HTTPException(status_code=409, detail="bundle version exists")
        for b in db.scalars(select(models.Bundle).where(
                models.Bundle.solution_id == body.solution_id)).all():
            b.is_latest = False
        db.add(models.Bundle(
            id=bid, solution_id=body.solution_id, version=body.version,
            is_latest=True, manifest=body.manifest, created_at=now))
        db.commit()
    auth.audit(op["sub"], "bundle.register", f"{body.solution_id}@{body.version}", {"id": bid})
    return {"id": bid, "solution_id": body.solution_id, "version": body.version}


@app.get("/v1/bundles")
def list_bundles(_v: dict = Depends(auth.require_viewer)) -> list[dict]:
    with SessionLocal() as db:
        return [
            {"id": b.id, "solution_id": b.solution_id, "version": b.version,
             "is_latest": b.is_latest, "runtimes": list((b.manifest or {}).get("runtimes", {}))}
            for b in db.scalars(select(models.Bundle)).all()
        ]


@app.put("/v1/bundles/{bundle_id}/artifact")
async def upload_artifact(bundle_id: str, request: Request,
                          op: dict = Depends(auth.require_operator)) -> dict:
    """번들 tarball(.tar.gz) 업로드 → CP 저장 + sha256 기록. (raw octet-stream body)"""
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty artifact")
    sha = hashlib.sha256(body).hexdigest()
    uri = storage.put_artifact(bundle_id, body)  # MinIO 또는 로컬 FS
    sig = _signer.sign(body)  # 번들 서명 (진위)
    with SessionLocal() as db:
        b = db.get(models.Bundle, bundle_id)
        if b is None:
            raise HTTPException(status_code=404, detail="unknown bundle")
        b.sha256 = sha
        b.storage_uri = uri
        b.cosign_bundle = sig
        b.size_bytes = len(body)
        db.commit()
    auth.audit(op["sub"], "bundle.artifact", bundle_id, {"sha256": sha, "size": len(body)})
    return {"id": bundle_id, "sha256": sha, "size_bytes": len(body)}


@app.get("/v1/bundles/{bundle_id}/blob")
def bundle_blob(bundle_id: str, t: str = Query(default="")):
    """번들 아티팩트 다운로드. 단기 다운로드 토큰(인증 stream으로 전달) 필요.
    무결성=sha256 + 진위=서명(둘 다 stream으로 전달). TODO: 클라이언트-cert mTLS 강화."""
    if not auth.verify_bundle_token(t, bundle_id):
        raise HTTPException(status_code=401, detail="invalid or missing download token")
    with SessionLocal() as db:
        b = db.get(models.Bundle, bundle_id)
        if b is None or not b.storage_uri:
            raise HTTPException(status_code=404, detail="no artifact")
        uri = b.storage_uri
    return Response(content=storage.get_artifact(uri), media_type="application/gzip")


class JobCreate(BaseModel):
    bundle: str | None = None  # "solution@version" (없으면 latest). None이면 raw exec(params.cmd)
    runtime: str = "docker"  # docker|k3s
    action: str = "status"  # install|uninstall|status...
    params: dict[str, str] = {}
    secret_refs: list[str] = []  # 비밀 참조(값 아님) — 에이전트가 로컬 store에서 해석
    force: bool = False  # Pre-flight 우회 (운영자 override, audit TODO)


def _preflight(requires: dict | None, runtime: str, node_id: str, db) -> str | None:
    """manifest.requires + 런타임 가용성 vs 노드 인벤토리. 부족하면 사유, 통과면 None."""
    need = requires or {}
    inv = db.get(models.NodeInventory, node_id)
    if inv is None or not inv.data:
        return "no inventory to pre-flight against"
    data = inv.data
    cpu = int((data.get("cpu") or {}).get("logical_cores", 0))
    mem_gb = int((data.get("memory") or {}).get("total_bytes", 0)) / (1024 ** 3)
    gpu = db.scalar(select(func.count()).select_from(models.NodeGPU)
                    .where(models.NodeGPU.node_id == node_id)) or 0
    if cpu < need.get("cpu_cores", 0):
        return f"cpu cores {cpu} < required {need['cpu_cores']}"
    if mem_gb + 0.05 < need.get("mem_gb", 0):
        return f"memory {mem_gb:.1f}GB < required {need['mem_gb']}GB"
    if gpu < need.get("gpu", 0):
        return f"gpu count {gpu} < required {need['gpu']}"
    # 런타임 가용성 게이트 — 인벤토리에 runtimes 필드가 있을 때만(구버전 에이전트 호환)
    runtimes = data.get("runtimes")
    if isinstance(runtimes, dict) and runtimes.get(runtime) is not True:
        return f"runtime {runtime!r} not available on node"
    return None


@app.post("/v1/nodes/{node_id}/jobs")
def create_job(node_id: str, body: JobCreate, op: dict = Depends(auth.require_operator)) -> dict:
    """Job 생성 → (번들 manifest 해석 + Pre-flight + 노드 락) → RunJob 명령 push."""
    now = dt.datetime.now(dt.timezone.utc)
    job_id = str(uuid.uuid4())
    command_id = str(uuid.uuid4())
    action = body.action
    params = dict(body.params)
    bundle_url = ""
    bundle_sha256 = ""
    bundle_sig = ""

    with SessionLocal() as db:
        node = db.get(models.Node, node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="unknown node")
        if node.status != "online":
            raise HTTPException(status_code=409, detail="node not online")

        # 번들 manifest 해석 (없으면 raw exec 호환)
        if body.bundle:
            sol, _, ver = body.bundle.partition("@")
            q = select(models.Bundle).where(models.Bundle.solution_id == sol)
            q = q.where(models.Bundle.version == ver) if ver else q.where(models.Bundle.is_latest.is_(True))
            bundle = db.scalar(q)
            if bundle is None:
                raise HTTPException(status_code=404, detail="unknown bundle")
            rt = (bundle.manifest or {}).get("runtimes", {}).get(body.runtime)
            if rt is None:
                raise HTTPException(status_code=400, detail=f"runtime {body.runtime} not in manifest")
            act = (rt.get("actions") or {}).get(action)
            if act is None or not ("cmd" in act or "entry" in act):
                raise HTTPException(status_code=400, detail=f"action {action} not in manifest")
            # Pre-flight 하드 게이트 (force로 우회 가능)
            if not body.force:
                err = _preflight(rt.get("requires"), body.runtime, node_id, db)
                if err:
                    raise HTTPException(status_code=412, detail=f"pre-flight failed: {err}")
            if "entry" in act:
                # 번들 아티팩트: 에이전트가 tarball fetch+sha256 후 entry 실행.
                if not bundle.sha256 or not bundle.storage_uri:
                    raise HTTPException(status_code=409, detail="bundle has no artifact uploaded")
                params["entry"] = act["entry"]
                token = auth.make_bundle_token(bundle.id)
                bundle_url = f"{settings.public_url}/v1/bundles/{bundle.id}/blob?t={token}"
                bundle_sha256 = bundle.sha256
                bundle_sig = bundle.cosign_bundle or ""
            else:
                params["cmd"] = act["cmd"]

        # 노드당 mutating Job 1개 락 (status 등 read-only는 병행 허용)
        if action != "status":
            busy = db.scalar(select(models.Job).where(
                models.Job.node_id == node_id,
                models.Job.phase.in_(["pending", "running"]),
                models.Job.kind != "status"))
            if busy is not None:
                raise HTTPException(status_code=409, detail=f"node busy with job {busy.id}")

        db.add(models.Job(
            id=job_id, node_id=node_id, command_id=command_id, kind=action,
            phase="pending", bundle_ref=body.bundle, params=params, created_at=now))
        db.flush()  # Job 먼저 INSERT (Postgres FK: commands.job_id -> jobs.id)
        db.add(models.Command(
            command_id=command_id, node_id=node_id, job_id=job_id, sent_at=now, attempt=1))
        db.commit()

    cmd = job_pb2.Command(
        command_id=command_id,
        run_job=job_pb2.RunJob(
            job_id=job_id, action=action, params=params, bundle_ref=body.bundle or "",
            bundle_url=bundle_url, bundle_sha256=bundle_sha256, bundle_sig=bundle_sig,
            secret_refs=body.secret_refs),
    )
    if not hub.send(node_id, stream_pb2.ServerMessage(command=cmd)):
        raise HTTPException(status_code=409, detail="node not connected to stream")
    auth.audit(op["sub"], "job.create", node_id,
               {"job_id": job_id, "bundle": body.bundle, "action": action})
    return {"job_id": job_id, "command_id": command_id, "phase": "pending"}


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, op: dict = Depends(auth.require_operator)) -> dict:
    with SessionLocal() as db:
        j = db.get(models.Job, job_id)
        if j is None:
            raise HTTPException(status_code=404, detail="unknown job")
        if j.phase not in ("pending", "running"):
            raise HTTPException(status_code=409, detail=f"job not cancellable (phase={j.phase})")
        node_id = j.node_id
    cmd = job_pb2.Command(command_id=str(uuid.uuid4()), cancel=job_pb2.CancelJob(job_id=job_id))
    if not hub.send(node_id, stream_pb2.ServerMessage(command=cmd)):
        raise HTTPException(status_code=409, detail="node not connected to stream")
    auth.audit(op["sub"], "job.cancel", job_id, {"node": node_id})
    return {"job_id": job_id, "status": "cancel requested"}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, _v: dict = Depends(auth.require_viewer)) -> dict:
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
def get_job_logs(job_id: str, _v: dict = Depends(auth.require_viewer)) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(models.JobLog).where(models.JobLog.job_id == job_id)
            .order_by(models.JobLog.offset)
        ).all()
        return [
            {"offset": r.offset, "stream": r.stream, "ts_unix_ms": r.ts_unix_ms, "text": r.text}
            for r in rows
        ]


class ClusterCreate(BaseModel):
    name: str
    runtime: str = "k3s"
    bundle: str  # "solution@version" (manifest runtime needs server+join actions)
    server: str  # server node_id
    workers: list[str] = []


@app.post("/v1/clusters")
def create_cluster(body: ClusterCreate, op: dict = Depends(auth.require_operator)) -> dict:
    try:
        cid = clusters.create_and_start(body.name, body.runtime, body.bundle, body.server, body.workers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    auth.audit(op["sub"], "cluster.create", cid,
               {"server": body.server, "workers": body.workers, "bundle": body.bundle})
    return {"cluster_id": cid, "status": "forming"}


@app.get("/v1/clusters")
def list_clusters(_v: dict = Depends(auth.require_viewer)) -> list[dict]:
    with SessionLocal() as db:
        return [
            {"id": c.id, "name": c.name, "runtime": c.runtime, "status": c.status,
             "server_url": c.server_url}
            for c in db.scalars(select(models.Cluster)).all()
        ]


@app.get("/v1/clusters/{cluster_id}")
def get_cluster(cluster_id: str, _v: dict = Depends(auth.require_viewer)) -> dict:
    with SessionLocal() as db:
        c = db.get(models.Cluster, cluster_id)
        if c is None:
            raise HTTPException(status_code=404, detail="unknown cluster")
        nodes = db.scalars(select(models.Node).where(models.Node.cluster_id == cluster_id)).all()
        return {
            "id": c.id, "name": c.name, "runtime": c.runtime, "status": c.status,
            "server_url": c.server_url, "plan": c.plan,
            "nodes": [{"node_id": n.id, "hostname": n.hostname, "role": n.cluster_role} for n in nodes],
        }


@app.get("/v1/nodes/{node_id}/inventory")
def node_inventory(node_id: str, _v: dict = Depends(auth.require_viewer)) -> dict:
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
def list_nodes(_v: dict = Depends(auth.require_viewer)) -> list[dict]:
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
