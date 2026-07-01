"""번들 서명 — 아티팩트를 CP 개인키로 ECDSA 서명, 에이전트가 공개키로 진위 검증.

설계 06(cosign key 모드)의 검증 가능한 등가 구현: ECDSA-P256/SHA256 detached 서명(base64).
공개키(PEM)는 등록 응답으로 에이전트에 배포. 실 cosign 툴체인 연동은 후속.
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


class BundleSigner:
    def __init__(self, key: ec.EllipticCurvePrivateKey, pub_pem: bytes) -> None:
        self.key = key
        self._pub_pem = pub_pem

    @classmethod
    def load_or_create(cls, dir_: str) -> "BundleSigner":
        os.makedirs(dir_, exist_ok=True)
        key_path = os.path.join(dir_, "bundle-sign.key")
        pub_path = os.path.join(dir_, "bundle-sign.pub")
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
            with open(pub_path, "rb") as f:
                return cls(key, f.read())
        key = ec.generate_private_key(ec.SECP256R1())
        pub_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
        os.chmod(key_path, 0o600)
        with open(pub_path, "wb") as f:
            f.write(pub_pem)
        return cls(key, pub_pem)

    def sign(self, data: bytes) -> str:
        return base64.b64encode(self.key.sign(data, ec.ECDSA(hashes.SHA256()))).decode()

    def pub_pem(self) -> str:
        return self._pub_pem.decode()
