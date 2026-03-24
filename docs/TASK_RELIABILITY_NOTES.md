# Task Reliability Notes

Operational guidelines to prevent Claude Code task sessions from hanging or timing out.

## Root Causes of Task Hangs

Previous sessions hung due to:
- Too many concurrent subagents exhausting context/resources
- Long-running pytest commands (3+ min) blocking the session with no timeout
- Reading entire large files (orchestrator.go is 800+ lines) in active multi-session environments
- Port conflicts causing servers to silently fail, then tasks waiting on an unhealthy endpoint

---

## Rules

### 1. Max concurrent code tasks: 3

Running more than 3 Claude Code tasks in parallel causes resource contention. Keep concurrent
sessions at ≤3 for reliable execution.

### 2. Always use `--timeout` on pytest (120s max)

```bash
# BAD — can hang indefinitely
pytest ./internal/telemetry/...

# GOOD — always bounded
pytest ./internal/telemetry/... --timeout=120 -x
```

If tests need longer than 2 minutes they need to be split or parallelized, not given more time.

### 3. Avoid reading entire large files — use line ranges

```bash
# BAD — reads 800+ lines, causes context pressure
# (Read tool with no limit on orchestrator.go)

# GOOD — read only the section you need
# (Read tool with offset + limit, or Grep first to find exact lines)
```

For files > 300 lines: use Grep to find the relevant function/section, then Read with
`offset` and `limit` parameters targeting only that range.

### 4. Don't spawn subagents inside code tasks

Subagents inside an already-running code task create nested context that compounds memory use.
Do the work directly in the task using Bash, Read, Edit, Grep, Glob tools.

Reserve subagents for the top-level orchestration layer only.

### 5. Kill old servers before starting new ones

Port conflicts cause `go run` to exit immediately with "address already in use", leaving the
task waiting on a server that never started.

```bash
# Always run before starting servers:
pkill -f 'omega-api' 2>/dev/null
pkill -f 'server_main' 2>/dev/null
lsof -ti:8080 | xargs kill -9 2>/dev/null
lsof -ti:9090 | xargs kill -9 2>/dev/null
sleep 2
```

### 6. Verify server health before running cycles

```bash
curl -s http://localhost:8080/healthz | grep -q HEALTHY || echo "API not ready"
```

Never proceed to `omega run` without confirming both servers are healthy first.

### 7. Use pre-built binaries for long-running commands

`go run` recompiles on every invocation. For tasks that run many cycles:

```bash
# Build once
go build -o /tmp/omega-cli ./cmd/omega/...
go build -o /tmp/omega-api-bin ./cmd/omega-api/...

# Then use the binary
/tmp/omega-cli run --cycles 10 --interval 20
```

This avoids recompilation overhead and keeps the command fast and predictable.

---

## Quick Reference Checklist

Before starting a measurement run:

- [ ] `pkill -f 'omega-api'` and `pkill -f 'server_main'`
- [ ] Start pipeline server, wait for "listening on 0.0.0.0:9090" in logs
- [ ] Start API server, confirm `/healthz` → HEALTHY
- [ ] Use pre-built binary: `go build -o /tmp/omega-cli ./cmd/omega/...`
- [ ] Run: `/tmp/omega-cli run --cycles N --interval S`
- [ ] Query observability with single psql command (not multiple round-trips)
