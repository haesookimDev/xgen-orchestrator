module github.com/xgen/orchestrator/agent

go 1.25.0

// gRPC/protobuf 의존성은 생성 코드(make proto -> agent/gen)가 사용한다.
// gen/ 은 .gitignore 대상이므로 빌드 전 `make proto` 필요. (gen 부재 상태에서 go mod tidy 금지)

require (
	golang.org/x/net v0.51.0 // indirect
	golang.org/x/sys v0.42.0 // indirect
	golang.org/x/text v0.34.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260226221140-a57be14db171 // indirect
	google.golang.org/grpc v1.81.1 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
)
