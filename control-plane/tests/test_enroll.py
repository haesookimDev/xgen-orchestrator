"""등록 엔드포인트 테스트 — CSR 생성 → /v1/enroll → cert 체인·machine-id 검증.

설계: docs/design/02-enrollment-security.md. (Go agent enroll_test 의 Python CP 대응)
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


def test_enroll_signs_and_registers(tmp_path):
    # env를 import 전에 설정 (config가 import 시점에 읽음)
    os.environ["XGEN_DATABASE_URL"] = f"sqlite:///{tmp_path}/cp.db"
    os.environ["XGEN_CA_DIR"] = str(tmp_path / "ca")
    os.environ["XGEN_JOIN_TOKEN"] = "test-token"
    from fastapi.testclient import TestClient

    from xgen_orchestrator.http.app import app

    mid = "test-machine-0123456789"
    body = {
        "join_token": "test-token",
        "csr": _make_csr(mid),
        "node_info": {"hostname": "h1", "machine_id": mid, "os": "linux", "arch": "amd64"},
    }
    with TestClient(app) as client:
        r = client.post("/v1/enroll", json=body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["node_id"]

        cert = x509.load_pem_x509_certificate(data["client_cert"].encode())
        ca = x509.load_pem_x509_certificate(data["ca_bundle"].encode())
        # machine-id 보존
        sn = cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)[0].value
        assert sn == mid
        # CA로 체인 검증 (cryptography >= 40)
        cert.verify_directly_issued_by(ca)
        # SAN spiffe node_id
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        uris = san.get_values_for_type(x509.UniformResourceIdentifier)
        assert uris == [f"spiffe://xgen/node/{data['node_id']}"]

        # 노드 목록에 노출
        nodes = client.get("/v1/nodes").json()
        assert any(n["machine_id"] == mid for n in nodes)

        # 잘못된 토큰 거부
        bad = dict(body, join_token="wrong")
        assert client.post("/v1/enroll", json=bad).status_code == 401
