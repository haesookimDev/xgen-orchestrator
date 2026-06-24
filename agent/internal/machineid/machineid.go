// Package machineid — 노드 안정 식별자(/etc/machine-id). 재등록 매칭 키.
// 설계: docs/design/02-enrollment-security.md, 04-data-model.md
package machineid

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// 표준 경로(우선순위). 컨테이너/테스트는 XGEN_MACHINE_ID 로 덮어쓸 수 있다.
var paths = []string{"/etc/machine-id", "/var/lib/dbus/machine-id"}

// Get — 시스템 machine-id 반환 (XGEN_MACHINE_ID > /etc/machine-id > dbus).
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

// GetOrCreate — 시스템 machine-id가 없으면(예: macOS) dir/machine-id 에 생성·영속해 안정 ID 제공.
// Linux 노드는 시스템 값을 그대로 쓰고, 그 외 환경(개발용 darwin 등)에서도 동작하게 한다.
func GetOrCreate(dir string) (string, error) {
	if id, err := Get(); err == nil {
		return id, nil
	}
	p := filepath.Join(dir, "machine-id")
	if b, err := os.ReadFile(p); err == nil {
		if id := strings.TrimSpace(string(b)); id != "" {
			return id, nil
		}
	}
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	id := hex.EncodeToString(buf)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	if err := os.WriteFile(p, []byte(id), 0o644); err != nil {
		return "", err
	}
	return id, nil
}
