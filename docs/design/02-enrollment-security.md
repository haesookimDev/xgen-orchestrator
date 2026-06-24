# xgen-orchestrator — 에이전트 등록 & 보안 (Enrollment & Security)

> Level-2 영역 A. `agent/internal/enroll/` ↔ `control-plane/.../enrollment/`.
> [00-overview.md](00-overview.md) · [01-repo-structure.md](01-repo-structure.md) 기반.

## 설계 원칙

1. **개인키는 노드를 떠나지 않는다** — 에이전트가 로컬에서 키쌍 생성, CSR만 전송. CP는 서명만.
2. **TOFU(첫 연결 맹신) 차단** — install.sh에 CP의 CA 지문(fingerprint)을 핀으로 박아 배포.
3. **토큰 유출의 폭발 반경 최소화** — bootstrap 토큰은 단기·제한적, 영구 신뢰는 mTLS 인증서로 승격.
4. **모든 후속 통신은 mTLS** — 등록은 한 번, 이후 stream은 클라이언트 인증서로만.

## 정책 결정 (Lock)

| 정책 | 결정 | 함의 |
|------|------|------|
| Join token | **TTL 공유 토큰 + 일회용 per-node 둘 다 지원** | 기본은 TTL 공유(대량 등록), 민감 노드는 일회용 |
| 노드 승인 | **신규 토큰 유효 시 자동 승인** | 마찰 없음. **join token이 곧 신뢰 경계** → 토큰 관리가 핵심 |
| Client cert 수명 | **장기 cert (예 1년), MVP는 rotation 없음** | 폐기는 서버측 상태 게이트로. rotation은 후속 운영강화 |
| **부트스트랩 신뢰** (P0-1) | **신뢰 CA TLS + 바이너리 cosign 서명** | install.sh 다운로드 신뢰와 바이너리 신뢰를 분리 |
| **재등록** (P0-2) | **machine-id 중복 → pending_reenroll + 재등록 토큰** | 자동 update 금지(탈취 경로 차단), 주체-node_id 매칭 |

> 상세 근거: [10-review-resolutions.md](10-review-resolutions.md) P0-1·P0-2.

## 등록 플로우

```
[운영자] CP UI/CLI 에서 join token 발급 (TTL·사용횟수 제한, 또는 일회용)
   └ 토큰 + CP 주소가 박힌 install.sh 한 줄 생성
        ▼
[노드] curl -sSL https://<cp>/install.sh | sudo bash -s -- \
          --token <JOIN> --server https://<cp>
  ├ ① install.sh 다운로드: CP가 신뢰 CA(공인/사내) 인증서로 서빙 → curl TLS 정상 검증
  │     (TOFU 아님. 사내 CA 없으면 curl --pinnedpubkey 또는 별도 채널+checksum)
  ├ ② 에이전트 바이너리 다운로드 → cosign 서명 검증(공개키 스크립트 내장)
  ├ systemd 유닛 설치 (xgen-agent.service), /etc/xgen-agent/ (0700)
  └ 에이전트 부팅
        ├ 1. 로컬 키쌍 생성 → CSR (CN=node, machine-id 포함)
        │     private key = /etc/xgen-agent/agent.key (0600), 노드 밖으로 안 나감
        ├ 2. POST /v1/enroll { join_token, csr, node_info(hostname,machine-id,os,arch) }
        │   [CP] join_token 검증(만료·횟수·폐기)
        │        → machine-id 신규? 자동 승인 : 중복이면 거부→pending_reenroll(재등록 토큰 요구)
        │        → 내부 CA가 CSR 서명, SAN에 spiffe://xgen/node/<node_id>
        │        → 반환 { node_id, client_cert(1y), ca_bundle }
        ├ 3. cert 저장 → 이후 mTLS gRPC stream. CP는 인증서 주체 ↔ 메시지 node_id 매칭
        └ (일회용 토큰은 사용 즉시 소진, TTL 토큰은 used_count++)
```

## 부트스트랩 신뢰 — 두 신뢰를 분리 (P0-1)

