"""운영자 표면 테스트 — join token 관리 + 노드 액션 (07-operator-surface.md).

- token-create(one_time) 발급 → enroll 소비 → 재사용 거부
- token-list / token-revoke
- node disable/enable/revoke 상태 전이 + RBAC(operator) 게이트
"""
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _make_csr(machine_id: str) -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "xgen-node"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, machine_id),
        ]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def _enroll(client, token, mid):
    body = {
        "join_token": token,
        "csr": _make_csr(mid),
        "node_info": {"hostname": mid, "machine_id": mid, "os": "linux", "arch": "amd64"},
    }
    return client.post("/v1/enroll", json=body)


def test_operator_surface(tmp_path):
    os.environ["XGEN_DATABASE_URL"] = f"sqlite:///{tmp_path}/cp.db"
    os.environ["XGEN_CA_DIR"] = str(tmp_path / "ca")
    os.environ["XGEN_JOIN_TOKEN"] = ""  # static token 비활성 — 발급 토큰만 사용
    from fastapi.testclient import TestClient

    from xgen_orchestrator.http.app import app

    with TestClient(app) as client:
        op = client.post("/v1/login", json={"username": "admin", "password": "admin"}).json()["token"]
        H = {"Authorization": "Bearer " + op}

        # 인증 없이는 토큰 발급 거부
        assert client.post("/v1/tokens", json={"type": "one_time"}).status_code == 401

        # one_time 토큰 발급 → 평문 1회 반환
        created = client.post("/v1/tokens", json={"type": "one_time"}, headers=H)
        assert created.status_code == 200, created.text
        tok = created.json()["token"]
        assert tok and len(tok) >= 16

        # 목록에 노출 (평문 없이)
        lst = client.get("/v1/tokens", headers=H).json()
        assert any(t["type"] == "one_time" and t["used_count"] == 0 for t in lst)
        assert all("token" not in t for t in lst)

        # 첫 enroll 성공, 재사용은 거부 (one_time 소비)
        r1 = _enroll(client, tok, "node-a")
        assert r1.status_code == 200, r1.text
        assert _enroll(client, tok, "node-b").status_code == 401
        node_id = r1.json()["node_id"]

        # 노드 액션: disable → enable → revoke
        assert client.post(f"/v1/nodes/{node_id}/disable", headers=H).json()["status"] == "disabled"
        assert client.post(f"/v1/nodes/{node_id}/enable", headers=H).json()["status"] == "offline"
        assert client.post(f"/v1/nodes/{node_id}/revoke", headers=H).json()["status"] == "revoked"
        assert client.post(f"/v1/nodes/unknown/disable", headers=H).status_code == 404

        # token-revoke: shared 토큰 발급 후 폐기하면 enroll 실패
        shared = client.post("/v1/tokens", json={"type": "shared"}, headers=H).json()
        assert _enroll(client, shared["token"], "node-c").status_code == 200
        assert client.post(f"/v1/tokens/{shared['id']}/revoke", headers=H).json()["revoked"] is True
        assert _enroll(client, shared["token"], "node-d").status_code == 401

        # WebSocket 로그 tail: 인증 토큰(JWT) 쿼리 + 종료 이벤트
        import datetime as dt

        from xgen_orchestrator.db import models
        from xgen_orchestrator.db.session import SessionLocal

        now = dt.datetime.now(dt.timezone.utc)
        with SessionLocal() as db:
            db.add(models.Job(id="job-1", node_id=node_id, command_id="cmd-1",
                              kind="run_job", phase="succeeded", created_at=now))
            db.flush()
            db.add(models.JobLog(job_id="job-1", source="agent", stream="stdout",
                                 offset=0, text="hello", ts_unix_ms=0))
            db.commit()

        # 무인증 WS는 즉시 닫힘
        import pytest
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/jobs/job-1/logs/ws") as ws:
                ws.receive_json()

        # 인증 WS는 로그 라인 + end 이벤트 수신
        with client.websocket_connect(f"/v1/jobs/job-1/logs/ws?token={op}") as ws:
            line = ws.receive_json()
            assert line["text"] == "hello"
            end = ws.receive_json()
            assert end["event"] == "end" and end["phase"] == "succeeded"
