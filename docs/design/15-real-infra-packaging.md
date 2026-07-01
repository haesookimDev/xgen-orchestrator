# xgen-orchestrator — 실 xgen-infra 패키징 & 이중 런타임 배포

> 개발 순서 4단계. [06-catalog-bundles.md](06-catalog-bundles.md)의 "비벤더, 빌드 시 참조" 원칙을
> 실제 xgen-infra 자산에 적용한다. 첫 실증 타겟: **192.168.1.138 (Windows + Docker Desktop + WSL k3s)**.

## 0. 목표와 비목표

- **목표**: `bundles/sample`(장난감)을 실제 xgen-infra 자산으로 대체하고, 서명된 번들이
  실 런타임(docker / k3s)에서 **끝까지 설치되는 것**을 e2e로 실증.
- **비목표(이번 단계)**: 전체 8개 서비스 프로덕션 배포(= private registry docker.x2bee.com,
  GitLab, Jenkins/ArgoCD 의존). 이는 폐쇄망 자산이 필요하므로 후속. 이번엔 **self-contained
  실 자산**(public 이미지만)으로 파이프라인 전체를 증명한다.

## 1. 타겟 토폴로지 — 이중 런타임 (핵심 결정)

192.168.1.138은 한 물리 머신에 두 실행 환경이 공존한다:

```
┌──────────────────────── 192.168.1.138 (Windows) ────────────────────────┐
│                                                                          │
│   Windows 네이티브 터미널 ─┐                                             │
│                            ├──▶  Docker Desktop 엔진  ◀──┐               │
│   WSL2 (Ubuntu)  ──────────┘   (WSL integration ON)      │               │
│      ├ k3s (네이티브 Linux)                              │               │
│      └ xgen-agent (여기서 실행) ─── docker CLI ──────────┘               │
│           │                                                              │
│           └── sh -c <entry>  (Linux 실행 환경)                           │
└──────────────────────────────────┬───────────────────────────────────────┘
                                    │ 단일 outbound mTLS gRPC
                                    ▼
                       Control Plane (Mac, 192.168.0.132)
```

### 결정: 에이전트는 WSL2 안에서 실행한다

| 이유 | 근거 |
|------|------|
| executor가 `sh -c` + `/proc` 기반 | Windows 네이티브 cmd엔 `sh` 없음. WSL Linux에서만 동작 |
| k3s가 WSL 네이티브 | `setup-k3s.sh`가 WSL 안에서 그대로 실행 |
| docker도 WSL에서 도달 | Docker Desktop "WSL integration" ON이면 WSL의 `docker` CLI가 Desktop 엔진에 연결 |

→ **단일 WSL 에이전트가 두 런타임(docker/k3s)을 모두 구동**한다. Windows 네이티브 에이전트는
불필요(오히려 `sh` 부재로 불가).

### 전제 조건 (pre-flight로 강제)
- WSL integration이 켜져 있어 WSL에서 `docker info` 성공 (docker 런타임 번들용).
- WSL에서 k3s 설치/기동 가능 (k3s 런타임 번들용).

## 2. 런타임 감지 — pre-flight 확장 (신규)

현재 pre-flight는 `requires`의 cpu/mem/gpu만 인벤토리와 비교한다. 이중 런타임에서는
"요청한 런타임이 이 노드에서 실제로 쓸 수 있는가"를 반드시 확인해야 한다. 아니면
docker 런타임을 요청했는데 WSL integration이 꺼져 있으면 설치 중반에 난해하게 실패한다.

```
에이전트 인벤토리(확장):
  runtimes: {
    docker:  true|false   # `docker info` 성공 여부
    compose: true|false   # `docker compose version` 성공
    k3s:     true|false   # k3s/kubectl 존재 또는 설치 가능
  }

pre-flight 게이트(확장):
  requires: { cpu_cores, mem_gb, gpu }          ← 기존
          + runtime 가용성(요청 런타임이 inventory.runtimes에 true)  ← 신규
  → 하나라도 불충족이면 Job을 시작조차 안 함 (명확한 실패 메시지)
```

## 3. 번들 2종 (이번 단계 산출물)

| 번들 | 런타임 | 자산(xgen-infra) | 의존 | 첫 e2e |
|------|--------|------------------|------|:---:|
| **xgen-infra-compose** | docker | `compose/k3s-infra/` (postgres·redis·qdrant·minio) | public 이미지만 | ✅ 1순위 |
| **xgen-k3s** | k3s | `k3s/scripts/setup-k3s.sh` (+ helm-chart) | 인터넷(get.k3s.io) | 2순위 |

`xgen-infra-compose`를 1순위로 잡는 이유: **self-contained**(public 이미지) → private
registry/GitLab 없이 파이프라인 전체(패키징→서명→fetch→검증→`docker compose up`→컨테이너
기동)를 증명할 수 있다. 파라미터(포트)·비밀(DB 패스워드)이 전부 `.env` 변수로 노출돼 있어
params/secret 주입 모델과 1:1로 맞물린다.

## 4. 번들 조립 — build.sh 확장 (비벤더 원칙 유지)

번들 "레시피"는 **우리 저장소**(`bundles/<name>/`)에 두고, 실제 설치 자산은 **빌드 시점에
외부 xgen-infra에서 복사**한다(커밋에 포함 안 함 = 비벤더).

