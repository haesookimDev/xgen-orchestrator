# xgen-orchestrator — 설계 개요 (Design Overview)

> 솔루션(XGEN 2.0)을 여러 서버/VM에 **설치·관리**하고 **하드웨어 자원·로그를 관측**하는
> 컨트롤 플레인 플랫폼. Jenkins/ArgoCD 류의 중앙 관제 + 노드별 CLI 에이전트 아키텍처.
> 이후 LLM Agentic 기능(트러블슈팅·로그분석·자동증설)으로 확장.

상태: **설계 진행 중** (Level-2 일부 확정). 개발은 설계 완료 후 착수.

---

## 0. 핵심 통찰 — xgen-infra 위의 컨트롤 플레인

`xgen-infra` 분석 결과, **솔루션 패키징·설치 자산은 이미 존재**한다. xgen-orchestrator는
패키징을 새로 만들지 않고, 기존 xgen-infra 산출물을 **원격에서 구동·관측·제어**한다.

| 필요 기능 | xgen-infra의 기존 자산 |
|-----------|------------------------|
| Docker 설치 | `compose/full-stack/`, `compose/trial/` |
| k3s/k8s 설치 | `k3s/helm-chart/` + ArgoCD App-of-Apps + Jenkins |
| 선언적 사이트 정의 | `sites/{site}.yaml` → `add-site.py --write` |
| 클러스터 부트스트랩 | `setup-k3s.sh`, `setup-k3s-ha.sh`(single/ha-2/ha), `setup-k3s-agent.sh` |
| 인프라 컴포넌트 | `deploy-infra.sh install --mode` (CNPG/Valkey/Qdrant/MinIO) |
| 폐쇄망(airgap) | `k3s/scripts/airgapped/` |
| GPU 포함 관측성 | Prometheus + Grafana + Loki + Tempo + **DCGM-exporter** |
| 에이전트 선례 | `xgen-edge-agent`, `xgen-kvm-host-agent` (호스트 레벨 데몬) |

→ 에이전트의 "Runtime Installer"는 위 스크립트/Helm/compose를 **노드에서 대신 실행하고
스트리밍**하는 실행기다.

---

## 1. 확정된 설계 결정 (Level-1 Lock)

| 영역 | 결정 | 근거 |
|------|------|------|
| 통신 모델 | **Agent-pull** (에이전트 outbound gRPC 양방향 stream) | NAT/방화벽/폐쇄망 뒤 노드도 인바운드 포트 0개 |
| Control Plane 배포 | **단일 바이너리 + docker-compose** | 설치·PoC 단순, 추후 HA 확장 |
| 규모/테넌시 | **단일 조직, 수십 노드**, 멀티테넌트 불필요 | 설계 단순 유지 |
| 추상화 수준 | **XGEN 전용 시작**, 솔루션 개념은 내부 추상화만 | 빠르고 현실적, 과설계 방지 |
| Agent 언어 | **Go** (단일 정적 바이너리) | install.sh 원클릭·크로스컴파일, k8s/gRPC 생태계 |
| Control Plane 언어 | **Python (FastAPI + grpcio)** | 기존 XGEN 스택·LLM 레이어와 직결 |
| 설치 로직 공급 | **Control Plane이 번들 푸시** | CP = 단일 진실원천, 폐쇄망·버전 일관성 |

---

## 2. 전체 아키텍처

```
┌──────── Control Plane (단일 바이너리 + docker-compose, Python/FastAPI) ────────┐
│  인증/인가 · Job 오케스트레이터 · 인벤토리/상태 DB(Postgres)                   │
│  메트릭 TSDB(VictoriaMetrics) · 로그 집계 · 솔루션 번들 저장소                 │
│  Web UI/대시보드 · [확장] LLM Agentic Layer                                    │
└───────────────────────────▲───────────────────────────────────────────────────┘
                            │ Agent-pull: 단일 outbound mTLS gRPC stream
                            │  ├ 상행: 인벤토리 · 메트릭(push) · 로그 · Job 결과
                            │  └ 하행: 명령(인벤토리 갱신 · Job 실행 · 번들 배포)
        ┌───────────────────┼───────────────────┐
   ┌────▼─────┐        ┌────▼─────┐        ┌────▼─────┐
   │Agent(Go) │        │Agent(Go) │        │Agent(Go) │  install.sh 원클릭 (systemd)
   │ 등록·인벤토리·메트릭(nvidia-smi/DCGM)·로그·Job 실행기                     │
   └──────────┘        └──────────┘        └──────────┘
        └──── xgen-infra 번들을 노드에서 구동 (Docker / k3s / k8s) ────┘
```

