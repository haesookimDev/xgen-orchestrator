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
	"sync"
	"time"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
	"github.com/xgen/orchestrator/agent/internal/config"
	"github.com/xgen/orchestrator/agent/internal/executor"
	"github.com/xgen/orchestrator/agent/internal/inventory"
	"github.com/xgen/orchestrator/agent/internal/metrics"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
)

const (
	heartbeatInterval = 10 * time.Second
	metricsInterval   = 10 * time.Second
)

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

	// 연결 단위 컨텍스트 — stream이 끊기면 connCancel로 모든 goroutine·ticker 정리.
	connCtx, connCancel := context.WithCancel(ctx)
	defer connCancel()

	stream, err := pb.NewAgentStreamClient(conn).Connect(connCtx)
	if err != nil {
		return err
	}

	// stream 사멸 신호 — sender/recv goroutine이 실패 시 1회 전달, Run이 반환하여 재연결.
	streamErr := make(chan error, 2)
	fail := func(err error) {
		select {
		case streamErr <- err:
		default:
		}
		connCancel()
	}

	// 단일 송신 경로 — 여러 producer(hello/inventory/heartbeat/executor)가 동시에
	// stream.Send 하면 unsafe하므로 sendCh로 직렬화.
	sendCh := make(chan *pb.AgentMessage, 64)
	send := func(m *pb.AgentMessage) {
		select {
		case sendCh <- m:
		case <-connCtx.Done():
		}
	}
	go func() {
		for {
			select {
			case <-connCtx.Done():
				return
			case m := <-sendCh:
				if err := stream.Send(m); err != nil {
					log.Printf("stream: send failed: %v", err)
					fail(err)
					return
				}
			}
		}
	}()

	// Hello (연결 직후 1회) — CP가 노드를 online 으로 표시.
	send(&pb.AgentMessage{NodeId: cfg.NodeID(), Payload: &pb.AgentMessage_Hello{Hello: &pb.Hello{AgentVersion: "0.1.0"}}})
	log.Printf("stream: connected to %s as node_id=%s", cfg.GRPCServer, cfg.NodeID())

	// 인벤토리 1회 보고. CP가 node_inventory/node_gpus 저장.
	if rep, err := inventory.Collect(ctx); err == nil {
		send(&pb.AgentMessage{NodeId: cfg.NodeID(), Payload: &pb.AgentMessage_Inventory{Inventory: rep}})
		log.Printf("stream: inventory sent (cpu=%q gpus=%d hash=%.12s)",
			rep.GetCpu().GetModel(), len(rep.GetGpus()), rep.GetContentHash())
	}

	// 실행 중 Job의 취소 함수 레지스트리 (CancelJob 처리용).
	var jobsMu sync.Mutex
	jobCancels := map[string]context.CancelFunc{}

	// 하행 수신 — RunJob 디스패치(취소 가능), CancelJob, HelloAck.
	go func() {
		for {
			msg, err := stream.Recv()
			if err != nil {
				fail(err)
				return
			}
			c := msg.GetCommand()
			if c == nil {
				if msg.GetHelloAck() != nil {
					log.Printf("stream: HelloAck (resync=%v)", msg.GetHelloAck().GetResyncRequired())
				}
				continue
			}
			if rj := c.GetRunJob(); rj != nil {
				jobCtx, jc := context.WithCancel(connCtx)
				jobsMu.Lock()
				jobCancels[rj.GetJobId()] = jc
				jobsMu.Unlock()
				log.Printf("stream: RunJob job=%s action=%s", rj.GetJobId(), rj.GetAction())
				go func(rj2 *pb.RunJob, cmdID string) {
					defer func() {
						jobsMu.Lock()
						delete(jobCancels, rj2.GetJobId())
						jobsMu.Unlock()
						jc()
					}()
					executor.Run(jobCtx, cfg.NodeID(), sendCh, cmdID, rj2, cfg.BundlePubPath())
				}(rj, c.GetCommandId())
			} else if cj := c.GetCancel(); cj != nil {
				log.Printf("stream: CancelJob job=%s", cj.GetJobId())
				jobsMu.Lock()
				if fn := jobCancels[cj.GetJobId()]; fn != nil {
					fn()
				}
				jobsMu.Unlock()
			}
		}
	}()

	// 동적 메트릭 주기 push (CP가 VictoriaMetrics에 기록).
	go func() {
		mt := time.NewTicker(metricsInterval)
		defer mt.Stop()
		for {
			select {
			case <-connCtx.Done():
				return
			case <-mt.C:
				send(&pb.AgentMessage{NodeId: cfg.NodeID(), Payload: &pb.AgentMessage_Metrics{Metrics: metrics.Collect(ctx, cfg.NodeID())}})
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
		case err := <-streamErr:
			return fmt.Errorf("stream closed: %w", err)
		case <-t.C:
			send(&pb.AgentMessage{NodeId: cfg.NodeID(), Payload: &pb.AgentMessage_Heartbeat{Heartbeat: &pb.Heartbeat{TsUnixMs: time.Now().UnixMilli()}}})
		}
	}
}
