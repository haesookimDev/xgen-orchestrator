package executor

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/ecdsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// fetchAndExtract — bundle_url에서 tar.gz fetch → sha256(무결성) + 서명(진위) 검증 → 전개.
// sha256·서명 값은 보안 stream으로 전달됨. TODO: 클라이언트-cert mTLS fetch.
func fetchAndExtract(ctx context.Context, url, wantSHA, sigB64, pubPath string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("fetch %s: %s", url, resp.Status)
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if wantSHA != "" {
		sum := sha256.Sum256(data)
		if got := hex.EncodeToString(sum[:]); got != wantSHA {
			return "", fmt.Errorf("sha256 mismatch: got %s want %s", got, wantSHA)
		}
	}
	if sigB64 != "" {
		if err := verifySig(data, sigB64, pubPath); err != nil {
			return "", fmt.Errorf("signature: %w", err)
		}
	}
	dir, err := os.MkdirTemp("", "xgen-bundle-*")
	if err != nil {
		return "", err
	}
	if err := extractTarGz(data, dir); err != nil {
		_ = os.RemoveAll(dir)
		return "", err
	}
	return dir, nil
}

// verifySig — data의 ECDSA 서명(base64)을 pubPath(PEM)로 검증.
func verifySig(data []byte, sigB64, pubPath string) error {
	pubPEM, err := os.ReadFile(pubPath)
	if err != nil {
		return fmt.Errorf("read pubkey %s: %w", pubPath, err)
	}
	block, _ := pem.Decode(pubPEM)
	if block == nil {
		return errors.New("bad pubkey PEM")
	}
	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		return err
	}
	ecpub, ok := pub.(*ecdsa.PublicKey)
	if !ok {
		return errors.New("pubkey is not ECDSA")
	}
	sig, err := base64.StdEncoding.DecodeString(sigB64)
	if err != nil {
		return err
	}
	h := sha256.Sum256(data)
	if !ecdsa.VerifyASN1(ecpub, h[:], sig) {
		return errors.New("verification failed")
	}
	return nil
}

func extractTarGz(data []byte, dir string) error {
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	root := filepath.Clean(dir) + string(os.PathSeparator)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		target := filepath.Join(dir, hdr.Name)
		// zip-slip 방지
		if target != filepath.Clean(dir) && !strings.HasPrefix(target, root) {
			return fmt.Errorf("unsafe path in bundle: %s", hdr.Name)
		}
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode))
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				f.Close()
				return err
			}
			f.Close()
		}
	}
}
