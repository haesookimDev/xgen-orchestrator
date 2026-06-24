package gpu

import (
	"context"
	"os/exec"
)

// nvidiaSMI — nvidia-smi --query-gpu 호출/파싱 기반 수집기 (의존성 없음, MVP 기본).
// 향후 NVML 바인딩 구현(nvml.go)으로 승격 가능 — Collector 인터페이스 뒤에서만 교체.
type nvidiaSMI struct{}

func (n *nvidiaSMI) Available() bool {
	_, err := exec.LookPath("nvidia-smi")
	return err == nil
}

func (n *nvidiaSMI) Inventory(ctx context.Context) ([]Device, error) {
	// TODO: nvidia-smi --query-gpu=name,index,memory.total,driver_version,...
	//       --format=csv,noheader,nounits 호출 후 파싱.
	return nil, nil
}

func (n *nvidiaSMI) Sample(ctx context.Context) ([]Sample, error) {
	// TODO: nvidia-smi --query-gpu=index,utilization.gpu,memory.used,temperature.gpu,power.draw
	return nil, nil
}
