"""생성된 protobuf 모듈 re-export.

buf 산출물은 `from orchestrator.v1 import ...` 형식이라 gen 루트를 sys.path에 올린다.
http·grpc 양쪽에서 `from ..pb import stream_pb2, job_pb2` 로 사용.
"""
import os
import sys

_GEN = os.path.abspath(os.path.join(os.path.dirname(__file__), "gen"))
if _GEN not in sys.path:
    sys.path.insert(0, _GEN)

from orchestrator.v1 import (  # noqa: E402,F401
    inventory_pb2,
    job_pb2,
    stream_pb2,
    stream_pb2_grpc,
    telemetry_pb2,
)
