// Package inventory — HW 인벤토리 수집 → proto InventoryReport.
// GPU(nvidia-smi→NVML) + 호스트(CPU/메모리/디스크/OS/가상화). 변경 감지는 content_hash.
// 설계: docs/design/03-grpc-protocol.md, 04-data-model.md
package inventory

import (
	"context"
	"crypto/sha256"
	"encoding/hex"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
	"github.com/xgen/orchestrator/agent/internal/inventory/gpu"
	"google.golang.org/protobuf/proto"
)

// Collect — 1회 인벤토리 수집 → proto InventoryReport.
func Collect(ctx context.Context) (*pb.InventoryReport, error) {
	rep := &pb.InventoryReport{}

	// GPU (베어 노드 호스트 직접 수집; nvidia-smi 기본, NVML 승격)
	g := gpu.Default()
	if g.Available() {
		if devs, err := g.Inventory(ctx); err == nil {
			for _, d := range devs {
				rep.Gpus = append(rep.Gpus, &pb.GPUInfo{
					Model:         d.Model,
					Index:         d.Index,
					VramBytes:     d.VRAMBytes,
					DriverVersion: d.DriverVersion,
					CudaVersion:   d.CUDAVersion,
					MigEnabled:    d.MIGEnabled,
				})
			}
		}
	}

	// 호스트 CPU/메모리/디스크/OS/가상화 — OS별 구현(collectHost).
	collectHost(rep)

	rep.ContentHash = contentHash(rep)
	return rep, nil
}

// contentHash — ContentHash를 제외한 결정적 marshal의 sha256.
func contentHash(r *pb.InventoryReport) string {
	r.ContentHash = ""
	b, _ := proto.MarshalOptions{Deterministic: true}.Marshal(r)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}
