# xgen-orchestrator — 운영 정책 (보존 / 시크릿·키)

> 추가 설계 ②③. 데이터 수명주기 + 시크릿/키 관리. 각 문서의 "미해결" 운영 항목 통합.

## ② 데이터 수명주기 (Lock)

| 데이터 | 저장소 | 정책 |
|--------|--------|------|
| 메트릭 | VictoriaMetrics | raw 15s, **보존 30일**, 다운샘플 없음 (VM `-retentionPeriod=30d`) |
| job_logs | Postgres | **30일 Postgres → MinIO 아카이브 후 DB 삭제** (장기 감사 보관) |
| 인벤토리 history | Postgres | 변경 시에만 적재(드묾) → 무제한 보관 |
| 번들 | MinIO | latest+핀+최근 K개 유지, 미참조 구버전 GC |

### job_logs 아카이브 흐름
```
설치 직후~30일 : Postgres job_logs (라이브 tail·조회)
30일 경과      : Job 단위로 MinIO 오브젝트(예: logs/<job_id>.ndjson.gz) 아카이브
                 → Postgres 행 삭제 (DB 경량 유지)
조회           : 최근=Postgres, 과거=MinIO에서 on-demand 로드
```

### 번들 GC
```
보호 대상: is_latest · 운영자 핀 · 클러스터(clusters.version)가 현재 참조 중 · 최근 K개
그 외 미참조 구버전 → MinIO 오브젝트 + bundles 행 GC
```

## ③ 시크릿 / 키 관리 (Lock)

| 항목 | 결정 |
|------|------|
| CP 시크릿 저장 | **Postgres app-level 암호화** (추가 인프라 없음) |
| 마스터 키 출처 | **파일(0600) + env 주입** (운영자 백업 책임) |

### 시크릿 분류와 보관

| 분류 | 보관 위치 | 노출 경계 |
|------|-----------|-----------|
| CA 개인키 | CP 파일(0600) → 후속 KMS | CP 내부, cert 서명 전용 |
| cosign 서명키 | **빌드 환경/CI 시크릿 (CP 아님)** | 에이전트엔 공개키만 배포 |
| node-token | `cluster_secrets.value_enc` (암호화) | secret_ref로만 주입 ([11](11-cluster-topology.md)) |
| 운영자 secret | CP 시크릿 스토어 (암호화) | secret_ref로만 주입, 로그·params 평문 금지 |

### 암호화 모델 (app-level)

```
마스터 키(KEK): 파일(0600) 또는 env (CP 부팅 시 로드)
   └ 각 시크릿: 랜덤 DEK로 암호화(AES-GCM), DEK는 KEK로 래핑(envelope)
저장: secrets(value_enc, dek_wrapped) — Postgres
복호: CP 메모리에서만, 사용 즉시 폐기. 로그·API 응답에 평문 비노출(UI는 "설정됨"만)
```

### 통합 시크릿 테이블 (P1-3 secret_refs의 백엔드)

```sql
secrets (
  ref text PK,                  -- secret_ref 식별자 (RunJob.secret_refs 가 참조)
  scope text,                   -- cluster:<id> | global | node:<id>
  value_enc bytea, dek_wrapped bytea,
  created_by text, created_at timestamptz
);
```
- node-token도 이 모델의 한 사례(scope=cluster). 운영자 제공 secret(레지스트리 인증 등)도 동일.
- 에이전트는 RunJob.secret_refs를 받아 **주입 시점에만** CP에서 복호값을 mTLS로 수령, 디스크 평문 미기록.

## 키 회전·백업 (운영 메모)
- 마스터 키 회전: 새 KEK로 DEK 재래핑(점진). MVP는 수동 절차로 둠.
- 마스터 키 분실 = 모든 시크릿 복구 불가 → 운영자 백업 필수(문서 경고).
- CA·cosign 키 분실 대비는 각 문서(02·06) 후속 항목.

## 미해결/후속
- KMS/Vault 승격 경로 (보안 강화 단계)
- 마스터 키 자동 회전·HSM
- 번들 GC 보호 K값 운영 튜닝
