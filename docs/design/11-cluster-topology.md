# xgen-orchestrator — 클러스터 토폴로지 / 멀티노드 (Cluster Topology)

> 추가 설계 ①. 노드 단위 Job([05](05-job-orchestration.md))을 넘어 다중 노드 k3s 클러스터를
> 조율. 원 요구사항("여러 서버/VM")과 xgen-infra `setup-k3s-agent.sh`·`setup-k3s-ha.sh` 연계.

## 결정 (Lock)

| 항목 | 결정 | 함의 |
|------|------|------|
| 클러스터 모델 | **명시적 Cluster 엔티티** | 노드가 cluster_id·role 보유, 조율·집계의 1급 객체 |
| 설치 조율 | **CP가 클러스터 플랜 조율** | 운영자는 "클러스터 설치" 1번, CP가 server→worker 순서 |
| node-token | **CP 암호화 보관 + 재사용** | secret_refs로 안전 전달, 워커 추가·재조인에 재사용 |
| v1 범위 | **단일노드 + 워커 조인** (1 server + N worker) | HA(server 3대)는 후속 |

## 문제 — 1:1에서 1:다로

```
지금까지:  [Job] → [노드 1개]
필요:      [클러스터 설치] → [server 노드 + worker 노드 N]  (순서·시크릿 의존)
```
k3s는 server가 먼저 뜨고 **node-token 발급** → worker가 그 토큰으로 조인. Agent-pull이라
노드 간 직접 통신 불가 → **CP가 토큰을 중개**.

## 데이터 모델 (C 확장)

```sql
clusters (
  id uuid PK,
  name text, runtime text,          -- k3s (v1)
  solution_id text, version text,
  server_url text,                  -- worker 조인 대상 (https://<server>:6443)
  status text,                      -- forming|ready|degraded
  created_at timestamptz
);
-- 노드에 클러스터 소속·역할 부여
ALTER TABLE nodes ADD cluster_id uuid REFERENCES clusters;
ALTER TABLE nodes ADD cluster_role text;   -- server | worker (null=standalone)

-- node-token 등 클러스터 시크릿 (암호화 저장, P1-3 secret_refs 대상)
cluster_secrets (
  cluster_id uuid REFERENCES clusters ON DELETE CASCADE,
  key text,                         -- 'k3s_node_token'
  value_enc bytea,                  -- 암호화 보관 (평문/로그 금지)
  PRIMARY KEY (cluster_id, key)
);
```

## 클러스터 설치 플랜 (CP 조율)

```
[운영자] "클러스터 C 설치: server=노드A, worker=[노드B,노드C], k3s"
   └ CP 클러스터 설치 워크플로 (다단계, 각 단계는 노드 단위 Job)
        ① 노드A에 RunJob(setup-k3s.sh install, role=server) → 완료 대기
        ② 노드A 에이전트가 /var/lib/rancher/k3s/server/node-token 수확
              → CP 보고 → cluster_secrets 에 암호화 저장
              (값은 secret_ref 로만 흐름 — params·job_logs 평문 금지, P1-3)
        ③ CP가 노드B,C 에 RunJob(setup-k3s-agent.sh join,
              server_url + secret_ref=k3s_node_token) 병렬
        ④ 전 노드 ready → clusters.status=ready
```
- 단계 간 의존(② 토큰이 ③의 입력)은 CP가 보장. 노드당 mutating Job 1개 락(P1-2)과 호환.
- 실패 시: 부분 성공 클러스터는 `degraded`, 운영자가 실패 노드만 재시도.

## node-token 취급 (CP 암호화 보관 + 재사용)

```
수확: server 에이전트가 토큰 파일 읽어 CP 보고
저장: cluster_secrets.value_enc (CP 키로 암호화)
재사용: 이후 worker 추가·재조인 시 secret_ref 로 주입 (재수확 불필요)
노출: params·로그·UI 어디에도 평문 금지. UI는 "설정됨" 표시만.
```

## 클러스터 인벤토리 집계

노드별 인벤토리(C)를 **클러스터 단위 합산**:
```
cluster.total_gpus = Σ node_gpus,  cluster.available_gpus = total - 사용중
```
- 멀티노드 Pre-flight(클러스터 전체 자원으로 판단), 스케줄링, **G의 자동증설 판단** 근거.
- "워커 추가" 액션 = 새 노드 등록 → 클러스터 join Job → 집계 자동 갱신.

## 워커 추가/제거 (Day-2)

```
추가: 노드 등록(02) → CP가 cluster_secrets 재사용해 join Job → cluster_role=worker
제거: drain Job(선택) → setup-k3s-agent.sh uninstall → cluster_id=null
```

## 미해결/후속
- HA(server 3대): server 조인 순서·etcd quorum·VIP — setup-k3s-ha.sh 연계, 후속
- k8s(비-k3s) 런타임 클러스터 조율
- 클러스터 단위 status/health 집계 스키마
- 노드 장애 시 클러스터 자동 reconcile (G 자율성과 연계)
