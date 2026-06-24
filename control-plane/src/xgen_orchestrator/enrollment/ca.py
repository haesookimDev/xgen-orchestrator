"""내부 CA — 노드 client cert 서명 전용. 부팅 시 생성/로드(영속).

CSR을 서명해 SAN=spiffe://xgen/node/<node_id> 를 박은 client cert 발급 (P0-2).
개인키는 CP 파일(0600). 설계: docs/design/02-enrollment-security.md.
"""
from __future__ import annotations

import datetime as dt
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class InternalCA:
    def __init__(self, cert: x509.Certificate, key: ec.EllipticCurvePrivateKey, pem: bytes) -> None:
        self.cert = cert
        self.key = key
        self.pem = pem  # CA cert PEM (ca_bundle)

    @classmethod
    def load_or_create(cls, ca_dir: str) -> "InternalCA":
        os.makedirs(ca_dir, exist_ok=True)
        key_path = os.path.join(ca_dir, "ca.key")
        crt_path = os.path.join(ca_dir, "ca.crt")
        if os.path.exists(key_path) and os.path.exists(crt_path):
            with open(key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
            with open(crt_path, "rb") as f:
                pem = f.read()
            return cls(x509.load_pem_x509_certificate(pem), key, pem)

        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "xgen-ca")])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(hours=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False, content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False, key_cert_sign=True,
                    crl_sign=True, encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        pem = cert.public_bytes(serialization.Encoding.PEM)
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
        os.chmod(key_path, 0o600)
        with open(crt_path, "wb") as f:
            f.write(pem)
        return cls(cert, key, pem)

    def sign_csr(self, csr_pem: bytes, node_id: str) -> bytes:
        csr = x509.load_pem_x509_csr(csr_pem)
        if not csr.is_signature_valid:
            raise ValueError("invalid CSR signature")
        now = dt.datetime.now(dt.timezone.utc)
        spiffe = x509.UniformResourceIdentifier(f"spiffe://xgen/node/{node_id}")
        cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)  # CN=xgen-node, serialNumber=machine-id 유지
            .issuer_name(self.cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(hours=1))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([spiffe]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(self.key, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.PEM)
