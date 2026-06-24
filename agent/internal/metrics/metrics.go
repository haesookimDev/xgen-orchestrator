// Package metrics — 동적 메트릭 주기 수집 → MetricBatch (stream으로 push, CP가 VM에 기록).
// node_up + 메모리 + GPU(util/mem/temp/power). 오프라인 시 drop (03-grpc-protocol).
package metrics

import (
	"context"
	"strconv"
	"time"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
	"github.com/xgen/orchestrator/agent/internal/inventory"
	"github.com/xgen/orchestrator/agent/internal/inventory/gpu"
)

// Collect — 1회 메트릭 스냅샷.
func Collect(ctx context.Context, nodeID string) *pb.MetricBatch {
	now := time.Now().UnixMilli()
	node := map[string]string{"node_id": nodeID}
	pts := []*pb.MetricPoint{
		{Name: "xgen_node_up", Labels: node, Value: 1, TsUnixMs: now},
	}

	used, total := inventory.HostMem()
	if total > 0 {
		pts = append(pts,
			&pb.MetricPoint{Name: "xgen_mem_total_bytes", Labels: node, Value: float64(total), TsUnixMs: now},
			&pb.MetricPoint{Name: "xgen_mem_used_bytes", Labels: node, Value: float64(used), TsUnixMs: now},
		)
	}

	g := gpu.Default()
	if g.Available() {
		if samples, err := g.Sample(ctx); err == nil {
			for _, s := range samples {
				gl := map[string]string{"node_id": nodeID, "gpu": strconv.Itoa(int(s.Index))}
				pts = append(pts,
					&pb.MetricPoint{Name: "xgen_gpu_utilization_percent", Labels: gl, Value: s.UtilPercent, TsUnixMs: now},
					&pb.MetricPoint{Name: "xgen_gpu_mem_used_bytes", Labels: gl, Value: float64(s.VRAMUsed), TsUnixMs: now},
					&pb.MetricPoint{Name: "xgen_gpu_temp_celsius", Labels: gl, Value: s.TempC, TsUnixMs: now},
					&pb.MetricPoint{Name: "xgen_gpu_power_watts", Labels: gl, Value: s.PowerWatts, TsUnixMs: now},
				)
			}
		}
	}
	return &pb.MetricBatch{Points: pts}
}
