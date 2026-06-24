# xgen-orchestrator — 설계 리뷰 해소 (Review Resolutions)

> [09-design-review.md](09-design-review.md)의 P0/P1·정합성 지적에 대한 확정 해소.
> 각 원본 문서(02~08)는 이 결정에 맞춰 본문이 갱신됨. 이 문서는 권위 요약.

## P0 해소

### P0-1. Installer/바이너리 부트스트랩 신뢰 → **신뢰 CA TLS + 바이너리 cosign 서명**
"install.sh 다운로드 신뢰"와 "에이전트 바이너리 신뢰"를 분리한다.

| 단계 | 신뢰 수단 |
|------|-----------|
| install.sh 다운로드 | CP가 **공인/사내 신뢰 CA 인증서**로 서빙 → 최초 `curl` TLS가 정상 검증(TOFU 아님) |
| 에이전트 바이너리 | install.sh가 받은 바이너리를 **cosign 서명 검증**(공개키 스크립트에 내장/핀) |
| 등록(enroll) TLS | 위와 동일 신뢰 CA. `--ca-pin`은 mTLS 클라이언트 단계의 보조 핀으로만 의미 |

→ `--ca-pin`만으로 최초 TLS를 대체하던 [02](02-enrollment-security.md) 예시를 폐기. 사내 CA가 없으면
`curl --pinnedpubkey` 또는 별도 채널+checksum이 대안이나 **기본은 신뢰 CA TLS**.

### P0-2. machine-id 재등록 → **pending_reenroll + 재등록 토큰 + 주체-node_id 매칭**
자동 update를 금지하고 탈취 경로를 차단한다.

- machine-id 중복 등록 시도 → 자동 update 안 함. 노드를 **`pending_reenroll`** 상태로 두고
  **별도 re-enroll token**을 요구(운영자 발급).
- 발급 cert SAN에 **SPIFFE-like URI(`spiffe://xgen/node/<node_id>`)** 포함. stream 수립 시
  **인증서 주체와 메시지 `node_id`를 반드시 매칭**(불일치 시 거부).
- `cert_serial`은 현재값뿐 아니라 **발급/폐기 이력**을 감사 가능하게 별도 테이블에 보존.

### P0-3. Job/로그 무손실 + 중복 제거 → **durable event_id/offset + unique key**
연결 seq(ephemeral)와 별개의 영속 식별자를 둔다.

- durable 메시지(LogBatch/JobUpdate)에 `source_id`(=job_id 등) + 단조 `offset` + `event_id` 부여.
- `job_logs`에 **`UNIQUE(job_id, source, offset)`** → 재전송 중복 insert 차단(idempotent).
- `JobUpdate`에 `attempt`/`phase_seq` → 재전송 시 idempotent update.
- CP의 pending command/ack 상태를 **DB(`commands`)에 영속** → CP 재시작 후 `jobs.phase`와
  에이전트 reconcile 로 at-least-once 상태 복원.

### P0-4. 운영자 인증/RBAC/감사 → **Local admin + JWT, 2-role, 감사 로그**
MVP의 보안 경계로 승격(후속 아님).

- 인증: **local admin 계정 + session/JWT**. (옵션 OIDC는 후속 확장)
- 권한 2단계: **viewer**(읽기) / **operator**(token 발급, Job 실행/취소/force, 번들 업로드·latest
  승격, 노드 disable/revoke).
- **감사 로그** 대상: token 발급·폐기, bundle upload·latest 변경, job 생성·cancel·force,
  node disable·revoke·re-enroll.
- **Web UI·xgenctl·WebSocket 모두 동일 인증/권한** 모델 사용.

## P1 해소

### P1-1. 번들 다운로드 신뢰 경계 → **CP bundle proxy(mTLS) 기본**
- 기본 경로: **agent → CP bundle proxy(mTLS) → MinIO**. 단일 mTLS 신뢰 경계로 통일.
- presigned URL 직접 다운로드는 기본에서 제외(특수 케이스로만, 채택 시 만료·IP제한·유출영향 문서화).
- sha256 + cosign 검증은 필수지만 **다운로드 권한 모델을 대체하지 않음**(직교).

