// Package inventory — 정적 HW 인벤토리 수집 (CPU/메모리/디스크/OS/가상화 + GPU).
// 베어 노드 호스트 직접 수집. 변경 감지는 content_hash. 설계: 03/04.
package inventory

import (
	"context"

	"github.com/xgen/orchestrator/agent/internal/inventory/gpu"
)

// Report — 수집 결과 (proto InventoryReport로 매핑).
type Report struct {
	GPUs        []gpu.Device
	ContentHash string
	// TODO: CPU/Memory/Disks/OS/Virtualization
}

// Collect — 1회 인벤토리 수집.
func Collect(ctx context.Context) (*Report, error) {
	g := gpu.Default()
	var devs []gpu.Device
	if g.Available() {
		devs, _ = g.Inventory(ctx)
	}
	// TODO: CPU/mem/disk/os/virt 수집 + content_hash 계산
	return &Report{GPUs: devs}, nil
}
