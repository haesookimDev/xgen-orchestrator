package gpu

import "testing"

func TestParseInventoryCSV(t *testing.T) {
	// nvidia-smi --query-gpu=name,index,memory.total,driver_version,mig.mode.current
	//   --format=csv,noheader,nounits  (2 GPU, 두 번째는 MIG Enabled)
	out := []byte(`NVIDIA A100-SXM4-80GB, 0, 81920, 535.104.05, Disabled
NVIDIA A100-SXM4-80GB, 1, 81920, 535.104.05, Enabled
`)
	devs := parseInventoryCSV(out)
	if len(devs) != 2 {
		t.Fatalf("got %d devices, want 2", len(devs))
	}
	d := devs[0]
	if d.Model != "NVIDIA A100-SXM4-80GB" {
		t.Errorf("model = %q", d.Model)
	}
	if d.Index != 0 {
		t.Errorf("index = %d, want 0", d.Index)
	}
	if d.VRAMBytes != 81920*1024*1024 {
		t.Errorf("vram = %d, want %d", d.VRAMBytes, 81920*1024*1024)
	}
	if d.DriverVersion != "535.104.05" {
		t.Errorf("driver = %q", d.DriverVersion)
	}
	if d.MIGEnabled {
		t.Error("gpu0 MIG should be Disabled")
	}
	if !devs[1].MIGEnabled {
		t.Error("gpu1 MIG should be Enabled")
	}
}

func TestParseSampleCSV(t *testing.T) {
	// index, utilization.gpu, memory.used, temperature.gpu, power.draw
	out := []byte(`0, 73, 40960, 61, 312.45
1, 0, 12, 35, 58.10
`)
	s := parseSampleCSV(out)
	if len(s) != 2 {
		t.Fatalf("got %d samples, want 2", len(s))
	}
	if s[0].Index != 0 || s[0].UtilPercent != 73 {
		t.Errorf("sample0 = %+v", s[0])
	}
	if s[0].VRAMUsed != 40960*1024*1024 {
		t.Errorf("vram used = %d", s[0].VRAMUsed)
	}
	if s[0].TempC != 61 || s[0].PowerWatts != 312.45 {
		t.Errorf("temp/power = %v/%v", s[0].TempC, s[0].PowerWatts)
	}
}

func TestParse_HandlesNAAndBlankLines(t *testing.T) {
	// MIG/power 미지원 장비: [N/A], [Not Supported] 와 빈 줄 섞임.
	out := []byte(`
Tesla T4, 0, 15360, 470.57.02, [N/A]

`)
	devs := parseInventoryCSV(out)
	if len(devs) != 1 {
		t.Fatalf("got %d devices, want 1", len(devs))
	}
	if devs[0].MIGEnabled {
		t.Error("[N/A] MIG must be false")
	}

	sampleOut := []byte("0, [Not Supported], 1024, 45, [N/A]\n")
	s := parseSampleCSV(sampleOut)
	if len(s) != 1 {
		t.Fatalf("got %d samples, want 1", len(s))
	}
	if s[0].UtilPercent != 0 || s[0].PowerWatts != 0 {
		t.Errorf("unsupported fields must be 0, got %+v", s[0])
	}
	if s[0].VRAMUsed != 1024*1024*1024 {
		t.Errorf("vram used = %d", s[0].VRAMUsed)
	}
}