| 단계 | 신뢰 수단 |
|------|-----------|
| install.sh 다운로드 | CP의 **신뢰 CA 인증서**로 최초 curl TLS 정상 검증 (대안: `--pinnedpubkey`/별도 채널) |
| 에이전트 바이너리 | **cosign 서명 검증** (무결성+진위) |
| 등록 TLS | 동일 신뢰 CA. mTLS 클라이언트 핀은 보조 |

## 재등록 — 노드 탈취 경로 차단 (P0-2)

```
machine-id 중복 등록 시도
  └ 자동 update 금지 → 노드 status=pending_reenroll
       └ 운영자 발급 re-enroll token 제시해야 새 cert 발급 (복제 VM·재설치 정상 시나리오 포함)
인증서 주체: SAN=spiffe://xgen/node/<node_id> → stream 수립 시 메시지 node_id 와 강제 매칭(불일치 거부)
cert 발급/폐기 이력: node_certs 테이블에 감사 보존 (04 참조)
```

## 신뢰 계층

| 계층 | 수단 | 역할 |
|------|------|------|
| CP 신뢰 | **신뢰 CA TLS** + 바이너리 cosign 서명 | 노드가 가짜 CP/변조 바이너리에 등록 차단 |
| 1회성 인입 | **join token** (TTL+횟수 / 일회용) | 등록 자격 증명, 유출 시 폭발 반경 제한 |
| 영구 신뢰 | **mTLS client cert** (1년) | 등록 후 모든 통신의 노드 신원 |
| 폐기 | **서버측 노드 상태 게이트** (아래) | 노드 제거·침해 시 즉시 차단 |

## 폐기(Revocation) — 장기 cert + 자동 승인의 안전장치

장기 cert는 보통 CRL/OCSP 배포가 부담이지만, **CP가 모든 gRPC stream을 종단**하므로 CRL 없이 해결:

```
에이전트 → (mTLS) → CP gRPC stream 수립 시도
                      └ CP: cert 유효성 + 주체(spiffe node_id) 매칭 + nodes.status 검사
                            status ∈ {disabled, revoked, pending_reenroll} → 연결 거부
```

- "노드 폐기" = `nodes.status = revoked` 한 줄 → **다음 연결부터 즉시 차단**. 인증서 자체는 유효해도 서버가 거부.
- 활성 stream 강제 종료도 CP가 자신이 잡고 있는 연결을 끊으면 됨(서버 주도).
- → CRL 배포·OCSP 불필요. 단일 조직·수십 노드 규모에 적합.

## CP 측 저장 (enrollment 도메인)

- `join_tokens` — id, token_hash, type(shared|one_time|**re_enroll**), ttl_expires_at, max_uses,
  used_count, created_by, revoked
- 내부 **CA** — CP 부팅 시 self-signed root CA 생성/로드(영속). 노드 cert 서명 전용.
- `node_certs` — 발급/폐기 **인증서 이력**(serial, spiffe_uri, issued_at, revoked_at, reason) 감사용
- 노드 신원·상태(`status`)는 `nodes` 테이블 (C. 데이터모델에서 상세)

## 에이전트 측 파일 (`/etc/xgen-agent/`, 0700)

| 파일 | 권한 | 내용 |
|------|------|------|
| `agent.key` | 0600 | 개인키 (노드 밖으로 안 나감) |
| `agent.crt` | 0644 | CP 발급 client cert |
| `ca.crt` | 0644 | CP CA bundle (서버 검증용) |
| `config.yaml` | 0644 | server 주소, node_id |

## 미해결/후속

- join token 발급 UI·CLI 흐름 (F. Web UI / xgenctl) — 운영자 인증/RBAC는 [07](07-operator-surface.md)
- ~~machine-id 충돌 정책~~ → **확정**(P0-2): pending_reenroll + 재등록 토큰 (위)
- CA 키 보호(파일 vs KMS) — 단일 조직 PoC는 파일(0600), 운영 강화는 후속
- mTLS rotation — MVP 비채택, 후속 운영강화
