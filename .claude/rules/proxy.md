---
paths:
  - "internal/ansible/proxy/**"
---

# Proxy Module Rules

- The proxy binds to `localhost` only. DO NOT change the bind address -- it has no authentication of its own.
- DO NOT remove either `Authorization` header stripping call in the handler chain. Both are required.
- Handler chain is assembled inside-out; ordering is load-bearing.
- Adding middleware that modifies request bodies must go between the authorization-stripping and owner-injection layers, never outside the cache handler.
- The cache handler implements a 6-second timeout with fallback to the API server.
- Owner references are injected via the proxy to track dependent resources for garbage collection.
- Metrics API binds to `localhost:5050`; do not expose externally.
- HTTP/2 is disabled by default (`--enable-http2=false`); `ReadHeaderTimeout: 5s` on all HTTP servers.
- Validate at package level: `go test ./internal/ansible/proxy/ -short`.