### P1-2. 노드당 Job 동시성/취소/복구 → **노드당 mutating Job 1개 락**
- MVP부터 **노드당 mutating Job(install/uninstall)은 1개만**. `status` 등 read-only만 병행.
- 락 구현: `jobs`에 노드별 활성 mutating Job 유니크 제약(또는 advisory lock).
- **cancel**: 프로세스 트리 종료 → timeout → partial state 기록 → 후속 status/reconcile.
- **agent 재시작 복구**: 실행 중이던 Job을 재시작 시 감지해 `interrupted`로 보고 → 운영자/Reconcile 결정.

### P1-3. 파라미터/secret → **제한적 자체 스키마 + secret 분리**
- manifest `params`는 제한적 자체 스키마(type: enum/string/int/bool + runtime 조건). MVP는 JSON Schema 전면 채택 안 함.
- **secret 값(인증정보 등)은 Job params 평문·로그·job_logs에 남기지 않음**. 별도 secret 참조로 주입.
- sites descriptor 산출물을 artifact로 저장 시 **민감 필드 masking/암호화**.

### P1-4. LLM 데이터 반출 → **opt-in + redaction + 폐쇄망 로컬 전용**
- 외부 LLM(Claude API) 사용은 **site/workspace 단위 opt-in**(기본 off).
- 입력(로그/env/토큰/도메인/IP)에 **redaction** 적용 후 전송.
- **폐쇄망 모드는 외부 Provider 비활성화**, local vLLM provider만 허용.

## 문서 정합성 해소

| # | 지적 | 해소 |
|---|------|------|
| 1 | 상태 문구 오래됨 | [00](00-overview.md) "미설계 영역"→"설계 완료", 상태 라인 최신화 |
| 2 | "단일 바이너리" 모호 | 전 문서 **"단일 CP 서비스 컨테이너 + docker-compose"**로 통일 |
| 3 | compose 구성 불일치 | 전 문서 **CP + Postgres + VictoriaMetrics + Grafana + MinIO**로 통일 |
| 4 | mTLS rotation 충돌 | MVP=장기 cert 회전 없음(서버측 게이트). rotation은 후속 운영강화로 분리 명시 |
| 5 | latest 포인터 제약 불완전 | `bundles`에 **partial unique index**(`WHERE is_latest`)로 solution별 1개 보장 |

## 갱신된 스키마 델타 (요약)

```sql
-- nodes: 상태 확장
status text   -- online|offline|disabled|revoked|pending_reenroll

-- 인증서 발급/폐기 이력 (감사)
node_certs (
  id bigserial PK, node_id uuid REFERENCES nodes,
  serial text, spiffe_uri text,
  issued_at timestamptz, revoked_at timestamptz, reason text
);

-- job_logs: 중복 제거 키
job_logs ( ..., source text, "offset" bigint,
  UNIQUE (job_id, source, "offset") );

-- jobs: 재전송 idempotency + 노드 락
jobs ( ..., attempt int, phase_seq int );
-- 노드당 활성 mutating Job 1개: partial unique index
CREATE UNIQUE INDEX one_mutating_job_per_node
  ON jobs(node_id) WHERE phase IN ('pending','running') AND kind <> 'status';

-- commands: at-least-once 상태 영속 (CP 재시작 복원)
commands (
  command_id text PK, node_id uuid, job_id uuid,
  sent_at timestamptz, acked_at timestamptz, attempt int
);

-- bundles: latest 단일 보장
CREATE UNIQUE INDEX one_latest_per_solution
  ON bundles(solution_id) WHERE is_latest;

-- 운영자 인증
operators ( id uuid PK, username text UNIQUE, pw_hash text, role text ); -- viewer|operator
audit_log ( id bigserial PK, actor text, action text, target text,
  detail jsonb, at timestamptz );
```

## 개발 착수 기준 충족 여부

리뷰의 6개 필수 항목 — 모두 해소:
1. ✅ Installer bootstrap 신뢰 (P0-1)
2. ✅ 재등록/인증서 주체/node_id 매칭 (P0-2)
3. ✅ durable event id·log/job idempotency (P0-3)
4. ✅ 운영자 인증/RBAC/감사 (P0-4)
5. ✅ 번들 다운로드 기본 경로·신뢰 경계 (P1-1)
6. ✅ 노드당 Job 락·cancel·timeout·복구 (P1-2)
