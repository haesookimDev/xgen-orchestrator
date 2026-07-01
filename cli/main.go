// xgenctl — 운영자 CLI. CP REST API 소비 (07-operator-surface.md).
// 서버: XGEN_CP_URL (기본 http://127.0.0.1:18080).
// TODO: 운영자 인증(JWT 2-role, P0-4) — 현재 CP REST는 무인증.
//
// 사용:
//
//	xgenctl nodes                          노드 목록
//	xgenctl inventory <node_id>            노드 HW 인벤토리
//	xgenctl bundles                        번들 카탈로그
//	xgenctl install <node_id> <sol@ver> [runtime] [action]   설치 Job 생성
//	xgenctl job <job_id>                   Job 상태
//	xgenctl logs <job_id>                  Job 로그
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

func server() string {
	if v := os.Getenv("XGEN_CP_URL"); v != "" {
		return v
	}
	return "http://127.0.0.1:18080"
}

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		usage()
		os.Exit(2)
	}
	cmd, rest := args[0], args[1:]
	switch cmd {
	case "login":
		need(rest, 2, "login <username> <password>")
		login(rest[0], rest[1])
	case "nodes":
		getPretty("/v1/nodes")
	case "bundles":
		getPretty("/v1/bundles")
	case "inventory":
		need(rest, 1, "inventory <node_id>")
		getPretty("/v1/nodes/" + rest[0] + "/inventory")
	case "job":
		need(rest, 1, "job <job_id>")
		getPretty("/v1/jobs/" + rest[0])
	case "logs":
		need(rest, 1, "logs <job_id>")
		printLogs("/v1/jobs/" + rest[0] + "/logs")
	case "cancel":
		need(rest, 1, "cancel <job_id>")
		resp, err := authed(http.MethodPost, server()+"/v1/jobs/"+rest[0]+"/cancel", nil)
		checkResp(resp, err)
		b, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		fmt.Println(string(b))
	case "install":
		need(rest, 2, "install <node_id> <sol@ver> [runtime] [action]")
		install(rest)
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `xgenctl — xgen-orchestrator operator CLI
  login <user> <pass>        authenticate (saves token)
  nodes                      list nodes
  inventory <node_id>        node HW inventory
  bundles                    bundle catalog
  install <node_id> <sol@ver> [runtime=docker] [action=install]
  job <job_id>               job status
  logs <job_id>              job logs
  cancel <job_id>            cancel a running job
env: XGEN_CP_URL (default http://127.0.0.1:18080), XGEN_TOKEN (else ~/.xgenctl-token)
`)
}

func tokenPath() string {
	h, _ := os.UserHomeDir()
	return filepath.Join(h, ".xgenctl-token")
}

func token() string {
	if v := os.Getenv("XGEN_TOKEN"); v != "" {
		return v
	}
	if b, err := os.ReadFile(tokenPath()); err == nil {
		return strings.TrimSpace(string(b))
	}
	return ""
}

func login(user, pass string) {
	body, _ := json.Marshal(map[string]string{"username": user, "password": pass})
	resp, err := http.Post(server()+"/v1/login", "application/json", bytes.NewReader(body))
	checkResp(resp, err)
	defer resp.Body.Close()
	var r struct {
		Token string `json:"token"`
		Role  string `json:"role"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		fail(err)
	}
	if err := os.WriteFile(tokenPath(), []byte(r.Token), 0o600); err != nil {
		fail(err)
	}
	fmt.Printf("logged in as %s (role=%s), token saved to %s\n", user, r.Role, tokenPath())
}

// authed — GET with Authorization header.
func authed(method, url string, body io.Reader) (*http.Response, error) {
	req, err := http.NewRequest(method, url, body)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if t := token(); t != "" {
		req.Header.Set("Authorization", "Bearer "+t)
	}
	return http.DefaultClient.Do(req)
}

func need(args []string, n int, form string) {
	if len(args) < n {
		fmt.Fprintln(os.Stderr, "usage: xgenctl "+form)
		os.Exit(2)
	}
}

func getPretty(path string) {
	resp, err := authed(http.MethodGet, server()+path, nil)
	checkResp(resp, err)
	defer resp.Body.Close()
	var v any
	if err := json.NewDecoder(resp.Body).Decode(&v); err != nil {
		fail(err)
	}
	b, _ := json.MarshalIndent(v, "", "  ")
	fmt.Println(string(b))
}

func printLogs(path string) {
	resp, err := authed(http.MethodGet, server()+path, nil)
	checkResp(resp, err)
	defer resp.Body.Close()
	var lines []struct {
		Stream string `json:"stream"`
		Text   string `json:"text"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&lines); err != nil {
		fail(err)
	}
	for _, l := range lines {
		fmt.Printf("%s: %s\n", l.Stream, l.Text)
	}
}

func install(rest []string) {
	runtime, action := "docker", "install"
	if len(rest) >= 3 {
		runtime = rest[2]
	}
	if len(rest) >= 4 {
		action = rest[3]
	}
	body, _ := json.Marshal(map[string]any{
		"bundle": rest[1], "runtime": runtime, "action": action,
	})
	resp, err := authed(http.MethodPost, server()+"/v1/nodes/"+rest[0]+"/jobs", bytes.NewReader(body))
	checkResp(resp, err)
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	fmt.Println(string(b))
}

func checkResp(resp *http.Response, err error) {
	if err != nil {
		fail(err)
	}
	if resp.StatusCode >= 300 {
		b, _ := io.ReadAll(resp.Body)
		fmt.Fprintf(os.Stderr, "error: %s: %s\n", resp.Status, bytes.TrimSpace(b))
		os.Exit(1)
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
