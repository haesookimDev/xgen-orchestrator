# xgen-orchestrator — gRPC 프로토콜 계약 (Protocol Contract)

> Level-2 영역 B. `proto/orchestrator/v1/`. stream 위 메시지 봉투·스키마·재연결·신뢰성.
> [02-enrollment-security.md](02-enrollment-security.md) 위에서 흐르는 통로.

## 결정 (Lock)

| 항목 | 결정 | 함의 |
|------|------|------|
| 등록 전송 | **REST (FastAPI) POST /v1/enroll** | cert 이전 1회, install.sh·바이너리 서빙과 동일 http 서버 |
| 상시 채널 | **단일 멀티플렉싱 bidi gRPC stream** | 연결 1개, 인바운드 0개. 봉투(oneof)로 모든 타입 다중화 |
| 오프라인 버퍼링 | **메트릭 drop / Job·로그 디스크 보관 후 재전송** | TSDB 공백 허용, 설치 결과·로그는 무손실 |
| 명령 전달 | **At-least-once + command_id 멱등성** | 미응답 재전송, 에이전트가 중복 실행 차단 |

## 서비스 토폴로지

```
① 등록(REST, cert 없음, join token 인증)   ② 상시(mTLS bidi stream)
   POST /v1/enroll → {cert, ca, node_id}      AgentStream.Connect(stream)⇄(stream)
```

## stream.proto — 봉투 멀티플렉싱

```protobuf
service AgentStream {
  rpc Connect(stream AgentMessage) returns (stream ServerMessage);
}

// 상행 (Agent → CP)
message AgentMessage {
  string node_id = 1;
  uint64 seq     = 2;            // 연결 내 단조 증가 → 재전송 dedup
  oneof payload {
    Hello           hello      = 10;   // 연결 직후 1회: agent_ver, last_acked_seq
    Heartbeat       heartbeat  = 11;
    InventoryReport inventory  = 12;
    MetricBatch     metrics    = 13;
    LogBatch        logs       = 14;
    JobUpdate       job_update = 15;
    CommandAck      ack        = 16;   // command_id 수신 확인
  }
}

// 하행 (CP → Agent)
message ServerMessage {
  uint64 seq = 1;
  oneof payload {
    HelloAck hello_ack = 10;
    Command  command   = 11;
    Ping     ping      = 12;
  }
}
```

## inventory.proto / telemetry.proto / job.proto (요지)

```protobuf
// inventory.proto
message InventoryReport {
  CPUInfo cpu = 1; MemoryInfo memory = 2; repeated DiskInfo disks = 3;
  OSInfo os = 4; Virtualization virt = 5; repeated GPUInfo gpus = 6;
  string content_hash = 7;          // 동일 hash면 무전송 (변경 감지)
}
message GPUInfo { string model=1; uint32 index=2; uint64 vram_bytes=3;
  string driver_version=4; string cuda_version=5; bool mig_enabled=6; }

// telemetry.proto
message MetricBatch { repeated MetricPoint points = 1; }   // → VictoriaMetrics
message MetricPoint { string name=1; map<string,string> labels=2;
  double value=3; int64 ts_unix_ms=4; }
message LogBatch { string source=1; repeated LogLine lines=2; }  // source = job-id|runtime|agent
message LogLine { int64 ts_unix_ms=1; string stream=2; string text=3; // stdout|stderr
  uint64 offset=4; }                // ★ source별 단조 offset → (job_id,source,offset) 중복제거 키

// job.proto
message Command {
  string command_id = 1;            // 멱등 키
  oneof kind { RunJob run_job=10; RefreshInventory refresh=11;
               PushBundle push_bundle=12; CancelJob cancel=13; }
}
message JobUpdate {
  string command_id=1; string job_id=2;
  enum Phase { PENDING=0; RUNNING=1; SUCCEEDED=2; FAILED=3; CANCELLED=4; INTERRUPTED=5; }
  Phase phase=3; int32 exit_code=4; string message=5;
  uint32 attempt=6; uint32 phase_seq=7;  // ★ 재전송 idempotent update 키
}
```

## 신뢰성 모델

### 상행 버퍼링 (오프라인 시)
```
메트릭     → drop. 재연결 후 현재값부터 (TSDB 공백 허용)
Job/로그   → 에이전트 로컬 디스크 큐에 보관 → 재연결 시 재전송 (무손실)
```
- 에이전트는 metrics 와 durable(job/log) 큐를 분리 운용. 메모리 압박 시 메트릭만 버림.

### 중복 제거 (P0-3) — 연결 seq와 별개의 영속 식별자
연결 `seq`는 ephemeral(연결 단위)이라 재연결 후 재전송분을 dedup하지 못한다. 따라서 durable 메시지는 **영속 식별자**로 idempotent 처리:
```
LogLine   : (job_id, source, offset)  → job_logs UNIQUE 제약, 중복 insert 무시
JobUpdate : (job_id, attempt, phase_seq) → idempotent update (오래된 phase_seq 무시)
```

### 하행 명령 (At-least-once + 멱등성, 상태 영속)
```
CP: Command{command_id} 전송 → commands 테이블에 sent 기록 → ack 대기, 타임아웃 시 재전송
Agent: 처리한 command_id 집합 유지 → 재수신 시 재실행 없이 ack만
```
- 설치 같은 비가역 작업도 command_id 로 중복 실행 차단.
- **CP 재시작 복원**: pending command/ack 상태를 `commands` 테이블에 영속 → 재시작 후
  `jobs.phase`와 에이전트 reconcile 로 at-least-once 상태 복구.

## 재연결 시맨틱
```
끊김 → 에이전트 지수 백오프 재연결 → Hello{last_acked_seq}
     → CP HelloAck → durable 큐 누락분만 재전송
liveness: heartbeat 주기 송신, CP 가 N회 결손 시 nodes.status=offline
```

## 미해결/후속
- RunJob / PushBundle 페이로드 상세 — D. Job 오케스트레이션에서 확정 ([05](05-job-orchestration.md))
- ~~seq 영속화 범위~~ → **확정**: seq=연결 단위 ephemeral, durable dedup은 offset/phase_seq (P0-3)
- proto 버전 호환(agent_ver ↔ CP) 정책 — 운영 단계
