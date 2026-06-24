"""grpcio — AgentStream.Connect 종단 (에이전트 단일 bidi stream).

상행: 인벤토리/메트릭(VM)/로그(job_logs)/JobUpdate. 하행: 명령(at-least-once).
mTLS: cert 주체(spiffe node_id) ↔ 메시지 node_id 매칭, nodes.status 게이트.
설계: docs/design/03-grpc-protocol.md, 13-threat-model.md.

NOTE: `make proto` 후 생성되는 gen/ 스텁(AgentStreamServicer)을 상속한다.
"""


class AgentStreamService:
    """make proto 후 orchestrator.v1 AgentStreamServicer 상속으로 교체."""

    def Connect(self, request_iterator, context):
        # 0. mTLS peer cert에서 spiffe node_id 추출 -> 메시지 node_id 매칭, status 검사
        # 1. Hello 수신 -> HelloAck (필요 시 resync)
        # 2. 상행 멀티플렉싱 처리:
        #    InventoryReport -> node_inventory(+history) + node_gpus (content_hash 비교)
        #    MetricBatch     -> VictoriaMetrics write
        #    LogBatch        -> job_logs insert (job_id,source,offset dedup)
        #    JobUpdate       -> jobs 갱신 (phase_seq idempotent)
        #    CommandAck      -> commands.acked_at
        # 3. 하행: 대기 명령을 ServerMessage.command 로 송신, ack 추적
        raise NotImplementedError
