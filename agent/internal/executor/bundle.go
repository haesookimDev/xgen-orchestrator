package executor

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// fetchAndExtract — bundle_url에서 tar.gz fetch → sha256 검증 → 임시 디렉토리에 전개.
// 무결성은 sha256(보안 stream으로 전달된 값)로 보장. TODO(P1-1): mTLS fetch + cosign verify.
func fetchAndExtract(ctx context.Context, url, wantSHA string) (string, error) {
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
