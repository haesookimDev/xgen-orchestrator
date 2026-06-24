// Package transport — 단일 outbound mTLS bidi gRPC stream.
// 상행: 인벤토리/메트릭/로그/JobUpdate. 하행: 명령. 재연결: 지수 백오프 + Hello 재동기화.
// durable(job/log) 큐는 디스크 보관 후 재전송, 메트릭은 drop. 설계: 03-grpc-protocol.md
package transport

import (
	"context"
	"log"

	"github.com/xgen/orchestrator/agent/internal/config"
)

// Run — stream 수명주기. 끊김 시 백오프 재연결.
func Run(ctx context.Context, cfg *config.Config) error {
	// 1. mTLS dial -> AgentStream.Connect
	// 2. Hello{agent_version, last_acked_seq} 송신
	// 3. 고루틴:
	//    - 인벤토리: 등록 시 + 변경 감지(content_hash)
	//    - 메트릭: 주기 수집 -> push (오프라인 시 drop)
	//    - 로그: durable 큐 -> push (재전송, offset dedup)
	//    - 명령 수신: command_id 멱등 처리 -> ack
	// 4. heartbeat 주기 송신
	// TODO: 구현 (proto codegen 필요)
	log.Println("stream: stub — idling until shutdown (Ctrl-C). TODO: connect mTLS gRPC")
	<-ctx.Done()
	return ctx.Err()
}
