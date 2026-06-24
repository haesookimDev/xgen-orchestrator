# xgen-orchestrator — 데이터 모델 (Data Model)

> Level-2 영역 C. `control-plane/.../db/`. PostgreSQL 스키마 + 저장소 역할 분담.
> 이 문서로 **MVP 슬라이스(등록+인벤토리+관측)가 end-to-end 설계 완결**.

## 저장소 역할 분담

| 데이터 | 저장소 |
|--------|--------|
| 노드·토큰·인벤토리·Job 메타·로그 | **PostgreSQL** |
| 시계열 메트릭 | **VictoriaMetrics** (Postgres 아님) |

## 결정 (Lock)

| 항목 | 결정 |
|------|------|
| machine-id 충돌 | **기존 노드 재등록(update)** — 재설치·에이전트 재설치에 자연스러움 |
| 인벤토리 이력 | **변경 이력 append 보관** (`node_inventory_history`) |
| Job/설치 로그 | **PostgreSQL** (`job_logs`) — 수십 노드 규모에 충분 |
| seq 영속화 | **연결 단위(ephemeral)** — DB 미영속, `last_seen_at`만 |

## 스키마

```sql
-- 노드 신원·상태 (등록/폐기/관측의 중심)
nodes (
  id            uuid PK,
  machine_id    text UNIQUE,        -- /etc/machine-id, 재등록 매칭 키
  hostname      text,
  status        text,               -- online|offline|disabled|revoked|pending_reenroll
  os text, arch text,
  agent_version text,
  cert_serial   text,               -- 현재 cert (이력은 node_certs)
  labels        jsonb,              -- 운영자 태그(역할·그룹)
  enrolled_at   timestamptz,
  last_seen_at  timestamptz
);

-- 인증서 발급/폐기 이력 (P0-2, 감사)
node_certs (
  id bigserial PK,
  node_id uuid REFERENCES nodes ON DELETE CASCADE,
  serial text, spiffe_uri text,     -- SAN: spiffe://xgen/node/<node_id>
  issued_at timestamptz, revoked_at timestamptz, reason text
);

-- 등록 토큰 (shared + one_time + re_enroll)
join_tokens (
  id uuid PK,
  token_hash text UNIQUE,           -- 평문 미저장
  type text,                        -- shared | one_time | re_enroll (P0-2)
  expires_at timestamptz,
  max_uses int, used_count int,
  revoked bool,
  created_by text, created_at timestamptz
);

-- 인벤토리 최신 스냅샷
node_inventory (
  node_id uuid PK REFERENCES nodes ON DELETE CASCADE,
  content_hash text,
  data jsonb,                       -- 전체 InventoryReport
  collected_at timestamptz
);

-- 인벤토리 변경 이력 (content_hash 바뀔 때 append)
node_inventory_history (
  id bigserial PK,
  node_id uuid REFERENCES nodes ON DELETE CASCADE,
  content_hash text,
  data jsonb,
  collected_at timestamptz
);

-- GPU 비정규화 (조회·집계: "A100 가진 노드 전부")
node_gpus (
  node_id uuid REFERENCES nodes ON DELETE CASCADE,
  index int, model text, vram_bytes bigint,
  driver_version text, cuda_version text, mig_enabled bool,
  PRIMARY KEY (node_id, index)
);

-- Job 이력 (Command/JobUpdate 영속화)
jobs (
  id uuid PK,
  node_id uuid REFERENCES nodes,
  command_id text UNIQUE,           -- at-least-once 멱등 키
  kind text,                        -- run_job | push_bundle | refresh_inventory | status
  phase text,                       -- pending|running|succeeded|failed|cancelled|interrupted
  exit_code int,
  attempt int, phase_seq int,       -- JobUpdate 재전송 idempotent update (P0-3)
  bundle_ref text, params jsonb,
  created_at timestamptz, started_at timestamptz, finished_at timestamptz
);
-- 노드당 mutating Job 1개 락 (P1-2)
CREATE UNIQUE INDEX one_mutating_job_per_node ON jobs(node_id)
  WHERE phase IN ('pending','running') AND kind <> 'status';

-- 하행 명령 상태 (at-least-once, CP 재시작 복원) (P0-3)
commands (
  command_id text PK,
  node_id uuid REFERENCES nodes, job_id uuid REFERENCES jobs,
  sent_at timestamptz, acked_at timestamptz, attempt int
);

-- Job/설치 로그 (무손실, 라인 단위)
job_logs (
  id bigserial PK,
  job_id uuid REFERENCES jobs ON DELETE CASCADE,
  ts_unix_ms bigint,
  source text,                      -- job-id|runtime|agent (LogBatch.source)
  stream text,                      -- stdout | stderr
  "offset" bigint,                  -- source별 단조 offset
  text text,
  UNIQUE (job_id, source, "offset")  -- 재전송 중복 insert 차단 (P0-3)
);

-- 운영자 인증/RBAC/감사 (P0-4, 상세는 07)
operators ( id uuid PK, username text UNIQUE, pw_hash text, role text );  -- viewer|operator
audit_log ( id bigserial PK, actor text, action text, target text,
  detail jsonb, at timestamptz );
```

## 쓰기 경로 (gRPC 메시지 → 테이블)

| gRPC 메시지 (B) | 처리 |
|------------------|------|
| `Hello` / `Heartbeat` | `nodes.last_seen_at`, `status=online`, `agent_version` 갱신 |
| `InventoryReport` | content_hash 비교 → 변경 시 `node_inventory` upsert + `node_inventory_history` append + `node_gpus` 재구성 |
| `MetricBatch` | VictoriaMetrics write (Postgres 아님) |
| `LogBatch` | `job_logs` insert — `(job_id,source,offset)` 충돌 시 무시(idempotent) |
| `JobUpdate` | `jobs` 갱신 — 더 큰 `phase_seq`만 반영(idempotent) |
| `CommandAck` | `commands.acked_at` 기록 (인메모리 아님, CP 재시작 복원) |

## 상태 전이

```
enroll → online ⇄ offline(heartbeat 결손)
              ├ 운영자 → disabled / 침해 → revoked  (다음 연결부터 stream 거부)
              └ machine-id 충돌 → pending_reenroll (재등록 토큰 요구, P0-2)
```

## MVP 슬라이스 완결 확인

```
install.sh ─enroll(REST)→ nodes 생성/재등록 + cert 발급
   └ stream ─Hello/Heartbeat→ status=online, last_seen
            ─InventoryReport→ node_inventory(+history) + node_gpus  → 대시보드
            ─MetricBatch→ VictoriaMetrics                          → 대시보드
            ─LogBatch→ job_logs                                    → 로그 뷰
```
→ 등록 + HW 인벤토리(CPU/NVIDIA GPU) + 관측(메트릭/로그)이 저장까지 일관되게 연결됨.

## 미해결/후속
- 메트릭 보존 기간·다운샘플링 (VictoriaMetrics 운영 설정)
- job_logs 보존·롤오프 정책 (대용량 시)
- 인벤토리 history 보존 기간
