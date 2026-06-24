# xgen-orchestrator 설계 문서 색인

솔루션(XGEN 2.0)을 여러 서버/VM에 설치·관리하고 하드웨어 자원·로그를 관측하는
컨트롤 플레인. Jenkins/ArgoCD 류 중앙 관제 + 노드별 CLI 에이전트. 이후 LLM Agentic 확장.

> **개발은 설계 완료 후 착수.** 모든 문서는 청사진 — 실제 코드는 아직 없음.
> 핵심 통찰: **xgen-orchestrator는 기존 [xgen-infra]의 설치 자산을 원격 구동·관측·제어하는
> 컨트롤 플레인** (패키징을 새로 만들지 않음).

## 문서

| # | 문서 | 내용 |
|---|------|------|
| 00 | [개요](00-overview.md) | 핵심 통찰 · Level-1 8대 결정 · 전체 아키텍처 |
| 01 | [레포 구조](01-repo-structure.md) | 모노레포 디렉토리 (proto/agent/control-plane/web/bundles) |
| 02 | [등록 & 보안](02-enrollment-security.md) | install.sh · join token · mTLS · 서버측 폐기 |
| 03 | [gRPC 프로토콜](03-grpc-protocol.md) | 단일 멀티플렉싱 stream · 메시지 스키마 · 신뢰성 |
| 04 | [데이터 모델](04-data-model.md) | PostgreSQL 스키마 · VM/Postgres 분담 |
| 05 | [Job 오케스트레이션](05-job-orchestration.md) | 설치 실행 · 번들 manifest · Pre-flight |
| 06 | [카탈로그 & 번들](06-catalog-bundles.md) | cosign 서명 · MinIO 저장 · 버전 |
| 07 | [운영자 접점](07-operator-surface.md) | Web UI + xgenctl · WebSocket · 메트릭 |
| 08 | [LLM Agentic Layer](08-llm-agentic-layer.md) | 트러블슈팅·로그분석·증설 (자리 예약) |

## 확정 결정 요약

| 영역 | 결정 |
|------|------|
| 통신 | Agent-pull, 단일 outbound mTLS gRPC stream |
| CP 배포 | 단일 바이너리 + docker-compose (CP + Postgres + VictoriaMetrics + Grafana + MinIO) |
| 규모 | 단일 조직, 수십 노드 |
| 언어 | Agent=Go, Control Plane=Python(FastAPI+grpcio), Web=Next.js |
| 레포 | 모노레포, proto 단일 진실원천(buf) |
| 번들 공급 | CP가 번들 푸시(비벤더, $XGEN_INFRA_PATH 빌드 시 참조), out-of-band mTLS HTTPS fetch |
| 등록 | join token(shared+one_time) · 자동승인 · 장기 cert · 서버측 상태 게이트 폐기 |
| 신뢰성 | 메트릭 drop / Job·로그 무손실, 명령 at-least-once+멱등 |
| 인벤토리 | 베어 노드 직접 수집, nvidia-smi→NVML 승격, 변경 이력 보관 |
| 설치 | host root 실행, install/uninstall/status, params=sites 디스크립터, Pre-flight 하드게이트 |
| 번들 | cosign(key) 서명, MinIO 저장, 명시 버전 핀+latest |
| 운영자 | Web UI+CLI 병행, WebSocket 라이브, Grafana+자체차트 |
| LLM | 제안만(read-only), 자리 예약, Claude API+로컬 vLLM 폴백 |

## 구현 슬라이스 순서 (설계 → 개발 전환 시)

1. **1차 — 관측**: 등록(02) → stream(03) → 데이터모델(04). install.sh → 인벤토리/메트릭/로그.
2. **2차 — 설치**: Job(05) + 번들(06). docker/k3s 원격 설치 + 라이브 로그.
3. **3차 — 운영자 표면**: Web UI/CLI(07).
4. **확장 — 지능화**: LLM(08).

[xgen-infra]: ../../../xgen-infra
