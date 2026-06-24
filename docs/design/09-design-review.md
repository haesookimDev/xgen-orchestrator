# xgen-orchestrator — 설계 리뷰

검토일: 2026-06-24

## 검토 범위

- `docs/design/README.md`
- `00-overview.md` ~ `08-llm-agentic-layer.md`

이 리뷰는 설계 문서 간 정합성, 보안 경계, 장애/재시도 모델, 운영 준비도를 기준으로 작성했다.
현재 저장소에는 구현 코드가 없으므로 코드-설계 일치성은 검토 대상에서 제외했다.

## 종합 의견

전체 방향은 타당하다. Agent-pull 기반 outbound mTLS stream, 기존 `xgen-infra` 자산 재사용,
PostgreSQL/VictoriaMetrics 역할 분리, Go agent + Python control-plane + Next.js web 조합은
대상 규모(단일 조직, 수십 노드)에 맞는 현실적인 설계다.

다만 설계 문서가 곧 개발 착수 기준이라면 아래 항목은 먼저 확정해야 한다. 특히 installer bootstrap
신뢰, 재등록 보안, stream 재전송/로그 중복 방지, 운영자 인증/RBAC, 번들 다운로드 신뢰 경계는
구현 중에 자연스럽게 해결될 성격이 아니다. 설계 단계에서 계약을 고정해야 이후 구현이 흔들리지 않는다.

## 잘 설계된 부분

1. **기존 자산 재사용 경계가 명확함**
   - `xgen-orchestrator`가 패키징을 새로 만들지 않고 `xgen-infra` 번들을 원격 실행/관측하는
     컨트롤 플레인이라는 방향이 일관적이다.
   - `bundles/`를 비벤더 경계로 두고 `$XGEN_INFRA_PATH`를 빌드 시 참조하는 결정은 결합도를 낮춘다.

2. **Agent-pull 모델이 배포 환경과 잘 맞음**
   - NAT, 방화벽, 폐쇄망 뒤 노드에 inbound 포트를 열지 않는 설계는 운영 현실에 맞다.
   - 단일 gRPC stream으로 명령, 메트릭, 로그, Job 업데이트를 멀티플렉싱하는 구조도 단순하다.

3. **MVP 슬라이스가 end-to-end로 연결됨**
   - 등록 → stream → 인벤토리 → 메트릭/로그 저장 → 대시보드까지 첫 슬라이스의 가치 흐름이 보인다.
   - 설치 전 베어 노드에서 직접 GPU/CPU 인벤토리를 수집한다는 결정은 Pre-flight와도 잘 이어진다.

4. **운영 규모에 맞는 저장소 선택**
   - 상태/인벤토리/Job 메타는 PostgreSQL, 시계열은 VictoriaMetrics로 분리한 판단은 적절하다.

## 개발 착수 전 필수 보완

### P0. `install.sh` bootstrap 신뢰 모델이 불완전함

`02-enrollment-security.md`는 TOFU 차단을 위해 CA 지문을 pin한다고 설명하지만, 예시는
`curl -sSL https://<cp>/install.sh | sudo bash ... --ca-pin <SHA256>` 형태다. 이 방식은
`install.sh`를 내려받는 최초 TLS 연결 자체를 pin으로 검증하지 못한다. 스크립트를 받은 뒤
스크립트 내부에서 CA pin을 검증해도, 이미 공격자가 바꾼 스크립트를 실행했을 수 있다.

권장 보완:

- CP가 공인/사내 신뢰 CA 인증서를 사용해 최초 `curl` TLS 검증을 통과하도록 한다.
- 또는 설치 명령 자체에 `curl --pinnedpubkey`/동등한 pin 검증을 포함한다.
- 또는 installer를 별도 신뢰 채널로 배포하고 checksum/signature 검증을 강제한다.
- 문서에는 "install.sh 다운로드 신뢰"와 "agent binary 다운로드 신뢰"를 분리해서 명시한다.

### P0. machine-id 기반 재등록이 노드 탈취 경로가 될 수 있음

