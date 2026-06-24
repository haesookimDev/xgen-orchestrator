# xgen-orchestrator — 모노레포 진입점
# 설계: docs/design/01-repo-structure.md

.PHONY: proto agent control-plane web build lint clean

# proto -> Go(agent/gen) + Python(control-plane/.../gen) 생성
proto:
	cd proto && buf lint && buf generate

agent:
	cd agent && go build ./...

control-plane:
	cd control-plane && python -m pip install -e .

web:
	cd web && npm install && npm run build

build: proto agent control-plane

lint:
	cd proto && buf lint
	cd agent && go vet ./...

clean:
	rm -rf agent/gen control-plane/src/xgen_orchestrator/gen
