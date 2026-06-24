# xgen-orchestrator — 위협 모델 (Threat Model)

> 추가 설계 ④. 새 결정 없음 — 02·05·06·10·11·12의 보안 결정을 자산·신뢰경계·STRIDE로
> 통합하고 잔여 위험을 명시.

## 자산 (Assets)

| 자산 | 위치 | 민감도 |
|------|------|--------|
| CA 개인키 | CP 파일(0600) | 최고 (전 노드 신원 위조 가능) |
| CP 마스터 키(KEK) | CP 파일/env | 최고 (전 시크릿 복호) |
| node-token·운영자 secret | secrets/cluster_secrets (암호화) | 높음 |
| 에이전트 client cert/key | 노드 `/etc/xgen-agent/`(0600) | 높음 (노드 가장) |
| join token | hash 저장 | 높음 (등록 자격) |
| cosign 서명키 | 빌드/CI (CP 아님) | 높음 (번들 위조) |
| job_logs·인벤토리 | Postgres/MinIO | 중 (인프라 정보) |

## 신뢰 경계 (Trust Boundaries)

```
[운영자] ──JWT/세션──▶ [CP HTTP/WS]      (P0-4: 인증·2-role·감사)
[노드 agent] ──mTLS gRPC──▶ [CP stream]  (cert 주체=node_id 매칭)
[agent] ──mTLS HTTPS──▶ [CP bundle proxy]──▶ [MinIO]  (P1-1)
[CP] ──외부──▶ [Claude API]  (P1-4: opt-in·redaction, 폐쇄망 차단)
[설치 시] install.sh/바이너리 다운로드  (P0-1: 신뢰 CA TLS + cosign)
```

## STRIDE 분석

| 위협 | 시나리오 | 완화 (설계 위치) |
|------|----------|------------------|
| **S**poofing (가짜 CP) | 노드가 공격자 CP에 등록 | 신뢰 CA TLS + 바이너리 cosign (P0-1) |
| **S**poofing (노드 가장) | 유출 토큰+machine-id로 노드 위조 | pending_reenroll+재등록토큰, cert SAN spiffe node_id 매칭 (P0-2) |
| **T**ampering (번들 변조) | 공급망에서 번들 교체 | sha256 + cosign 검증, CP proxy mTLS (P1-1, 06) |
| **T**ampering (명령 위조) | stream에 가짜 명령 주입 | mTLS 양방향, CP만 하행 명령 발행 |
| **R**epudiation | 고위험 작업 부인 | audit_log: token·bundle·job·node 작업 (P0-4) |
| **I**nfo disclosure (secret) | 로그/params로 secret 유출 | secret_refs(값 미전달), 로그 평문 금지 (P1-3, 12) |
| **I**nfo disclosure (LLM) | 외부 API로 인프라 정보 반출 | opt-in + redaction, 폐쇄망 로컬전용 (P1-4) |
| **D**oS | 대량 등록·로그 폭주 | join token TTL/횟수, 메트릭 drop, 보존정책 (12) |
| **E**levation (노드 폐기 우회) | 폐기된 노드 재접속 | 서버측 상태 게이트(연결 시 status 검사) (02) |
| **E**levation (권한 상승) | viewer가 operator 작업 | 2-role RBAC, UI·CLI·WS 공통 (P0-4) |

## 핵심 신뢰 가정

1. **CP 호스트 침해 = 전면 침해.** CA키·KEK가 CP 파일에 있으므로 CP 호스트 보안이 최상위 전제.
   → 후속: KMS/HSM, CP 호스트 강화.
2. **에이전트는 root.** 설치 스크립트가 호스트 root 실행(05)이므로, 악성 번들은 노드 장악 가능.
   → cosign 서명으로 번들 진위 보장이 필수 통제.
3. **join token 관리가 등록 보안의 핵심.** 자동 승인이라 토큰 유출=등록 가능. TTL·일회용·폐기로 제한.

## 잔여 위험 (수용/후속)

| 위험 | 현재 상태 | 대응 |
|------|-----------|------|
| CP 단일 호스트 키 집중 | 수용(PoC) | 후속 KMS/HSM, HA |
| 마스터 키 분실 시 복구 불가 | 수용 | 운영자 백업 의무(12) |
| 폐쇄망 vLLM 응답 신뢰 | 후속 | 품질 검증(08) |
| 공급망(빌드 환경) 침해 | 부분 | cosign 키 격리, 빌드 환경 강화(후속) |
| 내부자(operator) 오남용 | 부분 | audit_log 사후 추적 (예방은 후속) |

## 검증 체크리스트 (구현 시)
- [ ] cert 주체 spiffe node_id ↔ 메시지 node_id 매칭 강제
- [ ] secret 값이 job_logs·params·API 응답·UI에 절대 미노출
- [ ] 폐기/disabled/pending_reenroll 노드의 stream 연결 거부
- [ ] 번들 sha256+cosign 둘 다 실패 시 전개 차단
- [ ] 폐쇄망 모드에서 외부 LLM Provider 비활성 강제
- [ ] 고위험 작업 전부 audit_log 기록
