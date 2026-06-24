# xgen-orchestrator — 레포 구조 (Repository Structure)

> [00-overview.md](00-overview.md)의 결정을 물리적 디렉토리로 구체화한 설계.
> 개발 착수 전 청사진 — 실제 파일은 아직 생성하지 않음.

## 구조 결정 (Lock)

| 항목 | 결정 | 근거 |
|------|------|------|
| 레포 형태 | **모노레포** (agent+CP+web+proto) | proto 계약 공유·일괄 버전, 단일 조직·수십 노드 규모 |
| 번들 소스 | **빌드 시 참조 (비벤더)** | 별도 xgen-infra 체크아웃을 빌드 시 참조해 번들 생성, 레포 결합도 최소 |
| 대시보드 | **Next.js** | 기존 XGEN frontend와 스택 일치, 인력·컴포넌트 재사용 |
| proto codegen | **buf** | protoc보다 단순, Go·Python 동시 생성 |

## 디렉토리 트리

```
xgen-orchestrator/
├── README.md
├── Makefile                        # proto gen · build-all · lint (전체 진입점)
├── docs/design/                    # 설계 문서
│
├── proto/                          # ★ gRPC 계약 = 단일 진실원천 (Go·Python 공유)
│   ├── orchestrator/v1/
│   │   ├── stream.proto            # 양방향 stream 봉투(envelope) + 멀티플렉싱
│   │   ├── enrollment.proto        # 등록/인증
│   │   ├── inventory.proto         # HW 인벤토리 스키마
│   │   ├── telemetry.proto         # 메트릭/로그 push
│   │   └── job.proto               # 명령·Job 실행/결과
│   ├── buf.yaml
│   └── buf.gen.yaml
│
├── agent/                          # ★ Go 단일 정적 바이너리 (xgen-agent)
│   ├── cmd/xgen-agent/main.go
│   ├── internal/
│   │   ├── enroll/                 # bootstrap token, mTLS 인증서 수령
│   │   ├── transport/              # gRPC stream client · 재연결 · 백오프
│   │   ├── inventory/              # CPU/mem/disk/os/가상화 수집
│   │   │   └── gpu/                # Collector 인터페이스: nvidiasmi.go → nvml.go
│   │   ├── metrics/                # 동적 메트릭 수집 → push
│   │   ├── logs/                   # 로그 tail·stream
│   │   ├── executor/               # Job 실행기 (번들 구동 + stdout 스트리밍)
│   │   └── bundle/                 # 번들 수신·검증(서명)·전개
│   ├── gen/                        # proto → Go 생성물
│   ├── go.mod
│   └── Makefile
│
├── control-plane/                  # ★ Python FastAPI + grpcio (단일 서비스)
│   ├── pyproject.toml
│   ├── src/xgen_orchestrator/
│   │   ├── http/                   # FastAPI: REST API + install.sh·바이너리 서빙
│   │   ├── grpc/                   # grpcio 서버 (에이전트 stream 종단)
│   │   │   └── handlers/           # enroll·inventory·telemetry·job 핸들러
│   │   ├── domain/                 # 노드·인벤토리·Job 도메인 로직 (순수)
│   │   ├── db/                     # SQLAlchemy 모델 + repository
│   │   ├── enrollment/             # 내부 CA: token 발급·mTLS 서명·회전
│   │   ├── metrics/                # VictoriaMetrics 쓰기/쿼리 클라이언트
│   │   ├── bundles/                # 번들 빌드·저장·버전·서명
│   │   ├── llm/                    # (확장) Agentic Layer — 자리만 예약
│   │   └── gen/                    # proto → Python 생성물
│   ├── alembic/                    # DB 마이그레이션
│   └── tests/
│
├── web/                            # 대시보드 (Next.js)
│   ├── app/                        # 노드·인벤토리·메트릭·로그·Job 화면
│   └── package.json
│
├── bundles/                        # ★ 솔루션 번들 정의 (비벤더 — 소스 미포함)
│   └── xgen/
│       ├── manifest.yaml           # 번들 메타: 런타임·버전·엔트리스크립트·요구자원
│       └── build.sh                # $XGEN_INFRA_PATH 체크아웃 참조 → 번들 tarball 생성
│
├── deploy/                         # ★ Control Plane 자체 배포
│   ├── docker-compose.yml          # CP + Postgres + VictoriaMetrics + Grafana + MinIO
│   ├── .env.example
│   └── install-cp.sh               # CP 원클릭 설치
│
└── scripts/
    └── install.sh                  # ★ 에이전트 원클릭 설치 (CP의 /install.sh로 서빙)
```

## 핵심 경계와 의도

- **`proto/`가 최상위 단일 진실원천** — Go 에이전트·Python CP가 동일 `.proto`에서 codegen.
  계약 불일치를 구조적으로 차단. `agent/gen/`·`control-plane/src/.../gen/`은 생성물.
- **`agent/internal/inventory/gpu/`의 Collector 인터페이스** — "nvidia-smi 시작 → NVML 승격"
  결정을 구조로 못박음. 구현 교체가 인터페이스 뒤에서만 발생.
- **CP는 단일 Python 서비스에 http + grpc 공존** — 단일 CP 서비스 컨테이너 + docker-compose 철학과 일치.
- **`bundles/`가 xgen-infra ↔ orchestrator 경계** — 비벤더. `build.sh`가 외부
  `$XGEN_INFRA_PATH`를 참조해 번들 tarball 생성, `manifest.yaml`이 런타임별 엔트리포인트 선언.
  → orchestrator 레포는 xgen-infra 소스를 품지 않아 결합도 최소.

## 번들 빌드 흐름 (비벤더)

```
외부 xgen-infra 체크아웃 ($XGEN_INFRA_PATH)
        │  bundles/xgen/build.sh
        ▼
번들 tarball (compose/k3s/scripts + manifest.yaml)  ──▶  CP bundles/ 저장소(버전·서명)
        │  Job 실행 시 CP → 에이전트 push
        ▼
에이전트 bundle/ 가 수신·검증·전개 → executor/ 가 구동
```
