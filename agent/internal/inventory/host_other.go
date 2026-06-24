//go:build !linux

// 호스트 인벤토리 (비-Linux) — 최소 정보. 에이전트는 Linux가 대상이나, darwin 등에서
// 빌드/로컬 테스트가 되도록 둔다.
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
