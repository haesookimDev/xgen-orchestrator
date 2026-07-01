// 런타임 가용성 감지 — pre-flight 게이트용 (15-real-infra-packaging.md §2).
// WSL 에이전트에서 docker(Desktop WSL integration)·compose·k3s 사용 가능 여부를 보고.
package inventory

import (
	"context"
	"os/exec"
	"time"
)

// detectRuntimes — 각 런타임을 짧은 timeout으로 프로빙. 실패=false.
func detectRuntimes(ctx context.Context) map[string]bool {
	return map[string]bool{
		"docker":  probe(ctx, "docker", "info"),
		"compose": probe(ctx, "docker", "compose", "version"),
		"k3s":     probe(ctx, "k3s", "--version") || probe(ctx, "kubectl", "version", "--client"),
	}
}

func probe(ctx context.Context, name string, args ...string) bool {
	c, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if _, err := exec.LookPath(name); err != nil {
		return false
	}
	return exec.CommandContext(c, name, args...).Run() == nil
}
