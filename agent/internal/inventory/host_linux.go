//go:build linux

// 호스트 인벤토리 (Linux) — /proc·statfs 직접 수집. 베어 노드(DCGM/k8s 이전)에서 동작.
package inventory

import (
	"bufio"
	"os"
	"runtime"
	"strconv"
	"strings"
	"syscall"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
)

func collectHost(rep *pb.InventoryReport) {
	rep.Cpu = collectCPU()
	rep.Memory = &pb.MemoryInfo{TotalBytes: memTotalBytes()}
	if d := rootDisk(); d != nil {
		rep.Disks = []*pb.DiskInfo{d}
	}
	rep.Os = collectOS()
	rep.Virt = collectVirt()
}

func collectCPU() *pb.CPUInfo {
	c := &pb.CPUInfo{Arch: runtime.GOARCH, LogicalCores: uint32(runtime.NumCPU())}
	f, err := os.Open("/proc/cpuinfo")
	if err != nil {
		return c
	}
	defer f.Close()
	phys := map[string]bool{}
	cores := map[string]bool{}
	var curPhys string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		k, v, ok := splitSep(sc.Text(), ':')
		if !ok {
			continue
		}
		switch k {
		case "model name":
			if c.Model == "" {
				c.Model = v
			}
		case "physical id":
			curPhys = v
			phys[v] = true
		case "core id":
			cores[curPhys+"/"+v] = true
		}
	}
	c.Sockets = uint32(len(phys))
	if len(cores) > 0 {
		c.PhysicalCores = uint32(len(cores))
	}
	return c
}

func memTotalBytes() uint64 {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if strings.HasPrefix(sc.Text(), "MemTotal:") {
			if fields := strings.Fields(sc.Text()); len(fields) >= 2 {
				kb, _ := strconv.ParseUint(fields[1], 10, 64)
				return kb * 1024
			}
		}
	}
	return 0
}

func rootDisk() *pb.DiskInfo {
	var st syscall.Statfs_t
	if err := syscall.Statfs("/", &st); err != nil {
		return nil
	}
	return &pb.DiskInfo{Mount: "/", TotalBytes: uint64(st.Blocks) * uint64(st.Bsize)}
}

func collectOS() *pb.OSInfo {
	o := &pb.OSInfo{}
	if b, err := os.ReadFile("/proc/sys/kernel/osrelease"); err == nil {
		o.Kernel = strings.TrimSpace(string(b))
	}
	if f, err := os.Open("/etc/os-release"); err == nil {
		defer f.Close()
		sc := bufio.NewScanner(f)
		for sc.Scan() {
			k, v, ok := splitSep(sc.Text(), '=')
			if !ok {
				continue
			}
			v = strings.Trim(v, "\"")
			switch k {
			case "NAME":
				o.Name = v
			case "VERSION_ID":
				o.Version = v
			}
		}
	}
	return o
}

func collectVirt() *pb.Virtualization {
	v := &pb.Virtualization{Type: "bare"}
	if b, err := os.ReadFile("/proc/cpuinfo"); err == nil && strings.Contains(string(b), "hypervisor") {
		v.Type = "vm"
	}
	if _, err := os.Stat("/.dockerenv"); err == nil {
		v.ContainerRuntime = true
	}
	return v
}

func splitSep(line string, sep byte) (string, string, bool) {
	i := strings.IndexByte(line, sep)
	if i < 0 {
		return "", "", false
	}
	return strings.TrimSpace(line[:i]), strings.TrimSpace(line[i+1:]), true
}
