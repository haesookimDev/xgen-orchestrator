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
| 노드 승인 | **토큰 유효하면 자동 승인** | 마찰 없음. **join token이 곧 신뢰 경계** → 토큰 관리가 핵심 |
| Client cert 수명 | **장기 cert (예 1년)** | 회전 로직 불필요. 단 폐기 수단 필수 → 아래 서버측 게이트로 해결 |

## 등록 플로우

```
[운영자] CP UI/CLI 에서 join token 발급 (TTL·사용횟수 제한, 또는 일회용)
   └ 토큰 + CP 주소 + CA 지문이 박힌 install.sh 한 줄 생성
        ▼
[노드] curl -sSL https://<cp>/install.sh | sudo bash -s -- \
          --token <JOIN> --server https://<cp> --ca-pin <SHA256>
  ├ OS/arch 감지 → CP에서 에이전트 바이너리 다운로드 (CA 지문 검증 후 TLS)
  ├ systemd 유닛 설치 (xgen-agent.service), /etc/xgen-agent/ (0700)
  └ 에이전트 부팅
        ├ 1. 로컬 키쌍 생성 → CSR (CN=node, machine-id 포함)
        │     private key = /etc/xgen-agent/agent.key (0600), 노드 밖으로 안 나감
        ├ 2. POST /v1/enroll { join_token, csr, node_info(hostname,machine-id,os,arch) }
        │        TLS는 핀된 CA 지문으로 검증
        │   [CP] join_token 검증(만료·횟수·폐기) → machine-id 중복 검사
        │        → 자동 승인 → 내부 CA가 CSR 서명
        │        → 반환 { node_id, client_cert(1y), ca_bundle }
        ├ 3. cert 저장 → 이후 mTLS 로 gRPC 양방향 stream 수립
        └ (일회용 토큰은 사용 즉시 소진, TTL 토큰은 used_count++)
```

## 신뢰 계층

| 계층 | 수단 | 역할 |
|------|------|------|
| CP 신뢰 | install.sh에 핀된 **CA 지문** | 노드가 가짜 CP에 등록하는 것 차단 |
| 1회성 인입 | **join token** (TTL+횟수 / 일회용) | 등록 자격 증명, 유출 시 폭발 반경 제한 |
| 영구 신뢰 | **mTLS client cert** (1년) | 등록 후 모든 통신의 노드 신원 |
| 폐기 | **서버측 노드 상태 게이트** (아래) | 노드 제거·침해 시 즉시 차단 |

## 폐기(Revocation) — 장기 cert + 자동 승인의 안전장치

장기 cert는 보통 CRL/OCSP 배포가 부담이지만, **CP가 모든 gRPC stream을 종단**하므로 CRL 없이 해결:

```
에이전트 → (mTLS) → CP gRPC stream 수립 시도
                      └ CP: cert 유효성 + nodes.status 검사
                            status ∈ {disabled, revoked} → 연결 거부
```

- "노드 폐기" = `nodes.status = revoked` 한 줄 → **다음 연결부터 즉시 차단**. 인증서 자체는 유효해도 서버가 거부.
- 활성 stream 강제 종료도 CP가 자신이 잡고 있는 연결을 끊으면 됨(서버 주도).
- → CRL 배포·OCSP 불필요. 단일 조직·수십 노드 규모에 적합.

## CP 측 저장 (enrollment 도메인)

- `join_tokens` — id, token_hash, type(shared|one_time), ttl_expires_at, max_uses, used_count,
  created_by, revoked
- 내부 **CA** — CP 부팅 시 self-signed root CA 생성/로드(영속). 노드 cert 서명 전용.
- 노드 신원·상태(`status`)는 `nodes` 테이블 (C. 데이터모델에서 상세)

## 에이전트 측 파일 (`/etc/xgen-agent/`, 0700)

| 파일 | 권한 | 내용 |
|------|------|------|
| `agent.key` | 0600 | 개인키 (노드 밖으로 안 나감) |
| `agent.crt` | 0644 | CP 발급 client cert |
| `ca.crt` | 0644 | CP CA bundle (서버 검증용) |
| `config.yaml` | 0644 | server 주소, node_id |

## 미해결/후속

- join token 발급 UI·CLI 흐름 (F. Web UI / xgenctl)
- machine-id 충돌(복제 VM·이미지화) 정책 — 재등록 vs 신규로 처리할지 D/C 단계에서 확정
- CA 키 보호(파일 vs KMS) — 단일 조직 PoC는 파일(0600), 운영 강화는 후속
