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
	"time"
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
		need(rest, 1, "logs <job_id> [-f]")
		if len(rest) >= 2 && rest[1] == "-f" {
			followLogs(rest[0])
		} else {
			printLogs("/v1/jobs/" + rest[0] + "/logs")
		}
	case "cancel":
		need(rest, 1, "cancel <job_id>")
		postJSON("/v1/jobs/"+rest[0]+"/cancel", nil)
	case "token-create":
		body := map[string]any{}
		if len(rest) >= 1 {
			body["type"] = rest[0]
		}
		postJSON("/v1/tokens", body)
	case "token-list":
		getPretty("/v1/tokens")
	case "token-revoke":
		need(rest, 1, "token-revoke <id>")
		postJSON("/v1/tokens/"+rest[0]+"/revoke", nil)
	case "node-disable":
		need(rest, 1, "node-disable <node_id>")
		postJSON("/v1/nodes/"+rest[0]+"/disable", nil)
	case "node-enable":
		need(rest, 1, "node-enable <node_id>")
		postJSON("/v1/nodes/"+rest[0]+"/enable", nil)
	case "node-revoke":
		need(rest, 1, "node-revoke <node_id>")
		postJSON("/v1/nodes/"+rest[0]+"/revoke", nil)
	case "install":
		need(rest, 2, "install <node_id> <sol@ver> [runtime] [action]")
		install(rest)
	case "clusters":
		getPretty("/v1/clusters")
	case "cluster":
		need(rest, 1, "cluster <cluster_id>")
		getPretty("/v1/clusters/" + rest[0])
	case "cluster-create":
		need(rest, 3, "cluster-create <name> <sol@ver> <server_node> [worker_nodes...]")
		clusterCreate(rest)
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
  install <node_id> <sol@ver> [runtime=docker] [action=install] [-p k=v]... [-s ref]...
  job <job_id>               job status
  logs <job_id> [-f]         job logs (-f follow/tail)
  cancel <job_id>            cancel a running job
  token-create [type]        create join token (shared|one_time), prints once
  token-list                 list join tokens
  token-revoke <id>          revoke a join token
  node-disable <node_id>     disable node (blocks agent stream)
  node-enable <node_id>      re-enable a disabled node
  node-revoke <node_id>      revoke node cert (permanent)
  clusters                   list clusters
  cluster <cluster_id>       cluster detail
  cluster-create <name> <sol@ver> <server_node> [worker_nodes...]
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

func clusterCreate(rest []string) {
	body, _ := json.Marshal(map[string]any{
		"name": rest[0], "bundle": rest[1], "runtime": "k3s",
		"server": rest[2], "workers": rest[3:],
	})
	resp, err := authed(http.MethodPost, server()+"/v1/clusters", bytes.NewReader(body))
	checkResp(resp, err)
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	fmt.Println(string(b))
}

func postJSON(path string, body any) {
	var r io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		r = bytes.NewReader(b)
	}
	resp, err := authed(http.MethodPost, server()+path, r)
	checkResp(resp, err)
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	fmt.Println(string(b))
}

func followLogs(jobID string) {
	seen := 0
	for {
		resp, err := authed(http.MethodGet, server()+"/v1/jobs/"+jobID+"/logs", nil)
		checkResp(resp, err)
		var lines []struct {
			Offset int    `json:"offset"`
			Stream string `json:"stream"`
			Text   string `json:"text"`
		}
		_ = json.NewDecoder(resp.Body).Decode(&lines)
		resp.Body.Close()
		for _, l := range lines {
			if l.Offset >= seen {
				fmt.Printf("%s: %s\n", l.Stream, l.Text)
				seen = l.Offset + 1
			}
		}
		jr, err := authed(http.MethodGet, server()+"/v1/jobs/"+jobID, nil)
		checkResp(jr, err)
		var j struct {
			Phase string `json:"phase"`
		}
		_ = json.NewDecoder(jr.Body).Decode(&j)
		jr.Body.Close()
		switch j.Phase {
		case "succeeded", "failed", "cancelled", "interrupted":
			fmt.Println("--", j.Phase, "--")
			return
		}
		time.Sleep(time.Second)
	}
}

func install(rest []string) {
	// install <node> <sol@ver> [runtime] [action] [-p k=v]... [-s ref]...
	runtime, action := "docker", "install"
	params := map[string]string{}
	secrets := []string{}
	pos := 0
	for i := 2; i < len(rest); i++ {
		switch rest[i] {
		case "-p":
			i++
			if i < len(rest) {
				if k, v, ok := strings.Cut(rest[i], "="); ok {
					params[k] = v
				}
			}
		case "-s":
			i++
			if i < len(rest) {
				secrets = append(secrets, rest[i])
			}
		default:
			if pos == 0 {
				runtime = rest[i]
			} else if pos == 1 {
				action = rest[i]
			}
			pos++
		}
	}
	postJSON("/v1/nodes/"+rest[0]+"/jobs", map[string]any{
		"bundle": rest[1], "runtime": runtime, "action": action,
		"params": params, "secret_refs": secrets,
	})
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
