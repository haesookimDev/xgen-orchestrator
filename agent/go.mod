module github.com/xgen/orchestrator/agent

go 1.22

// 의존성은 proto 생성(make proto) 후 google.golang.org/grpc, protobuf 등이 추가됨.
// 1차 슬라이스 스캐폴딩 단계라 require 블록은 codegen 후 채운다.
