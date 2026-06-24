// Package executor — RunJob 실행기. 호스트에서 명령을 root로 실행하고 stdout/stderr를
// LogBatch로, 진행/결과를 JobUpdate로 sendCh에 push.
//
// 1차: params["cmd"]를 sh -c 로 실행(번들 fetch·manifest·pre-flight는 후속).
// 설계: docs/design/05-job-orchestration.md
package executor

import (
	"bufio"
	"context"
	"io"
	"os/exec"
	"sync"
	"sync/atomic"
	"time"

	pb "github.com/xgen/orchestrator/agent/gen/orchestrator/v1"
)

// Run — RunJob 1건 실행. sendCh로 LogBatch/JobUpdate/CommandAck push.
func Run(ctx context.Context, nodeID string, sendCh chan<- *pb.AgentMessage, commandID string, rj *pb.RunJob) {
	jobID := rj.GetJobId()
	push := func(m *pb.AgentMessage) {
		m.NodeId = nodeID
		select {
		case sendCh <- m:
		case <-ctx.Done():
		}
	}

	push(&pb.AgentMessage{Payload: &pb.AgentMessage_JobUpdate{JobUpdate: &pb.JobUpdate{
		CommandId: commandID, JobId: jobID, Phase: pb.JobUpdate_RUNNING, PhaseSeq: 1,
	}}})

	cmdStr := rj.GetParams()["cmd"]
	if cmdStr == "" {
		cmdStr = "echo 'no cmd param (TODO: bundle action)'"
	}
	c := exec.CommandContext(ctx, "sh", "-c", cmdStr)
	stdout, _ := c.StdoutPipe()
	stderr, _ := c.StderrPipe()

	var off uint64
	emit := func(stream, text string) {
		o := atomic.AddUint64(&off, 1) - 1
		push(&pb.AgentMessage{Payload: &pb.AgentMessage_Logs{Logs: &pb.LogBatch{
			Source: jobID,
			Lines:  []*pb.LogLine{{TsUnixMs: time.Now().UnixMilli(), Stream: stream, Text: text, Offset: o}},
		}}})
	}
	pump := func(wg *sync.WaitGroup, r io.Reader, name string) {
		defer wg.Done()
		sc := bufio.NewScanner(r)
		sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
		for sc.Scan() {
			emit(name, sc.Text())
		}
	}

	phase := pb.JobUpdate_SUCCEEDED
	var exitCode int32
	if err := c.Start(); err != nil {
		emit("stderr", "start failed: "+err.Error())
		phase, exitCode = pb.JobUpdate_FAILED, 1
	} else {
		var wg sync.WaitGroup
		wg.Add(2)
		go pump(&wg, stdout, "stdout")
		go pump(&wg, stderr, "stderr")
		wg.Wait()
		if err := c.Wait(); err != nil {
			phase = pb.JobUpdate_FAILED
			if ee, ok := err.(*exec.ExitError); ok {
				exitCode = int32(ee.ExitCode())
			} else {
				exitCode = 1
			}
		}
	}

	push(&pb.AgentMessage{Payload: &pb.AgentMessage_JobUpdate{JobUpdate: &pb.JobUpdate{
		CommandId: commandID, JobId: jobID, Phase: phase, ExitCode: exitCode, PhaseSeq: 2,
	}}})
	push(&pb.AgentMessage{Payload: &pb.AgentMessage_Ack{Ack: &pb.CommandAck{CommandId: commandID}}})
}
