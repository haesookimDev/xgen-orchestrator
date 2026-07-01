"""번들 아티팩트 저장 — MinIO(설정 시) 또는 로컬 파일시스템 폴백.

CP가 프록시로 서빙(P1-1): put_artifact/get_artifact 만 노출. storage_uri는
로컬 경로 또는 minio://bucket/key. 설계: 06-catalog-bundles, 12-operational-policies.
"""
from __future__ import annotations

import io
import os

from .config import settings


def use_minio() -> bool:
    return bool(settings.minio_endpoint)


def _client():
    from minio import Minio
    return Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
                 secret_key=settings.minio_secret_key, secure=settings.minio_secure)


def put_artifact(bundle_id: str, data: bytes) -> str:
    if use_minio():
        c = _client()
        if not c.bucket_exists(settings.minio_bucket):
            c.make_bucket(settings.minio_bucket)
        key = f"{bundle_id}.tar.gz"
        c.put_object(settings.minio_bucket, key, io.BytesIO(data), length=len(data),
                     content_type="application/gzip")
        return f"minio://{settings.minio_bucket}/{key}"
    os.makedirs(settings.bundle_dir, exist_ok=True)
    path = os.path.join(settings.bundle_dir, f"{bundle_id}.tar.gz")
    with open(path, "wb") as f:
        f.write(data)
    return path


def get_artifact(storage_uri: str) -> bytes:
    if storage_uri.startswith("minio://"):
        bucket, _, key = storage_uri[len("minio://"):].partition("/")
        r = _client().get_object(bucket, key)
        try:
            return r.read()
        finally:
            r.close()
            r.release_conn()
    with open(storage_uri, "rb") as f:
        return f.read()
