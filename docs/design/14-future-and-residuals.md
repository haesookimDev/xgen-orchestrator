# xgen-orchestrator — 미래 확장 & 잔여 항목 (Future & Residuals)

> 추가 설계 ⑤⑥. CP HA 확장 경로 + 소규모 잔여 항목의 기본값. 새 슬라이스 아님 —
> 방향·기본값만 고정해 추후 흔들림 방지.

## ⑤ CP HA 확장 경로 (현재 단일 컨테이너 → 미래)

현재: 단일 CP 서비스 컨테이너 + docker-compose. HA는 후속이나 **stream 라우팅**이 핵심 난제.

```
난제: 에이전트는 단일 bidi stream으로 한 CP 인스턴스에 붙음.
      CP가 N개로 늘면 "노드 X에 명령"을 그 노드의 stream을 쥔 인스턴스로 라우팅해야 함.

확장 경로(미래):
  ① 상태 저장소 외재화: Postgres/VictoriaMetrics/MinIO를 각자 HA로 (이미 외부 컴포넌트)
  ② CP 인스턴스 = 무상태(stateless) + 수평 확장
  ③ stream 라우팅: 노드↔CP인스턴스 매핑을 공유 저장소/메시지버스(NATS 등)에 두고
     명령을 해당 인스턴스로 포워드 (또는 버스로 명령 발행)
  ④ LB는 에이전트 연결을 아무 인스턴스로 분배(sticky 불필요, 매핑은 ②③이 처리)
```
- 단일 조직·수십 노드(현 목표)에선 단일 CP로 충분. 위는 규모 확장 시 청사진.

## ⑥ 소규모 잔여 항목 (기본값 고정)

### status 액션 결과 스키마
RunJob `status`는 텍스트 로그가 아니라 **구조화 결과**를 반환:
```protobuf
message StatusReport {
  string runtime = 1;                 // docker|k3s
  string overall = 2;                 // healthy|degraded|down
  repeated ComponentStatus components = 3;
}
message ComponentStatus { string name=1; string state=2; string detail=3; }
```
→ UI가 컴포넌트별 health 표시, G의 진단 입력.

### proto 버전 호환
- `Hello.agent_version` 로 협상. CP는 **현재·직전 major(N, N-1)** 지원.
- 비호환 → HelloAck에 거부 사유 + 에이전트 자동 업그레이드 권고. install.sh 재실행으로 갱신.

### 운영자 인증 — OIDC (후속)
- MVP는 local admin+JWT(P0-4). OIDC는 `operators`를 IdP 클레임에 매핑하는 어댑터로 추가.
  role(viewer/operator)은 그대로 재사용.

### 설치 마법사 UX (요지)
- 단계: 노드/클러스터 선택 → 런타임 → 버전 → params(sites 디스크립터 폼) → Pre-flight 미리보기 → 실행.
- Pre-flight 결과(자원 충족/부족)를 실행 전 시각화. xgenctl은 동일 단계의 플래그/대화형 등가물.

### WebSocket 재연결
- 인증=JWT(공통). 끊김 시 클라이언트 지수 백오프 재연결 + 마지막 수신 지점부터 재구독(로그는
  job_logs offset 기준 재조회로 갭 보정).

### LLM 운영 (구현 시)
- 컨텍스트 윈도우: job_logs는 tail+요약, 메트릭은 집계치만 주입(토큰 절약).
- 비용·레이트리밋: site 단위 쿼터. 자율성 상향은 audit 동반 단계적 로드맵(08).

## 전체 미해결 잔여 (운영 단계로 이월)
- KMS/HSM 승격, CP HA 실구현, k8s(비-k3s) 클러스터 조율, HA k3s(server 3대) 조율,
  노드 장애 자동 reconcile, 마스터 키 자동 회전.
