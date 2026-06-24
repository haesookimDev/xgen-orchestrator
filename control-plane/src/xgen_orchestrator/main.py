"""CP 진입점 — 단일 서비스 컨테이너에 HTTP(FastAPI) + gRPC(grpcio) 공존.

설계: docs/design/01-repo-structure.md (CP는 단일 Python 서비스에 http+grpc 공존).
"""
import asyncio


async def serve() -> None:
    # TODO:
    #   - DB 초기화/마이그레이션 확인 (alembic)
    #   - 내부 CA 로드/생성, 마스터 키 로드 (파일/env)
    #   - gRPC 서버 기동 (AgentStream, mTLS)
    #   - uvicorn으로 FastAPI 기동
    #   둘을 같은 프로세스에서 동시 실행
    raise NotImplementedError


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
