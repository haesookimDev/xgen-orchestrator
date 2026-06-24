// Package config — 에이전트 설정/상태 (/etc/xgen-agent/).
// 파일: agent.key(0600), agent.crt, ca.crt, config.yaml. 설계: 02-enrollment-security.md
package config

// Config — 에이전트 런타임 설정.
type Config struct {
	Server    string // CP 주소 (https://<cp>)
	NodeID    string // 등록 후 발급
	JoinToken string // 최초 부팅 시에만 (등록 후 폐기)
	CertPath  string // /etc/xgen-agent/agent.crt
	KeyPath   string // /etc/xgen-agent/agent.key (0600)
	CAPath    string // /etc/xgen-agent/ca.crt
}

// Load — config.yaml + 인증서 경로 로드.
func Load(path string) (*Config, error) {
	// TODO: YAML 파싱 + 파일 권한 검증(0600).
	return &Config{}, nil
}

// Enrolled — 이미 등록되어 client cert를 보유하는지.
func (c *Config) Enrolled() bool {
	return c.NodeID != "" // TODO: agent.crt 존재/유효성 검사
}
