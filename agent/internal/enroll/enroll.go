// Package enroll — 최초 등록 (REST POST /v1/enroll).
// 로컬 키쌍 생성 -> CSR -> join_token으로 인증 -> client cert 수령.
// 설계: docs/design/02-enrollment-security.md
package enroll

import (
	"context"

	"github.com/xgen/orchestrator/agent/internal/config"
)

// Run — 등록 수행. 성공 시 cfg에 node_id/cert 반영하고 디스크에 저장.
func Run(ctx context.Context, cfg *config.Config) error {
	// 1. 로컬 키쌍 생성 (private key는 노드 밖으로 안 나감)
	// 2. CSR 작성 (CN=node, machine-id 포함)
	// 3. POST {cfg.Server}/v1/enroll  { join_token, csr, node_info }
	//      TLS는 CP의 신뢰 CA로 검증 (P0-1)
	// 4. 응답 { node_id, client_cert(SAN=spiffe), ca_bundle } 저장
	// TODO: 구현
	return nil
}
