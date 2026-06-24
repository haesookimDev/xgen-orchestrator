// Package enroll — 최초 등록 (REST POST /v1/enroll).
//
// 로컬 키쌍 생성 -> CSR -> join_token으로 인증 -> CP 내부 CA가 서명한 client cert 수령.
// private key는 노드를 떠나지 않는다(CSR만 전송). TLS는 CP의 신뢰 CA로 검증(P0-1).
// 설계: docs/design/02-enrollment-security.md
package enroll

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"os"
	"runtime"

	"github.com/xgen/orchestrator/agent/internal/config"
	"github.com/xgen/orchestrator/agent/internal/machineid"
)

// Client — 등록에 사용할 HTTP 클라이언트. nil이면 http.DefaultClient(시스템 신뢰 CA).
// 테스트는 httptest 서버를 가리키도록 주입한다.
var Client *http.Client

type nodeInfo struct {
	Hostname  string `json:"hostname"`
	MachineID string `json:"machine_id"`
	OS        string `json:"os"`
	Arch      string `json:"arch"`
}

type enrollRequest struct {
	JoinToken string   `json:"join_token"`
	CSR       string   `json:"csr"` // PEM
	NodeInfo  nodeInfo `json:"node_info"`
}

type enrollResponse struct {
	NodeID     string `json:"node_id"`
	ClientCert string `json:"client_cert"` // PEM
	CABundle   string `json:"ca_bundle"`   // PEM
}

// Run — 등록 수행. 성공 시 key/cert/ca 저장 + node_id 영속화.
func Run(ctx context.Context, cfg *config.Config) error {
	if cfg.Server == "" {
		return fmt.Errorf("server not configured (XGEN_SERVER)")
	}
	if cfg.JoinToken == "" {
		return fmt.Errorf("join token not configured (XGEN_JOIN_TOKEN)")
	}

	mid, err := machineid.GetOrCreate(cfg.Dir)
	if err != nil {
		return fmt.Errorf("machine-id: %w", err)
	}

	// 1. 로컬 키쌍 + CSR. CN=xgen-node, SerialNumber=machine-id (재등록 매칭 키).
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return fmt.Errorf("keygen: %w", err)
	}
	csrPEM, err := buildCSR(key, mid)
	if err != nil {
		return fmt.Errorf("csr: %w", err)
	}

	// 2. POST /v1/enroll
	host, _ := os.Hostname()
	body, _ := json.Marshal(enrollRequest{
		JoinToken: cfg.JoinToken,
		CSR:       string(csrPEM),
		NodeInfo:  nodeInfo{Hostname: host, MachineID: mid, OS: runtime.GOOS, Arch: runtime.GOARCH},
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, cfg.Server+"/v1/enroll", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client().Do(req)
	if err != nil {
		return fmt.Errorf("enroll request: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return fmt.Errorf("enroll rejected: %s: %s", resp.Status, bytes.TrimSpace(b))
	}
	var er enrollResponse
	if err := json.NewDecoder(resp.Body).Decode(&er); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	if er.NodeID == "" || er.ClientCert == "" {
		return fmt.Errorf("incomplete enroll response")
	}

	// 3. 저장: key(0600), cert, ca. 그리고 node_id 영속화.
	if err := os.MkdirAll(cfg.Dir, 0o700); err != nil {
		return err
	}
	if err := writeKey(cfg.KeyPath(), key); err != nil {
		return fmt.Errorf("write key: %w", err)
	}
	if err := os.WriteFile(cfg.CertPath(), []byte(er.ClientCert), 0o644); err != nil {
		return fmt.Errorf("write cert: %w", err)
	}
	if er.CABundle != "" {
		if err := os.WriteFile(cfg.CAPath(), []byte(er.CABundle), 0o644); err != nil {
			return fmt.Errorf("write ca: %w", err)
		}
	}
	return cfg.SetNodeID(er.NodeID)
}

func buildCSR(key *ecdsa.PrivateKey, machineID string) ([]byte, error) {
	tmpl := &x509.CertificateRequest{
		Subject: pkix.Name{CommonName: "xgen-node", SerialNumber: machineID},
	}
	der, err := x509.CreateCertificateRequest(rand.Reader, tmpl, key)
	if err != nil {
		return nil, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: der}), nil
}

func writeKey(path string, key *ecdsa.PrivateKey) error {
	der, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return err
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: der})
	return os.WriteFile(path, pemBytes, 0o600)
}

func client() *http.Client {
	if Client != nil {
		return Client
	}
	return http.DefaultClient
}
