# xgen-agent 빌드 — 단일 정적 바이너리, 크로스 컴파일.
# 설계: docs/design/01-repo-structure.md

BIN := bin/xgen-agent

.PHONY: build cross vet
build:
	go build -o $(BIN) ./cmd/xgen-agent

# install.sh가 OS/arch별로 받을 수 있게 크로스 컴파일.
cross:
	GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o bin/xgen-agent-linux-amd64 ./cmd/xgen-agent
	GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o bin/xgen-agent-linux-arm64 ./cmd/xgen-agent

vet:
	go vet ./...