`04-data-model.md`는 machine-id 충돌 시 기존 노드를 update한다고 확정한다. 반면
`02-enrollment-security.md`는 join token이 곧 신뢰 경계이고 토큰이 유효하면 자동 승인한다고 한다.
이 조합에서는 공격자가 유출된 join token과 대상 machine-id를 확보할 경우 기존 노드의 새 인증서를
발급받아 노드를 가장할 수 있다. 복제 VM 이미지처럼 machine-id가 중복되는 정상 시나리오도 같은
문제를 만든다.

권장 보완:

- 기존 노드 재등록은 기존 client cert가 있는 cert rotation 경로와, 운영자 승인 기반 recovery 경로로 나눈다.
- machine-id 중복 시 자동 update하지 말고 `pending_reenroll` 상태로 두거나 별도 re-enroll token을 요구한다.
- cert SAN 또는 SPIFFE-like URI에 `node_id`를 넣고, stream 수립 시 인증서 주체와 메시지 `node_id`를 반드시 매칭한다.
- `cert_serial`은 현재값뿐 아니라 발급 이력/폐기 이력도 감사 가능해야 한다.

### P0. Job/로그 무손실과 중복 제거 계약이 부족함

`03-grpc-protocol.md`는 Job/로그는 디스크 큐에 보관 후 재전송한다고 하고,
`04-data-model.md`는 seq를 연결 단위 ephemeral로 확정한다. 이 상태에서는 CP가 로그를 DB에 쓴 뒤
ack 전에 연결이 끊긴 경우, 재전송된 로그를 중복 insert할 수 있다. `job_logs`에도 중복 제거 키가 없다.
`CommandAck` 역시 인메모리 추적만 해제한다고 되어 있어 CP 재시작 시 at-least-once 상태 복원이 애매하다.

권장 보완:

- durable 메시지에는 연결 seq와 별개로 `source_id` + `offset` 또는 `event_id`를 둔다.
- `job_logs`에 `(job_id, source, offset)` 같은 unique key를 추가한다.
- JobUpdate도 `attempt`, `event_id`, `phase_seq` 중 하나를 가져야 재전송 시 idempotent update가 가능하다.
- CP의 pending command/ack 상태는 DB에 저장하거나, CP 재시작 후 `jobs.phase`와 agent reconcile 절차로 복원한다고 명시한다.

### P0. 운영자 인증/RBAC/감사가 후속으로 밀려 있음

`07-operator-surface.md`는 운영자 인증·RBAC를 미해결로 둔다. 그러나 MVP 기능에는 join token 발급,
root 권한 Job 실행, Pre-flight 강제 우회, 번들 업로드/latest 승격, 노드 폐기 같은 고위험 작업이 포함된다.
단일 조직이라도 "단순 관리자 인증"은 개발 후속이 아니라 MVP 보안 경계다.

권장 보완:

- MVP 최소 인증 방식을 확정한다. 예: local admin 계정 + session/JWT, 또는 OIDC 연동.
- 권한을 최소 2단계로 나눈다. 예: viewer, admin/operator.
- 감사 로그 대상을 명시한다. token 발급/폐기, bundle upload/latest 변경, job 생성/cancel/force, node disable/revoke.
- WebSocket과 xgenctl도 동일 인증/권한 모델을 사용해야 한다.

### P1. 번들 다운로드 신뢰 경계가 문서 간 섞여 있음

`05-job-orchestration.md`는 out-of-band mTLS HTTPS fetch라고 하고,
`06-catalog-bundles.md`는 MinIO presigned URL 또는 CP proxy/mTLS 경유라고 설명한다.
presigned URL 직접 다운로드는 bearer URL 모델이고, mTLS client auth 모델과 보안 속성이 다르다.
둘 다 가능하지만 어떤 경로가 기본인지, 폐쇄망/사내망에서 어느 신뢰 경계를 쓰는지 확정해야 한다.

권장 보완:

- 기본 경로를 하나로 정한다. 예: agent → CP bundle proxy(mTLS) → MinIO.
- MinIO presigned URL을 직접 쓴다면 URL 유출 시 영향, 만료 시간, IP 제한 가능 여부, TLS CA 검증 경로를 문서화한다.
- sha256과 cosign 검증은 필수지만, 다운로드 권한 모델을 대체하지 않는다고 명시한다.

### P1. 노드 단위 Job 동시성/취소/복구 정책이 빠져 있음

`05-job-orchestration.md`가 동시 Job 직렬화/락을 후속으로 둔다. 하지만 install/uninstall은 root에서
호스트 상태를 바꾸는 작업이므로 동시 실행을 허용하면 손상 가능성이 크다.

