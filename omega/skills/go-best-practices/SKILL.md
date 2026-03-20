---
name: go-best-practices
description: Go coding standards, error handling, concurrency, and Connect-RPC conventions for the Omega project
tags:
  - go
  - golang
  - error-handling
  - concurrency
  - connect-rpc
  - protobuf
---

# Go Best Practices — Omega Project

## Error Handling

- Always return `error` as the last return value. Never panic unless it is truly unrecoverable.
- Wrap errors with context using `fmt.Errorf("operation: %w", err)` — use `%w` (not `%v`) to preserve the error chain for `errors.Is` / `errors.As`.
- Use `errors.Is` / `errors.As` for inspection, never string comparison.
- Sentinel errors: declare as `var ErrFoo = errors.New("foo")` at package level.
- For Connect-RPC handlers, always return typed Connect errors:
  ```go
  return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("node_id required"))
  ```

Connect error codes:
| Code | When to use |
|------|-------------|
| `CodeInvalidArgument` | Bad input from client |
| `CodeNotFound` | Resource doesn't exist |
| `CodeAlreadyExists` | Resource exists, can't create again |
| `CodePermissionDenied` | Authenticated but not authorized |
| `CodeUnauthenticated` | Not authenticated |
| `CodeInternal` | Unexpected server error (log these) |
| `CodeUnavailable` | Temporary outage, client should retry |

## Naming Conventions

- Exported: `PascalCase`. Unexported: `camelCase`.
- Interfaces: `-er` suffix where possible (`BrainAdapter`, `NodeRunner`).
- Acronyms all-caps: `NodeID`, `RPCURL`, `HTTPClient`.
- Test functions: `TestFunctionName_Scenario`.
- Avoid stuttering: prefer `node.ID` over `node.NodeID`.

## Package Structure

- One responsibility per package. Avoid circular imports.
- `internal/` for packages that must not be imported outside the module.
- `cmd/` for entry points only — minimal logic, delegate to `internal/`.
- Generated proto code lives in `gen/go/` — never edit manually.

## Connect-RPC Handler Pattern

```go
func (h *NodeHandler) Execute(
    ctx context.Context,
    req *connect.Request[omegav1.ExecuteRequest],
) (*connect.Response[omegav1.ExecuteResponse], error) {
    if req.Msg.NodeId == "" {
        return nil, connect.NewError(connect.CodeInvalidArgument, errors.New("node_id required"))
    }
    result, err := h.node.Execute(ctx, req.Msg)
    if err != nil {
        return nil, connect.NewError(connect.CodeInternal, err)
    }
    return connect.NewResponse(&omegav1.ExecuteResponse{Result: result}), nil
}
```

## Concurrency Patterns

- Share memory by communicating (channels), not by communicating by sharing memory.
- Protect shared state with `sync.Mutex` or `sync.RWMutex`. Keep critical sections short.
- `context.Context` for cancellation — always the first parameter of functions that do I/O.
- Never launch goroutines without a clear owner waiting for them (`sync.WaitGroup` or channel drain).
- `select` with `ctx.Done()` for timeout/cancellation; `select` with `default` for non-blocking.

## Testing

- Table-driven tests for all pure functions:
  ```go
  tests := []struct {
      name    string
      a, b    float64
      want    float64
  }{
      {"positive", 3, 4, 7},
      {"zero", 0, 5, 5},
  }
  for _, tt := range tests {
      t.Run(tt.name, func(t *testing.T) {
          got := Add(tt.a, tt.b)
          if got != tt.want {
              t.Errorf("got %v, want %v", got, tt.want)
          }
      })
  }
  ```
- Use `t.Helper()` in test helpers so failure lines point to the caller.
- Integration tests that need external services: guard with `t.Skip("requires OMEGA_API_ADDR")`.
- Run `golangci-lint run` before committing.

## Omega-Specific Patterns

- Nodes are Go HTTP handlers via Connect-RPC. Each capability maps to one RPC method.
- State mutations go through `StateStore` — never mutate in-memory state without persisting.
- Trace IDs propagate via `context.Context` using the `tracing` package helpers.
- Use `buf.build/connectrpc/go` generated stubs — Connect handles HTTP/1.1 and HTTP/2 transparently.
- Run `buf generate` from repo root after any `.proto` change.
