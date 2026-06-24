# xgen-orchestrator — LLM Agentic Layer

> Level-2 영역 G (확장). `control-plane/.../llm/`.
> 새 인프라 아님 — 앞 슬라이스의 신호(인벤토리·로그·Job·메트릭)와 훅(Pre-flight·RunJob)
> 위에 얹는 추론 레이어.

## 결정 (Lock)

| 항목 | 결정 | 함의 |
|------|------|------|
| 자율성 수위 | **제안만 (read-only + 권고)** | 모든 행동은 운영자 승인 후. 가장 안전, 신뢰 구축 단계 |
| 구축 시점 | **자리만 예약, 나중 구현** | 경계·Tool 인터페이스만 설계, MVP/설치 슬라이스 안정 후 구현 |
| 배치·모델 | **외부 Claude API + 로컬 vLLM 폴백** | 폐쇄망은 xgen-model(로컬) 폴백, 기본은 Claude API |

## 공통 패턴 — 신호 위의 추론 루프

```
관측(이미 있음) → LLM 추론 → 제안(운영자에게) → [승인] → 기존 훅 실행 → 결과 관측
```
v1 자율성은 **"제안"에서 멈춤** — 실행은 항상 운영자.

| 기능 | 입력 신호(기존) | v1 산출(제안) |
|------|----------------|---------------|
| 설치 트러블슈팅 | job_logs(실패) + manifest + 인벤토리 | 원인 진단 + 수정/재시도 제안 |
| 로그 분석 | job_logs / 런타임 로그 + 메트릭 | 이상 요약·근본원인 + 알림 |
| 자원 자동 증설 | 인벤토리 + 메트릭 + Pre-flight 실패 | 증설/워커 조인 제안 (실행은 승인 후) |

## 아키텍처 (자리 예약)

```
┌─── LLM Agentic Layer (control-plane/.../llm/) ───┐
│  Context Builder → LLM(Claude API|로컬 vLLM) → Proposal │
│        ▲                                  │      │
│        └──── 읽기 Tool 호출 ◀─────────────┘      │
└──────────────────┬───────────────────────────────┘
                   ▼  (제안만 — 실행 Tool은 운영자 승인 게이트 뒤)
        기존 도메인 API (조회 read-only / [승인 후] RunJob)
```

- **Tool = 기존 도메인 기능 래핑.** v1은 읽기 Tool만 LLM에 노출
  (`get_node_inventory`, `get_job_logs`, `query_metrics`, `check_preflight`).
  행동 Tool(`run_job` 등)은 인터페이스만 정의하고 **승인 게이트 뒤**에 둠.
- **모델 추상화**: `LLMProvider` 인터페이스 → ClaudeProvider(기본) / LocalVLLMProvider(폐쇄망 폴백).
  폐쇄망은 이미 존재하는 xgen-model(vLLM) 재사용.

## 기존 설계와의 훅 (이미 준비됨)

| 훅 | 어디서 왔나 |
|----|-------------|
| Pre-flight 실패 → 증설 제안 | [05-job-orchestration.md](05-job-orchestration.md) Pre-flight |
| job_logs(Postgres) → 진단 입력 | [04-data-model.md](04-data-model.md) |
| 메트릭(VM) → 이상 탐지 입력 | [03-grpc-protocol.md](03-grpc-protocol.md) telemetry |
| RunJob → (승인 후) 행동 출력 | [05-job-orchestration.md](05-job-orchestration.md) |

## 자리 예약의 의미
- `control-plane/.../llm/` 디렉토리, `LLMProvider` 인터페이스, 읽기 Tool 시그니처만 v1에 둠.
- 실제 추론·프롬프트·에이전트 루프는 후속. 앞 슬라이스가 신호·훅을 이미 제공하므로 **추가
  인프라 없이** 얹을 수 있음.

## 미해결/후속 (구현 시)
- 프롬프트·컨텍스트 윈도우 관리, 비용·레이트리밋
- 자율성 상향(승인 후 자동실행 → 조건부 자율) 단계적 로드맵·감사 로그
- 폐쇄망 vLLM 품질 검증
