// Package machineid — 노드 안정 식별자(/etc/machine-id). 재등록 매칭 키.
// 설계: docs/design/02-enrollment-security.md, 04-data-model.md
package machineid

import (
	"errors"
	"os"
	"strings"
)

// 표준 경로(우선순위). 컨테이너/테스트는 XGEN_MACHINE_ID 로 덮어쓸 수 있다.
var paths = []string{"/etc/machine-id", "/var/lib/dbus/machine-id"}

// Get — 노드 machine-id 반환.
func Get() (string, error) {
	if v := strings.TrimSpace(os.Getenv("XGEN_MACHINE_ID")); v != "" {
		return v, nil
	}
	for _, p := range paths {
		b, err := os.ReadFile(p)
		if err == nil {
			if id := strings.TrimSpace(string(b)); id != "" {
				return id, nil
			}
		}
	}
	return "", errors.New("machine-id not found")
}
