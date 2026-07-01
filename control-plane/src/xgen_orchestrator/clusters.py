"""멀티노드 클러스터 설치 조율 (설계 11-cluster-topology).

흐름: server 노드 install(server 액션) → 로그에서 join 토큰/URL 수확 →
cluster_secrets 저장 → worker 노드들에 join 액션(토큰/URL 주입) → 전부 성공 시 ready.

1차: manifest 액션은 cmd 기반(번들 아티팩트 fetch는 후속). 토큰은 서버 job 로그의
마커(XGEN_CLUSTER_TOKEN=, XGEN_SERVER_URL=)로 중개(node-token 브로커의 데모).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from .db import models
from .db.session import SessionLocal
from .grpc.hub import hub
from .pb import job_pb2, stream_pb2

TOKEN_MARK = "XGEN_CLUSTER_TOKEN="
URL_MARK = "XGEN_SERVER_URL="


def _dispatch(db, node_id: str, action: str, cmd: str, cluster_id: str, role: str) -> str:
    """클러스터 내부 Job 1건 디스패치 (Job+Command 생성 + stream push). job_id 반환."""
    now = dt.datetime.now(dt.timezone.utc)
    job_id = str(uuid.uuid4())
    command_id = str(uuid.uuid4())
    params = {"cmd": cmd, "_cluster_id": cluster_id, "_cluster_role": role}
    db.add(models.Job(id=job_id, node_id=node_id, command_id=command_id, kind=action,
                      phase="pending", params=params, created_at=now))
    db.add(models.Command(command_id=command_id, node_id=node_id, job_id=job_id,
                          sent_at=now, attempt=1))
    db.commit()
    cmd_pb = job_pb2.Command(command_id=command_id,
                             run_job=job_pb2.RunJob(job_id=job_id, action=action, params=params))
    hub.send(node_id, stream_pb2.ServerMessage(command=cmd_pb))
    return job_id


def _manifest_actions(db, bundle_ref: str, runtime: str) -> dict:
    sol, _, ver = bundle_ref.partition("@")
    q = select(models.Bundle).where(models.Bundle.solution_id == sol)
    q = q.where(models.Bundle.version == ver) if ver else q.where(models.Bundle.is_latest.is_(True))
    b = db.scalar(q)
    if b is None:
        raise ValueError("unknown bundle")
    rt = (b.manifest or {}).get("runtimes", {}).get(runtime)
    if rt is None:
        raise ValueError(f"runtime {runtime} not in manifest")
    return rt.get("actions") or {}


def create_and_start(name: str, runtime: str, bundle_ref: str,
                     server_node: str, worker_nodes: list[str]) -> str:
    """클러스터 생성 + server install 시작."""
    now = dt.datetime.now(dt.timezone.utc)
    cluster_id = str(uuid.uuid4())
    with SessionLocal() as db:
        for nid in [server_node, *worker_nodes]:
            n = db.get(models.Node, nid)
            if n is None or n.status != "online":
                raise ValueError(f"node {nid} not online")
        actions = _manifest_actions(db, bundle_ref, runtime)
        if "server" not in actions or "join" not in actions:
            raise ValueError("manifest runtime needs 'server' and 'join' actions")

        db.add(models.Cluster(
            id=cluster_id, name=name, runtime=runtime,
            solution_id=bundle_ref.partition("@")[0], version=bundle_ref.partition("@")[2],
            status="forming", created_at=now,
            plan={"bundle": bundle_ref, "runtime": runtime, "server_node": server_node,
                  "workers": worker_nodes, "server_action": actions["server"]["cmd"],
                  "join_action": actions["join"]["cmd"], "worker_jobs": {}}))
        # 노드 역할 지정
        db.get(models.Node, server_node).cluster_id = cluster_id
        db.get(models.Node, server_node).cluster_role = "server"
        for nid in worker_nodes:
            db.get(models.Node, nid).cluster_id = cluster_id
            db.get(models.Node, nid).cluster_role = "worker"
        db.commit()

        sjob = _dispatch(db, server_node, "server", actions["server"]["cmd"], cluster_id, "server")
        c = db.get(models.Cluster, cluster_id)
        plan = dict(c.plan)
        plan["server_job"] = sjob
        c.plan = plan
        db.commit()
    return cluster_id


def advance(job_id: str) -> None:
    """클러스터에 속한 Job이 종료됐을 때 호출 (grpc _apply_job_update에서)."""
    with SessionLocal() as db:
        job = db.get(models.Job, job_id)
        if job is None or not job.params:
            return
        cluster_id = job.params.get("_cluster_id")
        role = job.params.get("_cluster_role")
        if not cluster_id:
            return
        c = db.get(models.Cluster, cluster_id)
        if c is None:
            return
        plan = dict(c.plan or {})

        if role == "server":
            if job.phase != "succeeded":
                c.status = "degraded"
                db.commit()
                return
            token, url = _harvest(db, job_id)
            if token:
                db.add(models.Secret(ref=f"cluster:{cluster_id}:k3s_token",
                                     scope=f"cluster:{cluster_id}", value_enc=token.encode()))
            c.server_url = url or ""
            # worker join 디스패치
            wjobs = {}
            for nid in plan.get("workers", []):
                # export로 주입 → join 스크립트/명령 전체에서 $SERVER_URL/$TOKEN 사용 가능.
                cmd = f'export SERVER_URL="{url or ""}"; export TOKEN="{token or ""}"; ' + plan["join_action"]
                wjobs[nid] = _dispatch(db, nid, "join", cmd, cluster_id, "worker")
            plan["worker_jobs"] = wjobs
            c.plan = plan
            if not wjobs:
                c.status = "ready"
            db.commit()

        elif role == "worker":
            wjobs = plan.get("worker_jobs", {})
            phases = []
            for wid in wjobs.values():
                wj = db.get(models.Job, wid)
                phases.append(wj.phase if wj else "pending")
            if any(p == "failed" for p in phases):
                c.status = "degraded"
            elif all(p == "succeeded" for p in phases) and phases:
                c.status = "ready"
            db.commit()


def _harvest(db, server_job_id: str) -> tuple[str | None, str | None]:
    token = url = None
    rows = db.scalars(select(models.JobLog).where(models.JobLog.job_id == server_job_id)).all()
    for r in rows:
        t = (r.text or "").strip()
        if t.startswith(TOKEN_MARK):
            token = t[len(TOKEN_MARK):]
        elif t.startswith(URL_MARK):
            url = t[len(URL_MARK):]
    return token, url
