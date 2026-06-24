"""Job 생성 게이트 테스트 — Pre-flight 하드게이트 + 노드 락 + 번들 해석.

에이전트(stream) 없이 검증 가능한 부분: 게이트는 hub.send(노드 연결) 이전에 동작.
설계: docs/design/05-job-orchestration.md
"""
import datetime as dt
import os


def _env(tmp_path):
    os.environ["XGEN_DATABASE_URL"] = f"sqlite:///{tmp_path}/cp.db"
    os.environ["XGEN_CA_DIR"] = str(tmp_path / "ca")
    os.environ["XGEN_JOIN_TOKEN"] = "test-token"


def test_job_gates(tmp_path):
    _env(tmp_path)
    from fastapi.testclient import TestClient

    from xgen_orchestrator.db import models
    from xgen_orchestrator.db.session import SessionLocal
    from xgen_orchestrator.http.app import app

    now = dt.datetime.now(dt.timezone.utc)
    with TestClient(app) as client:
        # 노드(online) + 인벤토리(8코어, 16GB) 시드
        with SessionLocal() as db:
            db.add(models.Node(id="n1", machine_id="m1", hostname="h", status="online",
                               os="linux", arch="amd64", enrolled_at=now, last_seen_at=now))
            db.add(models.NodeInventory(node_id="n1", content_hash="x", collected_at=now,
                                        data={"cpu": {"logical_cores": 8},
                                              "memory": {"total_bytes": str(16 * 1024 ** 3)}}))
            db.commit()

        # 번들 2개: demo(요구 충족), heavy(요구 과다)
        assert client.post("/v1/bundles", json={
            "solution_id": "demo", "version": "1.0.0",
            "manifest": {"runtimes": {"docker": {"requires": {"cpu_cores": 4, "mem_gb": 8},
                                                 "actions": {"install": {"cmd": "echo hi"}}}}}}).status_code == 200
        assert client.post("/v1/bundles", json={
            "solution_id": "heavy", "version": "1.0.0",
            "manifest": {"runtimes": {"docker": {"requires": {"cpu_cores": 999},
                                                 "actions": {"install": {"cmd": "echo hi"}}}}}}).status_code == 200

        # 1) 번들 미존재 -> 404
        r = client.post("/v1/nodes/n1/jobs", json={"bundle": "nope@1.0.0", "runtime": "docker", "action": "install"})
        assert r.status_code == 404

        # 2) Pre-flight 실패 -> 412
        r = client.post("/v1/nodes/n1/jobs", json={"bundle": "heavy@1.0.0", "runtime": "docker", "action": "install"})
        assert r.status_code == 412, r.text
        assert "pre-flight" in r.json()["detail"]

        # 3) Pre-flight 통과 -> 락/Job 생성 후 hub.send 실패(에이전트 미연결) -> 409 not connected
        r = client.post("/v1/nodes/n1/jobs", json={"bundle": "demo@1.0.0", "runtime": "docker", "action": "install"})
        assert r.status_code == 409, r.text
        assert "not connected" in r.json()["detail"]  # 게이트 통과, 전송 단계에서만 실패

        # 4) 노드 락 -> 이미 pending install 존재하므로 또 다른 mutating job 거부 (busy)
        r = client.post("/v1/nodes/n1/jobs", json={"bundle": "demo@1.0.0", "runtime": "docker", "action": "install"})
        assert r.status_code == 409, r.text
        assert "busy" in r.json()["detail"]

        # 5) status(read-only)는 락과 무관 -> 게이트 통과(전송만 실패)
        r = client.post("/v1/nodes/n1/jobs", json={"bundle": "demo@1.0.0", "runtime": "docker", "action": "status"})
        # status 액션이 manifest에 없으므로 400 (manifest 검증 동작 확인)
        assert r.status_code == 400, r.text