---

## 3. Level-2 상세 — MVP 첫 슬라이스: 등록 + HW 인벤토리 + 관측

검증 목표: **install.sh 한 줄 → 노드 자동 등록 → CPU/NVIDIA GPU 인벤토리가 대시보드에
→ 실시간 메트릭/로그 스트리밍.** (이 슬라이스에서 솔루션 설치는 아직 안 함.)

### 3.1 에이전트 생명주기 (등록)

```
운영자: curl -sSL https://<cp>/install.sh | sudo bash -s -- --token <BOOTSTRAP>
  ├ install.sh: OS/arch 감지 → CP에서 Go 에이전트 바이너리 다운로드
  ├ systemd 서비스 등록 (xgen-agent.service)
  └ 에이전트 부팅 → CP에 enroll(BOOTSTRAP token)
        └ CP: node_id 발급 + mTLS 클라이언트 인증서 발급
              └ 에이전트 → CP outbound 양방향 gRPC stream 수립 (이후 모든 통신)
```
- 단일 outbound mTLS gRPC 스트림이 명령·텔레메트리를 멀티플렉싱. 인바운드 포트 0개.

### 3.2 HW 인벤토리 모델 (★ 베어 노드에서 동작)

> 인벤토리는 k8s/DCGM 설치 **이전**의 베어 노드에서 수집돼야 하므로, 에이전트가
> **호스트에서 직접** 수집한다 (DCGM-exporter는 k8s 설치 후 승격).

- **정적**(등록 시 1회 + 변경 감지): CPU(모델/물리·논리코어/arch/소켓), Memory, Disk(마운트별
  용량·타입), OS/Kernel, 가상화 타입(bare/kvm/vm), 컨테이너 런타임 유무,
  **NVIDIA GPU**(모델/개수/VRAM/드라이버/CUDA/MIG) — `nvidia-smi`로 호스트 직접 조회
- **동적**(기본 15s): CPU/Mem/Disk 사용률·load, **GPU**(util/VRAM/온도/전력)

### 3.3 관측 데이터 흐름

```
에이전트 ──(gRPC stream, push)──▶ CP 수집기 ──▶ VictoriaMetrics ──▶ 대시보드/알림
로그: 설치/Job 로그 = 라인 단위 라이브 스트리밍 / 런타임 로그 = tail 요청 시
```

### 3.4 MVP 슬라이스 확정 결정

| 영역 | 결정 |
|------|------|
| 메트릭 전송 | **에이전트 push (gRPC stream)** — 인바운드 불필요, Agent-pull과 정합 |
| 메트릭 저장소 | **VictoriaMetrics 내장** (compose에 경량 TSDB 1개, PromQL/Grafana 호환) |
| GPU 수집 | **nvidia-smi 시작 → NVML/DCGM 승격** (수집기 인터페이스 추상화) |
| 상태/인벤토리 저장 | PostgreSQL |

---

## 4. 미설계 영역 (다음 라운드)

- A. 에이전트 등록/보안 상세 (bootstrap token 발급·만료, mTLS rotation, install.sh 구체)
- B. gRPC 프로토콜/API 계약 (메시지 스키마, 명령 종류, 스트림 재연결)
- C. 데이터 모델/DB 스키마 (nodes, inventory, jobs, metrics, logs)
- D. Job 오케스트레이션 엔진 (2번째 슬라이스: docker/k3s 설치 워크플로우)
- E. 솔루션 카탈로그/번들 구조 (CP가 푸시하는 번들 포맷·버전)
- F. Web UI/대시보드
- G. LLM Agentic Layer (확장: 트러블슈팅·로그분석·자동증설)
