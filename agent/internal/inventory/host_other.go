//go:build !linux && !darwin

// 호스트 인벤토리 (Linux/darwin 외) — 최소 정보(빌드 가능성 보장용).
package inventory

import (
	"runtime"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
)

func collectHost(rep *pb.InventoryReport) {
	rep.Cpu = &pb.CPUInfo{Arch: runtime.GOARCH, LogicalCores: uint32(runtime.NumCPU())}
	rep.Os = &pb.OSInfo{Name: runtime.GOOS}
	rep.Virt = &pb.Virtualization{Type: "unknown"}
}

// HostMem — 미지원 플랫폼.
func HostMem() (used, total uint64) { return 0, 0 }