권장 보완:

- MVP부터 노드당 mutating Job은 1개만 허용한다. `status` 같은 read-only action만 병행 가능하게 둔다.
- cancel은 프로세스 트리 종료, timeout, partial state 처리, 후속 status/reconcile 흐름을 포함해야 한다.
- agent 재시작 후 실행 중이던 Job을 어떻게 복구/보고할지 정의한다.

### P1. 파라미터와 secret 처리 모델이 부족함

RunJob 페이로드는 `map<string,string> params`이고 manifest는 params schema를 선언한다.
하지만 `sites/{site}.yaml` 디스크립터로 변환되는 과정에서 enum 외 타입, 중첩 구조, 파일/인증정보,
민감값을 어떻게 다룰지 명확하지 않다.

권장 보완:

- manifest params schema를 JSON Schema 수준으로 올릴지, 제한된 자체 schema로 둘지 결정한다.
- secret 값은 Job params 평문/로그에 남기지 않는 규칙을 둔다.
- sites descriptor 생성 결과를 job artifact로 저장할 경우 masking/암호화 기준을 정한다.

### P1. LLM 계층의 데이터 반출 정책이 필요함

`08-llm-agentic-layer.md`는 Claude API 기본, 로컬 vLLM 폴백을 둔다. 입력으로 job_logs, 런타임 로그,
메트릭, 인벤토리를 사용하므로 외부 API 호출 시 고객/인프라 정보가 반출될 수 있다.

권장 보완:

- 외부 LLM 사용은 workspace/site 단위 opt-in으로 둔다.
- 로그/환경변수/토큰/도메인/IP에 대한 redaction 정책을 정의한다.
- 폐쇄망 모드에서는 외부 Provider를 비활성화하고 local provider만 허용한다고 명시한다.

## 문서 정합성 이슈

1. **상태 표시가 오래됨**
   - `00-overview.md`의 "미설계 영역"은 02~08 문서에서 이미 상당 부분 확정됐다.
   - "설계 진행 중", "Level-2 일부 확정", "개발은 설계 완료 후 착수" 같은 상태 문구를 최신화해야 한다.

2. **Control Plane "단일 바이너리" 표현이 모호함**
   - Python FastAPI+grpcio, Next.js web, Postgres, VictoriaMetrics, Grafana, MinIO를 포함하는 현재 구조에서
     "단일 바이너리"는 실제 배포 단위와 맞지 않는다.
   - "단일 CP 서비스 컨테이너 + docker-compose"처럼 표현을 바꾸는 편이 정확하다.

3. **deploy compose 구성 설명이 문서마다 다름**
   - `01-repo-structure.md`의 compose 주석은 CP + Postgres + VictoriaMetrics + Grafana만 언급한다.
   - `06-catalog-bundles.md`와 색인은 MinIO를 포함한다. compose 구성 목록을 통일해야 한다.

4. **`mTLS rotation` 표현과 장기 cert 정책이 충돌함**
   - overview 미설계 목록에는 rotation이 남아 있지만, `02-enrollment-security.md`는 1년 장기 cert와
     서버측 상태 게이트를 선택한다. rotation을 하지 않는 MVP 정책인지, 후속 운영 강화 항목인지 분리한다.

5. **latest 포인터의 DB 제약이 불완전함**
   - `bundles.is_latest`가 solution별 1개라는 규칙은 단순 bool만으로 보장되지 않는다.
   - partial unique index 또는 별도 `solution_channels` 테이블을 설계에 추가해야 한다.

## 권장 개발 착수 기준

개발 착수 전 최소한 아래 산출물을 설계 문서에 반영하는 것을 권장한다.

1. Installer bootstrap 신뢰 절차 확정
2. 재등록/인증서 주체/node_id 매칭 정책 확정
3. durable event id와 log/job idempotency schema 확정
4. 운영자 인증/RBAC/감사 로그 MVP 확정
5. 번들 다운로드 기본 경로와 신뢰 경계 확정
6. 노드당 Job 락, cancel, timeout, agent 재시작 복구 정책 확정

위 6개가 닫히면 현재 설계는 MVP 구현에 들어갈 수 있는 수준으로 올라간다.
