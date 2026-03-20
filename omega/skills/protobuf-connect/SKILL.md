---
name: protobuf-connect
description: Buf conventions, proto3 best practices, schema evolution rules, and Connect-ES v2 frontend patterns for Omega
tags:
  - protobuf
  - proto3
  - buf
  - connect-rpc
  - connect-es
  - schema-evolution
  - typescript
---

# Protobuf & Connect-RPC — Omega Project Conventions

## Buf Toolchain

All proto management uses Buf. Key files:
- `buf.yaml` — module definition, lint config (STANDARD), breaking change detection (FILE mode)
- `buf.gen.yaml` — generates Go (`gen/go/`) and TypeScript (`dashboard/src/gen/`)

```bash
# After any .proto change:
buf generate        # regenerate all targets
buf lint            # check style
buf breaking --against .git#branch=main  # check backward compat
```

Never edit files in `gen/` manually — they are always regenerated.

## Proto3 Field Naming

- `snake_case` for all field names (Buf lint enforces this).
- Generated Go: `CamelCase`. Generated TypeScript: `camelCase`. Do not rename generated fields.
- Booleans: `is_` prefix (`is_healthy`, `is_available`).
- Timestamps: use `google.protobuf.Timestamp`, not `string`.
- Durations: use `google.protobuf.Duration`.

## Message Design

- Flat messages for RPC request/response — avoid deep nesting.
- Every request: unique name ending in `Request` (`GetNodeRequest`, not `Request`).
- Every response: unique name ending in `Response` (`GetNodeResponse`).
- Use `oneof` for mutually exclusive fields.

## Field Numbers

- Never reuse field numbers — even after removal. Mark removed fields as `reserved`:
  ```protobuf
  reserved 5, 6;
  reserved "old_field_name", "removed_field";
  ```
- Field numbers 1–15 encode in 1 byte — use for the most frequently set fields.

## Schema Evolution Rules

**Safe (backward compatible):**
- Adding new optional fields
- Adding new enum values (never remove or reorder)
- Adding new RPC methods
- Renaming a message type (update all references)

**Breaking (never do):**
- Removing or renumbering fields
- Changing a field's type
- Removing enum values or changing their numbers
- Removing RPC methods
- Changing singular ↔ repeated

## Omega Proto Layout

```
proto/omega/v1/
├── types.proto          # Shared types: Node, NodeState, BrainConfig, TraceSummary, …
├── node_service.proto   # NodeService: Execute, Evaluate, Improve, GetState, GetCapabilities
└── omega_service.proto  # OrchestratorService: 23+ RPCs for dashboard (health, nodes, traces, …)
```

When adding a capability:
1. Add message types to `types.proto` (or new file for large additions)
2. Add RPC to the appropriate service proto
3. `buf generate`
4. Implement handler in `internal/handlers/`
5. Wire in `cmd/omega-api/main.go`

## Connect-RPC Go Handler Pattern

```go
func (h *Handler) GetNode(
    ctx context.Context,
    req *connect.Request[omegav1.GetNodeRequest],
) (*connect.Response[omegav1.GetNodeResponse], error) {
    if req.Msg.NodeId == "" {
        return nil, connect.NewError(connect.CodeInvalidArgument, errors.New("node_id required"))
    }
    node, err := h.store.GetNode(ctx, req.Msg.NodeId)
    if errors.Is(err, ErrNotFound) {
        return nil, connect.NewError(connect.CodeNotFound, err)
    }
    if err != nil {
        return nil, connect.NewError(connect.CodeInternal, err)
    }
    return connect.NewResponse(&omegav1.GetNodeResponse{Node: node}), nil
}
```

## Connect-ES v2 Frontend (TypeScript)

```typescript
import { createClient } from "@connectrpc/connect";
import { createConnectTransport } from "@connectrpc/connect-web";
import { OrchestratorService } from "../gen/omega/v1/omega_service_connect";

// One transport for the whole app
const transport = createConnectTransport({
  baseUrl: import.meta.env.VITE_API_URL ?? "http://localhost:8080",
});

const client = createClient(OrchestratorService, transport);

// Unary RPC
const { node } = await client.getNode({ nodeId: "my-node" });

// Server streaming
for await (const event of client.streamEvents({ filter: "all" })) {
  handleEvent(event);
}
```

Import generated types from `dashboard/src/gen/` — never from `proto/`.
Use `ConnectError` for typed error handling:
```typescript
import { ConnectError } from "@connectrpc/connect";
try {
  await client.execute(req);
} catch (err) {
  if (err instanceof ConnectError) {
    console.error(err.code, err.message);
  }
}
```
