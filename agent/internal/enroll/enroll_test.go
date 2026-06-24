package enroll

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"testing"
	"time"

	"github.com/xgen/orchestrator/agent/internal/config"
)

const testMachineID = "test-machine-0123456789"

// fakeCP — 임시 CA로 CSR를 서명해 cert를 돌려주는 CP 스텁.
func fakeCP(t *testing.T) (*httptest.Server, *x509.Certificate) {
	t.Helper()
	caKey, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	caTmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "xgen-test-ca"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign,
		BasicConstraintsValid: true,
	}
	caDER, _ := x509.CreateCertificate(rand.Reader, caTmpl, caTmpl, &caKey.PublicKey, caKey)
	caCert, _ := x509.ParseCertificate(caDER)
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: caDER})

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req enrollRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad json", http.StatusBadRequest)
			return
		}
		if req.JoinToken == "" {
			http.Error(w, "missing token", http.StatusUnauthorized)
			return
		}
		// CSR 파싱 + 서명 검증
		blk, _ := pem.Decode([]byte(req.CSR))
		if blk == nil {
			http.Error(w, "bad csr", http.StatusBadRequest)
			return
		}
		csr, err := x509.ParseCertificateRequest(blk.Bytes)
		if err != nil || csr.CheckSignature() != nil {
			http.Error(w, "invalid csr", http.StatusBadRequest)
			return
		}
		nodeID := "node-1"
		spiffe, _ := url.Parse("spiffe://xgen/node/" + nodeID)
		leaf := &x509.Certificate{
			SerialNumber: big.NewInt(2),
			Subject:      csr.Subject, // CN=xgen-node, SerialNumber=machine-id 유지
			NotBefore:    time.Now().Add(-time.Hour),
			NotAfter:     time.Now().Add(365 * 24 * time.Hour),
			KeyUsage:     x509.KeyUsageDigitalSignature,
			ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
			URIs:         []*url.URL{spiffe},
		}
		leafDER, _ := x509.CreateCertificate(rand.Reader, leaf, caCert, csr.PublicKey, caKey)
		leafPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: leafDER})
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(enrollResponse{
			NodeID:     nodeID,
			ClientCert: string(leafPEM),
			CABundle:   string(caPEM),
		})
	}))
	t.Cleanup(srv.Close)
	return srv, caCert
}

func TestRun_Enrolls(t *testing.T) {
	srv, caCert := fakeCP(t)
	dir := t.TempDir()
	t.Setenv("XGEN_DIR", dir)
	t.Setenv("XGEN_SERVER", srv.URL)
	t.Setenv("XGEN_JOIN_TOKEN", "join-tok")
	t.Setenv("XGEN_MACHINE_ID", testMachineID)
	Client = srv.Client()
	t.Cleanup(func() { Client = nil })

	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("config.Load: %v", err)
	}
	if cfg.Enrolled() {
		t.Fatal("should not be enrolled before Run")
	}
	if err := Run(context.Background(), cfg); err != nil {
		t.Fatalf("Run: %v", err)
	}

	// node_id 영속화
	if cfg.NodeID() != "node-1" {
		t.Errorf("node_id = %q, want node-1", cfg.NodeID())
	}
	// 재로드 시 등록 상태로 인식
	if reloaded, _ := config.Load(); !reloaded.Enrolled() {
		t.Error("reloaded config should report enrolled")
	}

	// 개인키 0600 + EC 파싱
	keyInfo, err := os.Stat(cfg.KeyPath())
	if err != nil {
		t.Fatalf("key missing: %v", err)
	}
	if perm := keyInfo.Mode().Perm(); perm != 0o600 {
		t.Errorf("key perm = %o, want 600", perm)
	}

	// cert 파싱 + machine-id 보존 + CA 체인 검증
	certPEM, _ := os.ReadFile(cfg.CertPath())
	blk, _ := pem.Decode(certPEM)
	if blk == nil {
		t.Fatal("cert not PEM")
	}
	cert, err := x509.ParseCertificate(blk.Bytes)
	if err != nil {
		t.Fatalf("parse cert: %v", err)
	}
	if cert.Subject.SerialNumber != testMachineID {
		t.Errorf("cert serialNumber = %q, want machine-id %q", cert.Subject.SerialNumber, testMachineID)
	}
	pool := x509.NewCertPool()
	pool.AddCert(caCert)
	if _, err := cert.Verify(x509.VerifyOptions{
		Roots:     pool,
		KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}); err != nil {
		t.Errorf("cert does not chain to CA: %v", err)
	}
}

func TestRun_RejectsMissingToken(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XGEN_DIR", dir)
	t.Setenv("XGEN_SERVER", "https://cp.invalid")
	t.Setenv("XGEN_MACHINE_ID", testMachineID)
	// XGEN_JOIN_TOKEN 미설정
	cfg, _ := config.Load()
	if err := Run(context.Background(), cfg); err == nil {
		t.Fatal("expected error when join token missing")
	}
}
