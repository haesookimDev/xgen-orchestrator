//go:build darwin

// 호스트 인벤토리 (macOS) — sysctl(8) 파싱. 개발용 노드(darwin)에서 동작하게 한다.
package inventory

import (
	"os/exec"
	"runtime"
	"strconv"
	"strings"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
)

func collectHost(rep *pb.InventoryReport) {
	cpu := &pb.CPUInfo{Arch: runtime.GOARCH, LogicalCores: uint32(runtime.NumCPU())}
	cpu.Model = sysctlStr("machdep.cpu.brand_string")
	rep.Cpu = cpu
	rep.Memory = &pb.MemoryInfo{TotalBytes: sysctlUint("hw.memsize")}
	rep.Os = &pb.OSInfo{Name: "macOS"}
	rep.Virt = &pb.Virtualization{Type: "bare"}
}

func sysctlStr(key string) string {
	out, err := exec.Command("sysctl", "-n", key).Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func sysctlUint(key string) uint64 {
	v, _ := strconv.ParseUint(sysctlStr(key), 10, 64)
	return v
}
