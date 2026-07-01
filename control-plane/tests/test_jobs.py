"""Job 생성 게이트 테스트 — Pre-flight 하드게이트 + 노드 락 + 번들 해석 (인증 포함).

에이전트(stream) 없이 검증: 게이트는 hub.send(노드 연결) 이전에 동작.
설계: docs/design/05-job-orchestration.md, 07(인증).
"""
import datetime as dt
import os


def _env(tmp_path):
    os.environ["XGEN_DATABASE_URL"] = f"sqlite:///{tmp_path}/cp.db"
    os.environ["XGEN_CA_DIR"] = str(tmp_path / "ca")
    os.environ["XGEN_JOIN_TOKEN"] = "test-token"
    os.environ["XGEN_ADMIN_USER"] = "admin"
    os.environ["XGEN_ADMIN_PASSWORD"] = "admin"


def _auth(client):
    r = client.post("/v1/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_job_gates(tmp_path):
    _env(tmp_path)
    from fastapi.testclient import TestClient

    from xgen_orchestrator.db import models
    from xgen_orchestrator.db.session import SessionLocal
    from xgen_orchestrator.http.app import app

    now = dt.datetime.now(dt.timezone.utc)
    with TestClient(app) as client:
        h = _auth(client)

        with SessionLocal() as db:
            db.add(models.Node(id="n1", machine_id="m1", hostname="h", status="online",
                               os="linux", arch="amd64", enrolled_at=now, last_seen_at=now))
            db.add(models.NodeInventory(node_id="n1", content_hash="x", collected_at=now,
                                        data={"cpu": {"logical_cores": 8},
                                              "memory": {"total_bytes": str(16 * 1024 ** 3)}}))
            db.commit()

        assert client.post("/v1/bundles", headers=h, json={
            "solution_id": "demo", "version": "1.0.0",
            "manifest": {"runtimes": {"docker": {"requires": {"cpu_cores": 4, "mem_gb": 8},
                                                 "actions": {"install": {"cmd": "echo hi"}}}}}}).status_code == 200
        assert client.post("/v1/bundles", headers=h, json={
            "solution_id": "heavy", "version": "1.0.0",
            "manifest": {"runtimes": {"docker": {"requires": {"cpu_cores": 999},
                                                 "actions": {"install": {"cmd": "echo hi"}}}}}}).status_code == 200

        # 인증 없이 변이 -> 401
        assert client.post("/v1/nodes/n1/jobs", json={"bundle": "demo@1.0.0", "action": "install"}).status_code == 401

        # 번들 미존재 -> 404
        assert client.post("/v1/nodes/n1/jobs", headers=h,
                           json={"bundle": "nope@1.0.0", "action": "install"}).status_code == 404
        # Pre-flight 실패 -> 412
        r = client.post("/v1/nodes/n1/jobs", headers=h, json={"bundle": "heavy@1.0.0", "action": "install"})
        assert r.status_code == 412 and "pre-flight" in r.json()["detail"]
        # 통과 -> 락/Job 생성 후 전송 실패(에이전트 미연결) 409
        r = client.post("/v1/nodes/n1/jobs", headers=h, json={"bundle": "demo@1.0.0", "action": "install"})
        assert r.status_code == 409 and "not connected" in r.json()["detail"]
        # 노드 락 -> busy 409
        r = client.post("/v1/nodes/n1/jobs", headers=h, json={"bundle": "demo@1.0.0", "action": "install"})
        assert r.status_code == 409 and "busy" in r.json()["detail"]


def test_runtime_preflight_gate(tmp_path):
    """런타임 가용성 게이트 — inventory.runtimes 로 요청 런타임 차단/허용 (15 §2)."""
    _env(tmp_path)
    from fastapi.testclient import TestClient

    from xgen_orchestrator.db import models
    from xgen_orchestrator.db.session import SessionLocal
    from xgen_orchestrator.http.app import app

    now = dt.datetime.now(dt.timezone.utc)
    with TestClient(app) as client:
        h = _auth(client)
        with SessionLocal() as db:
            db.add(models.Node(id="n2", machine_id="m2", hostname="h2", status="online",
                               os="linux", arch="amd64", enrolled_at=now, last_seen_at=now))
            # docker 사용 불가(false), k3s 가능(true) 인 노드
            db.add(models.NodeInventory(node_id="n2", content_hash="y", collected_at=now,
                                        data={"cpu": {"logical_cores": 8},
                                              "memory": {"total_bytes": str(16 * 1024 ** 3)},
                                              "runtimes": {"docker": False, "k3s": True}}))
            db.commit()
        assert client.post("/v1/bundles", headers=h, json={
            "solution_id": "svc", "version": "1.0.0",
            "manifest": {"runtimes": {
                "docker": {"requires": {}, "actions": {"install": {"cmd": "echo d"}}},
                "k3s": {"requires": {}, "actions": {"install": {"cmd": "echo k"}}}}}}).status_code == 200

        # docker 요청 → 런타임 불가로 412
        r = client.post("/v1/nodes/n2/jobs", headers=h,
                        json={"bundle": "svc@1.0.0", "runtime": "docker", "action": "install"})
        assert r.status_code == 412 and "runtime" in r.json()["detail"]
        # k3s 요청 → 게이트 통과 후 에이전트 미연결 409
        r = client.post("/v1/nodes/n2/jobs", headers=h,
                        json={"bundle": "svc@1.0.0", "runtime": "k3s", "action": "install"})
        assert r.status_code == 409 and "not connected" in r.json()["detail"]


def test_bootstrap_runtime_bypasses_gate(tmp_path):
    """bootstrap 런타임(k3s 설치)은 노드에 그 런타임이 없어도 게이트 통과 (15 §k3s)."""
    _env(tmp_path)
    from fastapi.testclient import TestClient

    from xgen_orchestrator.db import models
    from xgen_orchestrator.db.session import SessionLocal
    from xgen_orchestrator.http.app import app

    now = dt.datetime.now(dt.timezone.utc)
    with TestClient(app) as client:
        h = _auth(client)
        with SessionLocal() as db:
            db.add(models.Node(id="n3", machine_id="m3", hostname="h3", status="online",
                               os="linux", arch="amd64", enrolled_at=now, last_seen_at=now))
            # k3s 미설치 노드
            db.add(models.NodeInventory(node_id="n3", content_hash="z", collected_at=now,
                                        data={"cpu": {"logical_cores": 8},
                                              "memory": {"total_bytes": str(16 * 1024 ** 3)},
                                              "runtimes": {"k3s": False}}))
            db.commit()
        # bootstrap 런타임 번들
        assert client.post("/v1/bundles", headers=h, json={
            "solution_id": "boot", "version": "1.0.0",
            "manifest": {"runtimes": {"k3s": {"bootstrap": True, "requires": {},
                                              "actions": {"install": {"cmd": "echo k"}}}}}}).status_code == 200
        # k3s 미설치라도 bootstrap이라 게이트 통과 → 에이전트 미연결 409
        r = client.post("/v1/nodes/n3/jobs", headers=h,
                        json={"bundle": "boot@1.0.0", "runtime": "k3s", "action": "install"})
        assert r.status_code == 409 and "not connected" in r.json()["detail"]
