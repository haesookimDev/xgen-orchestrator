// Package transport — 단일 outbound bidi gRPC stream (AgentStream.Connect).
// 1차: Hello + Heartbeat (노드 online/last_seen). 인벤토리/메트릭/로그는 후속.
// TODO: mTLS(client cert) + 서버측 status 게이트. 현재는 insecure + node_id.
// 설계: docs/design/03-grpc-protocol.md
package transport

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log"
	"os"
	"time"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
	"github.com/xgen/orchestrator/agent/internal/config"
	"github.com/xgen/orchestrator/agent/internal/inventory"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
)

const heartbeatInterval = 10 * time.Second

// clientTLS — 등록으로 받은 client cert/key + CA로 mTLS 자격증명 구성.
// ServerName 기본값은 dial 호스트; XGEN_GRPC_SERVER_NAME 로 override 가능.
func clientTLS(cfg *config.Config) (credentials.TransportCredentials, error) {
	cert, err := tls.LoadX509KeyPair(cfg.CertPath(), cfg.KeyPath())
	if err != nil {
		return nil, err
	}
	caPEM, err := os.ReadFile(cfg.CAPath())
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("invalid CA bundle %s", cfg.CAPath())
	}
	tc := &tls.Config{Certificates: []tls.Certificate{cert}, RootCAs: pool}
	if sn := os.Getenv("XGEN_GRPC_SERVER_NAME"); sn != "" {
		tc.ServerName = sn
	}
	return credentials.NewTLS(tc), nil
}

// Run — stream 수명주기. ctx 취소까지 유지.
func Run(ctx context.Context, cfg *config.Config) error {
	creds, err := clientTLS(cfg)
	if err != nil {
		return fmt.Errorf("mTLS: %w", err)
	}
	conn, err := grpc.NewClient(cfg.GRPCServer, grpc.WithTransportCredentials(creds))
	if err != nil {
		return err
	}
	defer conn.Close()

	stream, err := pb.NewAgentStreamClient(conn).Connect(ctx)
	if err != nil {
		return err
	}

	// Hello (연결 직후 1회) — CP가 노드를 online 으로 표시.
	if err := stream.Send(&pb.AgentMessage{
		NodeId:  cfg.NodeID(),
		Payload: &pb.AgentMessage_Hello{Hello: &pb.Hello{AgentVersion: "0.1.0"}},
	}); err != nil {
		return err
	}
	log.Printf("stream: connected to %s as node_id=%s", cfg.GRPCServer, cfg.NodeID())

	// 인벤토리 1회 보고 (변경 감지는 후속). CP가 node_inventory/node_gpus 저장.
	if rep, err := inventory.Collect(ctx); err == nil {
		if err := stream.Send(&pb.AgentMessage{
			NodeId:  cfg.NodeID(),
			Payload: &pb.AgentMessage_Inventory{Inventory: rep},
		}); err != nil {
			log.Printf("stream: inventory send failed: %v", err)
		} else {
			log.Printf("stream: inventory sent (cpu=%q gpus=%d hash=%.12s)",
				rep.GetCpu().GetModel(), len(rep.GetGpus()), rep.GetContentHash())
		}
	}

	// 하행 수신 (HelloAck/Ping/Command) — 현재는 로깅만.
	go func() {
		for {
			msg, err := stream.Recv()
			if err != nil {
				return
			}
			if msg.GetHelloAck() != nil {
				log.Printf("stream: HelloAck (resync=%v)", msg.GetHelloAck().GetResyncRequired())
			}
		}
	}()

	// heartbeat
	t := time.NewTicker(heartbeatInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			if err := stream.Send(&pb.AgentMessage{
				NodeId:  cfg.NodeID(),
				Payload: &pb.AgentMessage_Heartbeat{Heartbeat: &pb.Heartbeat{TsUnixMs: time.Now().UnixMilli()}},
			}); err != nil {
				log.Printf("stream: heartbeat send failed: %v", err)
				return err
			}
		}
	}
}
