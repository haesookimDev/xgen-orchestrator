// Package gpu — GPU 인벤토리/메트릭 수집기.
//
// 설계 결정(docs/design/00-overview.md): "nvidia-smi 시작 -> NVML 승격".
// 이 인터페이스가 구현 교체를 인터페이스 뒤에서만 일어나게 못박는다.
// 베어 노드(k8s/DCGM 설치 이전)에서 호스트 직접 수집해야 하므로 nvidia-smi가 기본.
package gpu

import "context"

// Device — 정적 GPU 인벤토리 1장.
type Device struct {
	Model         string
	Index         uint32
	VRAMBytes     uint64
	DriverVersion string
	CUDAVersion   string
	MIGEnabled    bool
}

// Sample — 동적 GPU 메트릭 1장 (util/VRAM/온도/전력).
type Sample struct {
	Index       uint32
	UtilPercent float64
	VRAMUsed    uint64
	TempC       float64
	PowerWatts  float64
}

// Collector — GPU 수집기. 구현체: nvidiasmi(기본), 향후 nvml/dcgm.
type Collector interface {
	// Available — 이 노드에서 사용 가능한지(드라이버/도구 존재).
	Available() bool
	// Inventory — 정적 인벤토리 (등록 시 1회 + 변경 감지).
	Inventory(ctx context.Context) ([]Device, error)
	// Sample — 동적 메트릭 (주기 수집).
	Sample(ctx context.Context) ([]Sample, error)
}

// Default — 노드 환경에 맞는 수집기 선택. 현재는 nvidia-smi.
func Default() Collector { return &nvidiaSMI{} }
