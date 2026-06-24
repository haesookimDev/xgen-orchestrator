// Package config — 에이전트 설정/상태 (/etc/xgen-agent/).
//
// 입력(server, join token)은 env로 받는다(install.sh/systemd가 주입):
//   XGEN_SERVER, XGEN_JOIN_TOKEN, XGEN_DIR(기본 /etc/xgen-agent)
// 영속 상태(node_id)는 <dir>/state.json. 인증서는 <dir>/{agent.key,agent.crt,ca.crt}.
// 설계: docs/design/02-enrollment-security.md
package config

import (
	"encoding/json"
	"os"
	"path/filepath"
)

const defaultDir = "/etc/xgen-agent"

// Config — 에이전트 런타임 설정.
type Config struct {
	Server    string // CP 주소 (https://<cp>)
	JoinToken string // 최초 부팅 시에만 (등록 후 사용 안 함)
	Dir       string // 설정/인증서 디렉토리

	state state // 영속 상태 (state.json)
}

type state struct {
	NodeID string `json:"node_id"`
}

// Load — env + state.json 로드.
func Load() (*Config, error) {
	dir := os.Getenv("XGEN_DIR")
	if dir == "" {
		dir = defaultDir
	}
	c := &Config{
		Server:    os.Getenv("XGEN_SERVER"),
		JoinToken: os.Getenv("XGEN_JOIN_TOKEN"),
		Dir:       dir,
	}
	// state.json 있으면 로드 (없으면 미등록 상태로 진행).
	if b, err := os.ReadFile(c.statePath()); err == nil {
		_ = json.Unmarshal(b, &c.state)
	}
	return c, nil
}

func (c *Config) KeyPath() string   { return filepath.Join(c.Dir, "agent.key") }
func (c *Config) CertPath() string  { return filepath.Join(c.Dir, "agent.crt") }
func (c *Config) CAPath() string    { return filepath.Join(c.Dir, "ca.crt") }
func (c *Config) statePath() string { return filepath.Join(c.Dir, "state.json") }

// NodeID — 등록으로 발급된 노드 식별자.
func (c *Config) NodeID() string { return c.state.NodeID }

// Enrolled — 이미 등록되어 node_id와 client cert를 보유하는지.
func (c *Config) Enrolled() bool {
	if c.state.NodeID == "" {
		return false
	}
	_, err := os.Stat(c.CertPath())
	return err == nil
}

// SetNodeID — 등록 성공 시 node_id 영속화.
func (c *Config) SetNodeID(id string) error {
	c.state.NodeID = id
	b, err := json.MarshalIndent(c.state, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(c.statePath(), b, 0o600)
}
