# xgen-orchestrator — 운영자 접점 (Web UI + CLI)

> Level-2 영역 F. `web/`, `xgenctl`(신규), `control-plane/.../http`.
> 백엔드 계약(A~E) 위의 운영자 표면. gRPC는 에이전트 전용, 운영자는 REST/WebSocket.

## 결정 (Lock)

| 항목 | 결정 | 함의 |
|------|------|------|
| 접점 | **Web UI(Next.js) + xgenctl(CLI) 병행** | 동일 CP REST API 소비, 자동화·시각화 모두 |
| 라이브 전달 | **WebSocket** | 양방향, 향후 터미널 제어 등 확장 여지 |
| 대시보드 | **Grafana 임베드 + 자체 차트 UI 둘 다** | VM을 두 경로가 공유 (아래) |

## 접점 구조

```
운영자
 ├─ Web UI (Next.js) ──┐
 │                      ├─→ CP REST API (FastAPI) ─→ 도메인 → DB / VM / MinIO
 └─ xgenctl (CLI) ─────┘     └─ WebSocket (라이브 로그/상태)
                             (에이전트는 gRPC stream 별도 경로)
```

## 화면/명령 맵 (도메인 그대로 표면화)

| 영역 | Web UI | xgenctl | API |
|------|--------|---------|-----|
| 노드 | 목록·상태 | `nodes ls` | `GET /v1/nodes` |
| 등록 | token 발급·install.sh 생성 | `token create` | `POST /v1/tokens` |
| 인벤토리 | 노드 상세 CPU/GPU/디스크 | `nodes describe <id>` | `GET /v1/nodes/{id}/inventory` |
| 메트릭 | 대시보드(Grafana+자체) | `metrics <id>` | 메트릭 프록시 / Grafana |
| 카탈로그 | 솔루션·버전 | `bundles ls` | `GET /v1/bundles` |
| 설치 | 설치 마법사 | `install <id> --runtime k3s ...` | `POST /v1/jobs` |
| Job | 목록·라이브 로그 | `jobs logs <job> -f` | `GET /v1/jobs` + WS |

## 라이브 로그/상태 (WebSocket)

```
에이전트 ─gRPC LogBatch/JobUpdate→ CP ─WebSocket→ Web UI / xgenctl (-f)
                                      └ job_logs(Postgres) 영속 (과거 조회는 REST)
```
- WebSocket = 라이브 tail. 과거 로그는 `GET /v1/jobs/{id}/logs` (Postgres).

## 메트릭 — 두 경로 공존

```
VictoriaMetrics
   ├─ Grafana(임베드) ── Web UI iframe/링크 : 강력한 기성 대시보드
   └─ CP 메트릭 프록시(PromQL) ── 자체 Next.js 차트 : 노드 카드 인라인 차트 등
```
- CP가 `GET /v1/metrics?query=<PromQL>` 프록시를 노출 → 자체 차트 UI가 VM 직접 노출 없이 소비.
- Grafana는 동일 VM 데이터소스. 두 경로가 같은 데이터를 공유.

## xgenctl 설계 메모
- CP REST를 소비하는 Go 단일 바이너리(에이전트와 코드 일부 공유 가능). 인증은 운영자 토큰/세션.
- `xgenctl install`이 설치 마법사의 CLI 등가물 — params를 sites 디스크립터로 직렬화(D와 동일 경로).

## 미해결/후속
- 운영자 인증·RBAC (지금은 단일 조직: 단순 관리자 인증부터)
- 설치 마법사 UX 상세 (런타임·노드·params 단계)
- WebSocket 인증·재연결
