# xgen-orchestrator — Job 오케스트레이션 & 번들 (Jobs & Bundles)

> Level-2 영역 D (+ E 일부). `agent/internal/executor`·`bundle`,
> `control-plane/.../bundles`, `bundles/xgen/manifest.yaml`.
> 두 번째 슬라이스 = 실제 가치(설치·관리). [03-grpc-protocol.md](03-grpc-protocol.md)·
> [04-data-model.md](04-data-model.md) 위에 얹힘.

## 결정 (Lock)

| 항목 | 결정 | 함의 |
|------|------|------|
| 호스트 실행 | **executor가 호스트에서 root 실행** | xgen-infra 스크립트가 본질적 호스트 레벨(강제 제약) |
| 번들 전송 | **Out-of-band HTTPS fetch (mTLS)** | RunJob엔 url+sha256만, 대용량·폐쇄망 이미지 대응, stream과 비경합 |
| v1 액션 | **install / uninstall / status** | 최단 가치 경로 |
| 파라미터 모델 | **xgen-infra `sites/*.yaml` 디스크립터 재사용** | 기존 add-site.py 파이프라인 그대로, 이중관리 회피 |
| Pre-flight | **하드 게이트** (자원 부족 시 차단) | 인벤토리 슬라이스의 첫 수확, 강제실행 옵션 별도 |

## 실행 흐름

```
[운영자] "노드 X에 XGEN을 k3s(single)로 설치, env=dev, domain=..."
   └ CP: Job 생성 → bundle+runtime+action+params 해석
        ├ 1. Pre-flight: manifest.requires vs node_inventory/node_gpus  → 부족 시 차단
        ├ 2. 번들 확보: 캐시 없으면 bundle_url(mTLS HTTPS) 제공
        ├ 3. Command{RunJob, command_id} 하행 (at-least-once)
        ▼
[에이전트 executor] (systemd root)
   ├ 번들 fetch(HTTPS, 재개·청크) → sha256 검증 → 전개
   ├ params → sites/{site}.yaml 디스크립터로 구성 → add-site.py 등 적용
   ├ manifest action→entry 스크립트 호스트 실행 (setup-k3s.sh / deploy.sh)
   ├ stdout/stderr → LogBatch 라이브 스트리밍 → job_logs
   └ JobUpdate{phase, exit_code} → jobs
```

## 호스트 실행 (설계 제약)

xgen-infra 스크립트는 k3s/docker 설치·systemd·패키지 관리 등 **호스트 레벨** 작업.
→ executor는 컨테이너가 아니라 **호스트에서 root(systemd 서비스)로** 스크립트 실행. xgen-infra
성격상 강제되는 제약.

## 번들 manifest (E 일부 확정)

```yaml
# bundles/xgen/manifest.yaml
solution: xgen
version: "2.0.0"
runtimes:
  docker:
    actions:
      install:   { entry: "compose/full-stack/deploy.sh", args: ["up"] }
      uninstall: { entry: "compose/full-stack/deploy.sh", args: ["down"] }
      status:    { entry: "compose/full-stack/status.sh" }
    requires: { cpu_cores: 8,  mem_gb: 32, gpu: optional }
  k3s:
    actions:
      install:   { entry: "k3s/scripts/setup-k3s.sh", args: ["install"] }
      uninstall: { entry: "k3s/scripts/setup-k3s.sh", args: ["uninstall"] }
      status:    { entry: "k3s/scripts/status.sh" }
    requires: { cpu_cores: 16, mem_gb: 64, gpu: { nvidia: 1 } }
params:        # sites 디스크립터로 매핑되는 입력 (manifest가 스키마 선언)
  site:   { type: string }
  env:    { type: enum, values: [dev, stg, prd] }
  domain: { type: string }
  mode:   { type: enum, values: [single, ha-2, ha], runtime: k3s }
```

## 파라미터 = sites 디스크립터 재사용

Job params는 새 형식을 만들지 않고 **xgen-infra `sites/{site}.yaml` 디스크립터**로 직렬화.
에이전트는 이를 디스크립터 파일로 떨어뜨린 뒤 기존 `add-site.py --write` / `setup-k3s.sh`
파이프라인을 그대로 호출. → 형식 이중관리 회피, 기존 자산 100% 재사용.

## RunJob 페이로드 (B 보완)

```protobuf
message RunJob {
  string job_id = 1;
  string bundle_ref = 2;        // solution@version
  string runtime = 3;           // docker|k3s|k8s
  string action = 4;            // install|uninstall|status
  map<string,string> params = 5;// → sites 디스크립터로 구성
  string bundle_url = 6;        // out-of-band mTLS HTTPS fetch
  string bundle_sha256 = 7;
}
```

## Pre-flight (하드 게이트)

```
CP: manifest.requires(cpu/mem/nvidia gpu) vs node_inventory/node_gpus 대조
    └ 미달 → Job 거부 (phase=failed, 사유 기록). 운영자 강제실행 플래그로 우회 가능.
```
- 인벤토리 슬라이스가 여기서 처음 가치를 냄. **향후 G의 "자원 부족 시 자동 증설"이 이 훅에 연결.**

## 번들 빌드·배포 (E 연계, 비벤더)

```
외부 xgen-infra ($XGEN_INFRA_PATH) ─bundles/xgen/build.sh→ 번들 tarball(+manifest, 서명)
   └ CP bundles 저장소(버전·sha256) ──RunJob.bundle_url(mTLS HTTPS)──▶ 에이전트 fetch
```

## 미해결/후속 (E 잔여 → 별도 라운드)
- 번들 버전 관리·서명 키 운영, 다중 솔루션 카탈로그 (E 본편)
- 동시 Job 직렬화/락 (노드당 1개 설치 동시성 제어)
- status 액션의 구조화된 결과 스키마
- 강제실행(Pre-flight 우회) 권한·감사