```
bundles/xgen-infra-compose/         ← 레시피 (우리 저장소, 커밋됨)
  ├ manifest.json                   ← 런타임×액션 매핑 + requires
  ├ install.sh  status.sh  uninstall.sh   ← .env 생성 후 docker compose 호출
  └ sources.txt                     ← "xgen-infra에서 뭘 가져올지" 목록

build.sh <recipe_dir> <out.tar.gz>:
  1. staging/ 에 recipe_dir/* 복사 (sources.txt 제외)
  2. sources.txt 각 줄 "<src>  <dest>" → cp -r $XGEN_INFRA_PATH/<src> staging/<dest>
  3. staging/BUILD_INFO 기록: xgen-infra git ref(built_from) + 빌드 시각
  4. tar staging → out.tar.gz + sha256 출력
```

번들 tarball 구조(추출 후 = 에이전트 실행 cwd):

```
/  (extract root, executor cwd)
├ manifest.json
├ install.sh            entry: "bash install.sh"
├ status.sh  uninstall.sh
├ BUILD_INFO            built_from=<gitref>
└ k3s-infra/            ← compose/k3s-infra 복사본
   ├ docker-compose.yml
   ├ init-scripts/  qdrant-config.yaml
```

## 5. params / secret 주입 — executor 확장 (신규)

현재 executor는 `entry`만 쓰고 params를 프로세스 env로 넘기지 않는다. 실 번들은
`.env` 변수가 필요하므로 다음을 추가한다:

```
RunJob.params  (비밀 아님)      → 프로세스 env (KEY=val), 예약키(entry/cmd) 제외
RunJob.secret_refs (참조)       → 에이전트 로컬 secret store에서 값 조회 → env 주입
                                   (store: 파일 $XGEN_DIR/secrets/<ref> 또는 env XGEN_SECRET_<REF>)
                                   미해결 ref → 즉시 실패(명확한 메시지)

executor:  c.Env = os.Environ() + params(env) + secrets(env)
```

install.sh(레시피)는 이 env를 받아 `.env`를 생성한다:

```sh
# bundles/xgen-infra-compose/install.sh (개념)
cd k3s-infra
cat > .env <<EOF
POSTGRES_USER=${POSTGRES_USER:-ailab}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?secret required}   # secret_refs로 주입
POSTGRES_DB=${POSTGRES_DB:-xgen}
POSTGRES_PORT=${POSTGRES_PORT:-5432}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_PASSWORD=${REDIS_PASSWORD:?secret required}
QDRANT_HTTP_PORT=${QDRANT_HTTP_PORT:-6333}
QDRANT_GRPC_PORT=${QDRANT_GRPC_PORT:-6334}
MINIO_API_PORT=${MINIO_API_PORT:-9000}
MINIO_CONSOLE_PORT=${MINIO_CONSOLE_PORT:-9001}
MINIO_ROOT_USER=${MINIO_ROOT_USER:-minio}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD:?secret required}
EOF
docker compose -p xgen-infra up -d
```

- **비밀 분리**: DB/redis/minio 패스워드는 `secret_refs`로만, 값은 stream/DB/로그에 안 남김.
- **포트 파라미터화**: 운영자가 install 시 포트를 params로 지정 → 기존 스택과 충돌 회피.

## 6. e2e 런북 (138)

```
[Mac CP]
1. CP 기동 (LAN 바인드): XGEN_GRPC_SAN=127.0.0.1,localhost,192.168.0.132
2. 실 번들 빌드:  XGEN_INFRA_PATH=~/Desktop/orche/xgen-infra \
                  bundles/build.sh bundles/xgen-infra-compose dist/xgen-infra-compose.tar.gz
3. 등록+업로드:   POST /v1/bundles (manifest) → PUT .../artifact (서명)
4. join token 발급: xgenctl token-create one_time

[138 WSL]
5. 에이전트 설치(one-click): XGEN_SERVER=http://192.168.0.132:18080 \
      XGEN_JOIN_TOKEN=<token> ./install.sh   → enroll → stream 연결
6. (docker 런타임 pre-flight: WSL에서 docker info 성공 확인)

[Mac CP]
7. 설치:  xgenctl install <node> xgen-infra-compose@<ver> docker install \
             --param POSTGRES_PORT=15432 ... --secret POSTGRES_PASSWORD ...
8. xgenctl logs <job> -f  → docker compose up 로그 실시간
9. 검증: 138에서 docker ps → postgresql/redis/qdrant/minio 4개 healthy
```

## 7. 이번 단계 범위 vs 후속

| 항목 | 이번 | 후속 |
|------|:---:|:---:|
| build.sh 조립(recipe+subtree, git ref) | ✅ | |
| executor params/secret→env 주입 | ✅ | |
| 런타임 감지 pre-flight | ✅ | |
| xgen-infra-compose 번들 + docker e2e(138) | ✅ | |
| xgen-k3s 번들 (setup-k3s.sh) | 초안 | 실 k3s e2e |
| 전체 8서비스(registry/GitLab/ArgoCD) 배포 | | ✅ (6단계 HA와 함께) |
| secret store 정식화(KMS/rotation) | | ✅ |

## 8. 미해결/리스크
- Docker Desktop WSL integration이 꺼져 있으면 docker 런타임 불가 → pre-flight로 조기 차단.
- `compose/k3s-infra`의 `container_name` 고정(postgresql 등) → 동일 머신 중복 설치 시 충돌.
  이번 e2e는 138 단일 설치라 무방. 다중화는 compose project/name 파라미터화로 후속.
- CP↔138 서브넷 상이(0.x ↔ 1.x) → 라우팅/방화벽 확인 필요(현재 접속 블로커).
