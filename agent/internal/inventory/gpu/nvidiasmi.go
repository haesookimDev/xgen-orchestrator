package gpu

import (
	"context"
	"os/exec"
	"strconv"
	"strings"
)

// nvidiaSMI — nvidia-smi --query-gpu 호출/파싱 기반 수집기 (의존성 없음, MVP 기본).
// 향후 NVML 바인딩 구현(nvml.go)으로 승격 가능 — Collector 인터페이스 뒤에서만 교체.
type nvidiaSMI struct{}

const (
	// 정적 인벤토리 쿼리. nounits -> memory.total 은 MiB.
	invQuery    = "name,index,memory.total,driver_version,mig.mode.current"
	sampleQuery = "index,utilization.gpu,memory.used,temperature.gpu,power.draw"
)

func (n *nvidiaSMI) Available() bool {
	_, err := exec.LookPath("nvidia-smi")
	return err == nil
}

func (n *nvidiaSMI) Inventory(ctx context.Context) ([]Device, error) {
	out, err := n.run(ctx, invQuery)
	if err != nil {
		return nil, err
	}
	return parseInventoryCSV(out), nil
}

func (n *nvidiaSMI) Sample(ctx context.Context) ([]Sample, error) {
	out, err := n.run(ctx, sampleQuery)
	if err != nil {
		return nil, err
	}
	return parseSampleCSV(out), nil
}

func (n *nvidiaSMI) run(ctx context.Context, query string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "nvidia-smi",
		"--query-gpu="+query, "--format=csv,noheader,nounits")
	return cmd.Output()
}

// parseInventoryCSV — "name, index, memory.total[MiB], driver, mig.mode" 줄들을 파싱.
func parseInventoryCSV(out []byte) []Device {
	var devs []Device
	for _, f := range splitRows(out, 5) {
		devs = append(devs, Device{
			Model:         f[0],
			Index:         uint32(atoiSafe(f[1])),
			VRAMBytes:     mibToBytes(f[2]),
			DriverVersion: f[3],
			MIGEnabled:    strings.EqualFold(f[4], "Enabled"),
			// CUDAVersion: query-gpu 미지원 -> NVML 승격 시 채움.
		})
	}
	return devs
}

// parseSampleCSV — "index, util%, mem.used[MiB], temp[C], power[W]" 줄들을 파싱.
func parseSampleCSV(out []byte) []Sample {
	var samples []Sample
	for _, f := range splitRows(out, 5) {
		samples = append(samples, Sample{
			Index:       uint32(atoiSafe(f[0])),
			UtilPercent: atofSafe(f[1]),
			VRAMUsed:    mibToBytes(f[2]),
			TempC:       atofSafe(f[3]),
			PowerWatts:  atofSafe(f[4]),
		})
	}
	return samples
}

// splitRows — CSV 출력을 행별로 쪼개고 컬럼 수가 min 이상인 행만 trim해서 반환.
func splitRows(out []byte, min int) [][]string {
	var rows [][]string
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.Split(line, ",")
		if len(parts) < min {
			continue
		}
		for i := range parts {
			parts[i] = strings.TrimSpace(parts[i])
		}
		rows = append(rows, parts)
	}
	return rows
}

// nvidia-smi nounits 는 MiB. 미지원/[N/A] 값은 0.
func mibToBytes(s string) uint64 {
	v := atoiSafe(s)
	if v <= 0 {
		return 0
	}
	return uint64(v) * 1024 * 1024
}

func atoiSafe(s string) int {
	v, err := strconv.Atoi(strings.TrimSpace(s))
	if err != nil {
		return 0 // [N/A], [Not Supported] 등
	}
	return v
}

func atofSafe(s string) float64 {
	v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil {
		return 0
	}
	return v
}
