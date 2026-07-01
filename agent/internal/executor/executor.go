// Package executor — RunJob 실행기. 호스트에서 명령을 실행하고 stdout/stderr를
// LogBatch로, 진행/결과를 JobUpdate로 sendCh에 push.
//
// timeout(params["timeout_sec"], 기본 3600s) + cancel(부모 ctx 취소=CancelJob) 지원.
// 설계: docs/design/05-job-orchestration.md
package executor

import (
	"bufio"
	"context"
	"io"
	"os"
	"os/exec"
	"strconv"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
)

const defaultTimeout = 3600 * time.Second

// Run — RunJob 1건 실행. ctx 취소 시 CANCELLED, timeout 시 FAILED(timeout).
func Run(ctx context.Context, nodeID string, sendCh chan<- *pb.AgentMessage, commandID string, rj *pb.RunJob) {
	jobID := rj.GetJobId()
	push := func(m *pb.AgentMessage) {
		m.NodeId = nodeID
		select {
		case sendCh <- m:
		case <-ctx.Done():
		}
	}
	finish := func(phase pb.JobUpdate_Phase, exit int32, msg string) {
		push(&pb.AgentMessage{Payload: &pb.AgentMessage_JobUpdate{JobUpdate: &pb.JobUpdate{
			CommandId: commandID, JobId: jobID, Phase: phase, ExitCode: exit, Message: msg, PhaseSeq: 2,
		}}})
		push(&pb.AgentMessage{Payload: &pb.AgentMessage_Ack{Ack: &pb.CommandAck{CommandId: commandID}}})
	}

	push(&pb.AgentMessage{Payload: &pb.AgentMessage_JobUpdate{JobUpdate: &pb.JobUpdate{
		CommandId: commandID, JobId: jobID, Phase: pb.JobUpdate_RUNNING, PhaseSeq: 1,
	}}})

	// timeout ctx (params["timeout_sec"] 우선). CancelJob은 부모 ctx를 취소해 여기로 전파.
	timeout := defaultTimeout
	if v := rj.GetParams()["timeout_sec"]; v != "" {
		if n, _ := strconv.Atoi(v); n > 0 {
			timeout = time.Duration(n) * time.Second
		}
	}
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	var off uint64
	emit := func(stream, text string) {
		o := atomic.AddUint64(&off, 1) - 1
		push(&pb.AgentMessage{Payload: &pb.AgentMessage_Logs{Logs: &pb.LogBatch{
			Source: jobID,
			Lines:  []*pb.LogLine{{TsUnixMs: time.Now().UnixMilli(), Stream: stream, Text: text, Offset: o}},
		}}})
	}

	var cmdStr, workdir string
	if rj.GetBundleUrl() != "" {
		dir, err := fetchAndExtract(runCtx, rj.GetBundleUrl(), rj.GetBundleSha256())
		if err != nil {
			emit("stderr", "bundle: "+err.Error())
			finish(pb.JobUpdate_FAILED, 1, "bundle fetch failed")
			return
		}
		defer os.RemoveAll(dir)
		workdir = dir
		cmdStr = rj.GetParams()["entry"]
		if cmdStr == "" {
			cmdStr = "echo 'no entry in manifest'"
		}
	} else {
		cmdStr = rj.GetParams()["cmd"]
		if cmdStr == "" {
			cmdStr = "echo 'no cmd param'"
		}
	}

	c := exec.CommandContext(runCtx, "sh", "-c", cmdStr)
	if workdir != "" {
		c.Dir = workdir
	}
	// 자체 프로세스 그룹으로 실행 → 취소/timeout 시 자식(예: sleep)까지 그룹 kill.
	c.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	c.Cancel = func() error {
		if c.Process != nil {
			_ = syscall.Kill(-c.Process.Pid, syscall.SIGKILL) // 음수 pid = 프로세스 그룹
		}
		return nil
	}
	// 자식이 파이프를 붙잡고 있어도 취소 후 최대 3s 뒤 파이프 닫고 Wait 반환.
	c.WaitDelay = 3 * time.Second
	stdout, _ := c.StdoutPipe()
	stderr, _ := c.StderrPipe()

	pump := func(wg *sync.WaitGroup, r io.Reader, name string) {
		defer wg.Done()
		sc := bufio.NewScanner(r)
		sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
		for sc.Scan() {
			emit(name, sc.Text())
		}
	}

	if err := c.Start(); err != nil {
		emit("stderr", "start failed: "+err.Error())
		finish(pb.JobUpdate_FAILED, 1, err.Error())
		return
	}
	var wg sync.WaitGroup
	wg.Add(2)
	go pump(&wg, stdout, "stdout")
	go pump(&wg, stderr, "stderr")
	wg.Wait()
	waitErr := c.Wait()

	switch {
	case runCtx.Err() == context.DeadlineExceeded:
		finish(pb.JobUpdate_FAILED, -1, "timeout")
	case runCtx.Err() == context.Canceled:
		finish(pb.JobUpdate_CANCELLED, -1, "cancelled")
	case waitErr != nil:
		exit := int32(1)
		if ee, ok := waitErr.(*exec.ExitError); ok {
			exit = int32(ee.ExitCode())
		}
		finish(pb.JobUpdate_FAILED, exit, waitErr.Error())
	default:
		finish(pb.JobUpdate_SUCCEEDED, 0, "")
	}
}
