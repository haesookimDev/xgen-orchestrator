// xgen-agent — 노드별 CLI 에이전트 (단일 정적 바이너리, systemd 서비스).
// 1차 슬라이스: 등록 -> 인벤토리 -> 메트릭/로그 stream.
// 설계: docs/design/02-enrollment-security.md, 03-grpc-protocol.md
package main

import (
	"context"
	"errors"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/xgen/orchestrator/agent/internal/config"
	"github.com/xgen/orchestrator/agent/internal/enroll"
	"github.com/xgen/orchestrator/agent/internal/transport"
)

func main() {
	// 시그널 컨텍스트: Ctrl-C/SIGTERM까지 정상 대기 (Background의 nil Done() deadlock 방지).
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	// 최초 부팅이면 등록(REST POST /v1/enroll): CSR 생성 -> client cert 수령.
	if !cfg.Enrolled() {
		if err := enroll.Run(ctx, cfg); err != nil {
			log.Fatalf("enroll: %v", err)
		}
		log.Printf("enrolled as node_id=%s", cfg.NodeID())
	} else {
		log.Printf("already enrolled as node_id=%s", cfg.NodeID())
	}

	// 단일 outbound mTLS bidi stream 수립 -> 인벤토리/메트릭/로그 push, 명령 수신.
	if err := transport.Run(ctx, cfg); err != nil && !errors.Is(err, context.Canceled) {
		log.Fatalf("stream: %v", err)
	}
	log.Println("shutdown")
}
