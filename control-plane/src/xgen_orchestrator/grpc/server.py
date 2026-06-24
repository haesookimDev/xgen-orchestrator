"""grpcio — AgentStream.Connect 종단 (에이전트 단일 bidi stream).

1차: Hello/Heartbeat 로 노드 online/last_seen 갱신. 인벤토리/메트릭/로그는 후속.
TODO: mTLS peer cert ↔ node_id 매칭 + nodes.status 게이트 (P0-2, 13-threat-model).
설계: docs/design/03-grpc-protocol.md.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from concurrent import futures

import grpc
from google.protobuf.json_format import MessageToDict
from sqlalchemy import select

# 생성된 protobuf는 `from orchestrator.v1 import ...` 형식이라 gen 루트를 sys.path에 추가.
_GEN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "gen"))
if _GEN not in sys.path:
    sys.path.insert(0, _GEN)

from orchestrator.v1 import stream_pb2, stream_pb2_grpc  # noqa: E402

from ..db import models  # noqa: E402
from ..db.session import SessionLocal  # noqa: E402


class AgentStreamServicer(stream_pb2_grpc.AgentStreamServicer):
    def Connect(self, request_iterator, context):
        node_id: str | None = None
        try:
            for msg in request_iterator:
                kind = msg.WhichOneof("payload")
                if kind == "hello":
                    node_id = msg.node_id
                    self._touch(node_id, online=True, agent_version=msg.hello.agent_version)
                    yield stream_pb2.ServerMessage(hello_ack=stream_pb2.HelloAck(resync_required=False))
                elif kind == "heartbeat":
                    self._touch(msg.node_id or node_id, online=True)
                elif kind == "inventory":
                    self._store_inventory(msg.node_id or node_id, msg.inventory)
                # metrics/logs/ack -> 후속
        finally:
            if node_id:
                self._touch(node_id, online=False)

    @staticmethod
    def _touch(node_id: str | None, online: bool = True, agent_version: str | None = None) -> None:
        if not node_id:
            return
        now = dt.datetime.now(dt.timezone.utc)
        with SessionLocal() as db:
            node = db.get(models.Node, node_id)
            if node is None:
                return  # 미등록 node_id (TODO: mTLS 게이트에서 거부)
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
                return  # 미등록 node_id
            cur = db.get(models.NodeInventory, node_id)
            if cur is not None and cur.content_hash == content_hash:
                return  # 변경 없음 -> 무저장
            if cur is None:
                db.add(models.NodeInventory(
                    node_id=node_id, content_hash=content_hash, data=data, collected_at=now))
            else:
                cur.content_hash = content_hash
                cur.data = data
                cur.collected_at = now
            db.add(models.NodeInventoryHistory(
                node_id=node_id, content_hash=content_hash, data=data, collected_at=now))
            # GPU 비정규화 재구성
            for g in db.scalars(select(models.NodeGPU).where(models.NodeGPU.node_id == node_id)).all():
                db.delete(g)
            for g in inv.gpus:
                db.add(models.NodeGPU(
                    node_id=node_id, index=g.index, model=g.model, vram_bytes=g.vram_bytes,
                    driver_version=g.driver_version, cuda_version=g.cuda_version,
                    mig_enabled=g.mig_enabled))
            db.commit()


def serve_grpc(host: str, port: int) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    stream_pb2_grpc.add_AgentStreamServicer_to_server(AgentStreamServicer(), server)
    server.add_insecure_port(f"{host}:{port}")  # TODO: mTLS creds
    server.start()
    return server
