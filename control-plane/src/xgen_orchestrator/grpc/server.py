"""grpcio — AgentStream.Connect 종단 (에이전트 단일 bidi stream).

상행: Hello/Heartbeat(online/last_seen), InventoryReport(저장), JobUpdate/LogBatch(Job 결과·로그).
하행: Command(RunJob 등) — HTTP에서 hub로 enqueue, 여기서 yield.
mTLS: peer cert spiffe node_id ↔ 메시지 node_id 매칭 + status 게이트 (P0-2, 13-threat-model).
설계: docs/design/03-grpc-protocol.md, 05-job-orchestration.md.
"""
from __future__ import annotations

import datetime as dt
import queue
import threading
import urllib.request
from concurrent import futures

import grpc
from cryptography import x509
from google.protobuf.json_format import MessageToDict
from sqlalchemy import select

from ..config import settings
from ..db import models
from ..db.session import SessionLocal
from ..pb import stream_pb2, stream_pb2_grpc
from .hub import hub

_DENY_STATUS = {"disabled", "revoked", "pending_reenroll"}
_SPIFFE_PREFIX = "spiffe://xgen/node/"
_PHASE = {0: "pending", 1: "running", 2: "succeeded", 3: "failed", 4: "cancelled", 5: "interrupted"}
_TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class AgentStreamServicer(stream_pb2_grpc.AgentStreamServicer):
    def Connect(self, request_iterator, context):
        peer = _peer_node_id(context)
        if not peer:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "no client cert spiffe id")
        with SessionLocal() as db:
            node = db.get(models.Node, peer)
            if node is None or node.status in _DENY_STATUS:
                context.abort(grpc.StatusCode.PERMISSION_DENIED, "node not allowed")

        outq = hub.register(peer)
        stop = threading.Event()

        def reader() -> None:
            try:
                for msg in request_iterator:
                    if msg.node_id and msg.node_id != peer:
                        break  # node_id 불일치 -> 종료
                    kind = msg.WhichOneof("payload")
                    if kind == "hello":
                        self._touch(peer, online=True, agent_version=msg.hello.agent_version)
                        self._recover(peer)  # 재연결=이전 실행중 Job은 죽음 -> interrupted
                        outq.put(stream_pb2.ServerMessage(
                            hello_ack=stream_pb2.HelloAck(resync_required=False)))
                    elif kind == "heartbeat":
                        self._touch(peer, online=True)
                    elif kind == "inventory":
                        self._store_inventory(peer, msg.inventory)
                    elif kind == "metrics":
                        self._write_metrics(msg.metrics)
                    elif kind == "job_update":
                        self._apply_job_update(msg.job_update)
                    elif kind == "logs":
                        self._store_logs(msg.logs)
            finally:
                stop.set()

        threading.Thread(target=reader, daemon=True).start()
        try:
            while not stop.is_set() and context.is_active():
                try:
                    yield outq.get(timeout=1.0)
                except queue.Empty:
                    continue
        finally:
            stop.set()
            hub.unregister(peer, outq)
            self._touch(peer, online=False)

    # ---- 상행 처리 ----

    @staticmethod
    def _touch(node_id: str | None, online: bool = True, agent_version: str | None = None) -> None:
        if not node_id:
            return
        now = dt.datetime.now(dt.timezone.utc)
        with SessionLocal() as db:
            node = db.get(models.Node, node_id)
            if node is None:
                return
            node.last_seen_at = now
            node.status = "online" if online else "offline"
            if agent_version:
                node.agent_version = agent_version
            db.commit()

    @staticmethod
    def _store_inventory(node_id: str | None, inv) -> None:
        if not node_id:
            return
        now = dt.datetime.now(dt.timezone.utc)
        content_hash = inv.content_hash
        data = MessageToDict(inv, preserving_proto_field_name=True)
        with SessionLocal() as db:
            if db.get(models.Node, node_id) is None:
                return
            cur = db.get(models.NodeInventory, node_id)
            if cur is not None and cur.content_hash == content_hash:
                return
            if cur is None:
                db.add(models.NodeInventory(
                    node_id=node_id, content_hash=content_hash, data=data, collected_at=now))
            else:
                cur.content_hash = content_hash
                cur.data = data
                cur.collected_at = now
            db.add(models.NodeInventoryHistory(
                node_id=node_id, content_hash=content_hash, data=data, collected_at=now))
            for g in db.scalars(select(models.NodeGPU).where(models.NodeGPU.node_id == node_id)).all():
                db.delete(g)
            for g in inv.gpus:
                db.add(models.NodeGPU(
                    node_id=node_id, index=g.index, model=g.model, vram_bytes=g.vram_bytes,
                    driver_version=g.driver_version, cuda_version=g.cuda_version,
                    mig_enabled=g.mig_enabled))
            db.commit()

    @staticmethod
    def _recover(node_id: str) -> None:
        # 재연결 시 이전 연결에서 실행 중이던 Job은 유실 -> interrupted (노드 락도 해제됨).
        now = dt.datetime.now(dt.timezone.utc)
        with SessionLocal() as db:
            stale = db.scalars(select(models.Job).where(
                models.Job.node_id == node_id,
                models.Job.phase.in_(["pending", "running"]))).all()
            for j in stale:
                j.phase = "interrupted"
                j.finished_at = now
            if stale:
                db.commit()

    @staticmethod
    def _apply_job_update(ju) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        with SessionLocal() as db:
            job = db.scalar(select(models.Job).where(models.Job.command_id == ju.command_id))
            if job is None and ju.job_id:
                job = db.get(models.Job, ju.job_id)
            if job is None:
                return
            if ju.phase_seq and job.phase_seq and ju.phase_seq < job.phase_seq:
                return  # 오래된 업데이트 무시 (idempotent)
            job.phase = _PHASE.get(ju.phase, "pending")
            job.exit_code = ju.exit_code
            job.phase_seq = ju.phase_seq
            if job.phase == "running" and job.started_at is None:
                job.started_at = now
            if job.phase in _TERMINAL and job.finished_at is None:
                job.finished_at = now
            db.commit()

    @staticmethod
    def _write_metrics(batch) -> None:
        # MetricPoint -> Prometheus exposition -> VictoriaMetrics import. best-effort(drop).
        if not settings.vm_url or not batch.points:
            return
        lines = []
        for p in batch.points:
            labels = ",".join(f'{k}="{v}"' for k, v in p.labels.items())
            lines.append(f"{p.name}{{{labels}}} {p.value} {p.ts_unix_ms}")
        body = "\n".join(lines).encode()
        try:
            req = urllib.request.Request(
                settings.vm_url + "/api/v1/import/prometheus", data=body, method="POST")
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            pass  # 메트릭 drop (TSDB 공백 허용)

    @staticmethod
    def _store_logs(logs) -> None:
        with SessionLocal() as db:
            for ln in logs.lines:
                db.add(models.JobLog(
                    job_id=logs.source, ts_unix_ms=ln.ts_unix_ms, source=logs.source,
                    stream=ln.stream, offset=ln.offset, text=ln.text))
            try:
                db.commit()  # (job_id,source,offset) UNIQUE 로 중복 차단
            except Exception:
                db.rollback()


def _peer_node_id(context) -> str | None:
    auth = context.auth_context() or {}
    pem = None
    for key in ("x509_pem_cert", b"x509_pem_cert"):
        vals = auth.get(key)
        if vals:
            pem = vals[0]
            break
    if not pem:
        return None
    if isinstance(pem, str):
        pem = pem.encode()
    try:
        cert = x509.load_pem_x509_certificate(pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for uri in san.get_values_for_type(x509.UniformResourceIdentifier):
            if uri.startswith(_SPIFFE_PREFIX):
                return uri[len(_SPIFFE_PREFIX):]
    except Exception:
        return None
    return None


def serve_grpc(host: str, port: int, ca, sans: list[str]) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    stream_pb2_grpc.add_AgentStreamServicer_to_server(AgentStreamServicer(), server)
    cert_pem, key_pem = ca.issue_server_cert(sans)
    creds = grpc.ssl_server_credentials(
        [(key_pem, cert_pem)], root_certificates=ca.pem, require_client_auth=True)
    server.add_secure_port(f"{host}:{port}", creds)
    server.start()
    return server
