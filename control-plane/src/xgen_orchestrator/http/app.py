"""FastAPI — 운영자 REST + 에이전트 등록(REST) + install.sh/바이너리/번들 서빙.

gRPC(에이전트 stream)는 grpc/server.py가 담당. 운영자 인증=JWT 2-role (P0-4).
설계: docs/design/02-enrollment-security.md, 06, 07.
"""
from fastapi import FastAPI

app = FastAPI(title="xgen-orchestrator control-plane")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/install.sh")
def install_sh():
    """에이전트 원클릭 설치 스크립트 서빙. 신뢰 CA TLS로 제공 (P0-1)."""
    # TODO: scripts/install.sh 를 server 주소/파라미터 치환해 반환
    raise NotImplementedError


@app.post("/v1/enroll")
def enroll():
    """등록(REST). join_token 검증 -> machine-id 신규면 자동승인, 중복이면 pending_reenroll.
    내부 CA가 CSR 서명(SAN=spiffe node_id) -> {node_id, client_cert, ca_bundle}. (P0-2)"""
    # TODO: 구현
    raise NotImplementedError


@app.get("/v1/nodes")
def list_nodes():
    """노드 목록·상태 (viewer)."""
    # TODO
    raise NotImplementedError


@app.get("/v1/nodes/{node_id}/inventory")
def node_inventory(node_id: str):
    """노드 인벤토리 상세 (CPU/GPU/디스크)."""
    # TODO
    raise NotImplementedError


@app.get("/v1/bundles/{bundle_id}/blob")
def bundle_proxy(bundle_id: str):
    """번들 다운로드 — CP bundle proxy(mTLS) -> MinIO (P1-1). presigned 직접 아님."""
    # TODO
    raise NotImplementedError
