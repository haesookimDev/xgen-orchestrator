# xgen-orchestrator — 솔루션 카탈로그 & 번들 (Catalog & Bundles)

> Level-2 영역 E. `control-plane/.../bundles`, `bundles/xgen/`.
> [05-job-orchestration.md](05-job-orchestration.md)에서 절반 연 번들 주제를 닫음.

## 결정 (Lock)

| 항목 | 결정 | 함의 |
|------|------|------|
| 번들 서명 | **cosign (key 모드)** | 오프라인 검증, Sigstore/OCI·CI 통합. 공개키 에이전트 사전 배포 |
| 저장 백엔드 | **MinIO / 오브젝트 스토리지** | compose에 MinIO 추가, CP proxy(mTLS) 경유 서빙, 대용량·다수 번들 대응 |
| 버전 모델 | **명시적 버전 핀 + latest 포인터** | 단순·예측 가능, 채널 승급 절차 불요 |

## 카탈로그 모델 (XGEN 전용, 구조는 일반화 대비)

```sql
bundles (
  id           uuid PK,
  solution_id  text,             -- 'xgen' (단일, 구조만 다중 대비)
  version      text,             -- semver 2.0.0
  is_latest    bool,             -- latest 포인터 (solution_id별 1개)
  sha256       text,
  cosign_bundle text,            -- cosign 서명/증명 (key 모드)
  manifest     jsonb,            -- manifest.yaml 파싱본
  storage_uri  text,             -- MinIO 오브젝트 키
  size_bytes   bigint,
  built_from   text,             -- xgen-infra git ref (추적성)
  created_at   timestamptz,
  UNIQUE (solution_id, version)
);
-- latest 단일 보장 (정합성 #5): bool 만으로는 부족 → partial unique index
CREATE UNIQUE INDEX one_latest_per_solution ON bundles(solution_id) WHERE is_latest;
```

## 번들 라이프사이클 (비벤더, 빌드 시 참조)

```
외부 xgen-infra ($XGEN_INFRA_PATH @ git ref)
   └ bundles/xgen/build.sh
        ├ 런타임별 자산(compose/k3s/scripts)+manifest.yaml 패키징 → tarball
        ├ sha256 + cosign sign (key 모드)
        └ CP 업로드(POST /v1/bundles) → MinIO 저장 + bundles 등록 → 카탈로그 노출
                                                                    ▼
   운영자 version 선택(또는 latest) → RunJob.bundle_url(CP proxy)+sha256 → 에이전트
```

## 저장·서빙 (MinIO) — 다운로드 신뢰 경계 (P1-1)

```
CP compose 스택: control-plane + Postgres + VictoriaMetrics + Grafana + MinIO
   └ 번들 tarball = MinIO 오브젝트
   └ 기본 경로: agent ──mTLS──▶ CP bundle proxy ──▶ MinIO   (단일 mTLS 신뢰 경계)
```
- **기본은 CP bundle proxy(mTLS)**. MinIO presigned URL 직접 다운로드는 기본에서 제외(bearer URL
  모델이라 신뢰 속성이 다름). 특수 케이스로 채택 시 만료·IP제한·유출영향을 문서화.
- 다운로드 **권한 모델(mTLS)** 과 **무결성/진위(sha256+cosign)** 는 직교 — 후자가 전자를 대체하지 않음.

## 에이전트 측 검증 (D의 fetch에 이어)

```
fetch(CP proxy, mTLS) → sha256 일치 → cosign verify(사전 배포 공개키)
   └ 무결성(sha256) + 진위(cosign) 둘 다 통과해야 전개
```

## 노드 측 번들 캐시
- 노드 로컬 `version→sha256` 캐시. RunJob.sha256 일치 시 fetch 생략 (동일 버전 재설치·
  다중 노드 동일 버전 재다운로드 회피).

## latest 포인터
- `bundles.is_latest` = solution_id별 1개 (partial unique index로 DB 보장). 새 버전 업로드 시 운영자가 latest 승격(명시적).
- 설치 시 운영자는 명시적 version 또는 `latest` 지정. 재현성 위해 Job엔 해석된 구체 version 기록.

## 미해결/후속
- cosign 키 보관(파일 vs KMS)·로테이션
- 번들 GC(미사용 구버전 정리) 정책
- 다중 솔루션 카탈로그 본격화 (일반화 단계)
