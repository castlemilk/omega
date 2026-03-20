# Skill Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a skills system for Omega where nodes load domain-specific SKILL.md knowledge artifacts contextually into their LLM brain requests.

**Architecture:** Skills are markdown files with YAML frontmatter (name, description, tags). `SkillLoader` discovers and indexes them by tag, injecting relevant content into `BrainRequest.domain_context` when a node calls `consult_brain()`. Nodes declare their skill requirements via a `skill_tags` class attribute.

**Tech Stack:** Python 3.11+ stdlib only (no external dependencies), pytest, existing `omega.core.brain`/`omega.core.node` patterns.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `omega/skills/go-best-practices/SKILL.md` | Create | Go coding standards, error handling, Connect-RPC conventions |
| `omega/skills/deep-research/SKILL.md` | Create | IterDRAG search→summarize→reflect loop pattern |
| `omega/skills/protobuf-connect/SKILL.md` | Create | Buf conventions, proto3 best practices, Connect-ES v2 patterns |
| `omega/skills/testing/SKILL.md` | Create | Go/Python/React testing patterns |
| `omega/core/skill_loader.py` | Create | Discovery, frontmatter parsing, tag indexing, content serving |
| `omega/core/brain.py` | Modify | Add `skill_hints: List[str]` to `BrainRequest` |
| `omega/core/node.py` | Modify | Add `skill_tags = []` class attr + load skills in `consult_brain()` |
| `omega/nodes/skill_creator.py` | Create | Node that generates new SKILL.md files |
| `tests/test_skill_loader.py` | Create | Unit tests for SkillLoader |
| `tests/test_skill_creator.py` | Create | Unit + integration tests for SkillCreatorNode |

---

## Task 1: SKILL.md — Go Best Practices

**Files:**
- Create: `omega/skills/go-best-practices/SKILL.md`

- [ ] **Step 1: Create the skill file**

```markdown
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
- Wrap errors with context using `fmt.Errorf("operation: %w", err)` — use `%w` (not `%v`) to preserve the error chain.
- Use `errors.Is` / `errors.As` for inspection, never string comparison.
- Sentinel errors: declare as `var ErrFoo = errors.New("foo")` at package level.
- Custom error types: implement the `error` interface with a `Error() string` method.
- For Connect-RPC handlers, always return typed Connect errors:
  ```go
  return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("node_id required"))
  ```

## Naming Conventions

- Exported identifiers: `PascalCase`. Unexported: `camelCase`.
- Interfaces: name with `-er` suffix where possible (`BrainAdapter`, `NodeRunner`).
- Acronyms all-caps in identifiers: `NodeID`, `RPCURL`, `HTTPClient`.
- Test files: `foo_test.go`. Test functions: `TestFunctionName_Scenario`.
- Avoid stuttering: `node.NodeID` → `node.ID`.

## Package Structure

- One responsibility per package. Avoid circular imports.
- `internal/` for packages that should not be imported outside the module.
- `cmd/` for entry points only — minimal logic, delegate to `internal/`.
- Generated proto code lives in `gen/go/` — never edit manually.

## Connect-RPC / Protobuf Conventions

- All service definitions live in `proto/omega/v1/`. Run `buf generate` after any `.proto` change.
- Handler implementations in `internal/handlers/`. Never put business logic in `cmd/`.
- Always validate request fields at handler entry, return `connect.CodeInvalidArgument` for invalid inputs.
- For streaming RPCs, check `stream.Receive()` error for `io.EOF` as the normal termination signal.
- Proto field names use `snake_case`; Go generated names are `CamelCase` — do not manually rename.
- Backward compatibility: never remove or renumber proto fields. Add new fields; deprecate old ones.

## Concurrency Patterns

- Share memory by communicating (channels), not by communicating by sharing memory.
- Protect shared state with `sync.Mutex` or `sync.RWMutex`. Keep critical sections short.
- Use `context.Context` for cancellation — always the first parameter of functions that do I/O.
- Never use goroutines without a clear owner responsible for waiting (`sync.WaitGroup` or channel drain).
- `select` with `default` for non-blocking channel operations; `select` with `ctx.Done()` for timeout.

## Testing Patterns

- Table-driven tests for all pure functions:
  ```go
  tests := []struct {
      name  string
      input int
      want  int
  }{
      {"positive", 1, 2},
      {"zero", 0, 1},
  }
  for _, tt := range tests {
      t.Run(tt.name, func(t *testing.T) {
          got := MyFunc(tt.input)
          if got != tt.want {
              t.Errorf("got %d, want %d", got, tt.want)
          }
      })
  }
  ```
- Use `t.Helper()` in test helpers so failure lines point to the caller.
- Integration tests that need external services: use `t.Skip("requires...")` when env var absent.
- Fuzz targets in `FuzzXxx` functions to explore edge cases on numeric/string inputs.

## Code Quality

- Run `golangci-lint run` before committing. Config in `.golangci.yml`.
- `gofmt` is non-negotiable — enforced by pre-commit hook.
- Keep functions ≤ 40 lines. If a function needs a comment to explain what it does, it is too complex.
- Avoid `init()` functions — prefer explicit initialization.
- `defer` for resource cleanup (file close, mutex unlock) immediately after acquiring the resource.

## Omega-Specific Patterns

- Nodes are Go HTTP handlers via Connect-RPC. Each capability maps to one RPC method.
- State mutations go through `StateStore` — never mutate in-memory state without recording to store.
- Trace IDs propagate via `context.Context` using the `tracing` package helpers.
- Use `buf.build/connectrpc/go` generated stubs, not raw gRPC — Connect handles HTTP/1.1 and HTTP/2.
```

- [ ] **Step 2: Commit**

```bash
git add omega/skills/go-best-practices/SKILL.md
git commit -m "feat(skills): add go-best-practices skill"
```

---

## Task 2: SKILL.md — Deep Research (IterDRAG)

**Files:**
- Create: `omega/skills/deep-research/SKILL.md`

- [ ] **Step 1: Create the skill file**

```markdown
---
name: deep-research
description: IterDRAG iterative retrieval-augmented generation pattern for deep research with search, summarize, and reflect loops
tags:
  - research
  - search
  - rag
  - deep-research
  - analysis
---

# Deep Research — IterDRAG Pattern

Implements the Iterative Deep Research and Augmented Generation (IterDRAG) pattern.
When assigned a research task, follow this loop until confident the answer is comprehensive.

## The Loop

```
QUERY → SEARCH → SUMMARIZE → REFLECT → (gap found?) → SEARCH again → ... → REPORT
```

### Phase 1: Decompose the Query

Before searching, break the research question into 3-5 sub-questions. Each sub-question should be independently searchable and together they should cover the full topic.

Example for "What are the best practices for Connect-RPC in Go?":
1. What is Connect-RPC and how does it differ from gRPC?
2. What are the recommended project structure conventions for Connect-RPC Go services?
3. How should error handling work in Connect-RPC handlers?
4. What are the performance best practices for Connect-RPC streaming?
5. How does Connect-RPC handle backward compatibility with proto changes?

### Phase 2: Search (per sub-question)

For each sub-question:
1. Formulate a precise search query (use technical terms, avoid ambiguity).
2. Execute the search (via web search tool or knowledge retrieval).
3. Collect 3-5 relevant sources. Prefer: official docs, source code, RFC/specs, engineering blogs.
4. Note the URL, title, and key claims from each source.

### Phase 3: Summarize

After searching for all sub-questions:
1. Write a structured summary of findings per sub-question.
2. For each claim, note the source (URL or document name).
3. Flag contradictions between sources explicitly.
4. Identify what is authoritative (spec, official docs) vs. community opinion.

### Phase 4: Reflect on Gaps

Critically evaluate the summary:
- What questions remain unanswered?
- What claims lack good sourcing?
- Are there edge cases or failure modes not covered?
- Is the information current (check publication dates)?

If gaps exist → formulate new targeted queries and return to Phase 2.
If confident → proceed to Phase 5.

**Stopping criteria:** Stop iterating when:
- All sub-questions have authoritative answers, OR
- 3 iterations have completed (diminishing returns), OR
- The new searches return no new information not already in the summary.

### Phase 5: Produce the Report

Structure the final report as:

```markdown
# [Topic] — Research Report

## Summary (2-3 sentences, key findings)

## Findings

### [Sub-question 1]
[Answer with citations]

### [Sub-question 2]
[Answer with citations]

...

## Key Recommendations
- [Actionable recommendation 1]
- [Actionable recommendation 2]

## Sources
- [URL or doc name] — [relevance note]
- ...

## Gaps and Caveats
- [What is still uncertain or requires verification]
```

## Configuration

- **Local (offline):** Use Ollama with a capable model (llama3, mistral, deepseek-r1). Best for private data.
- **Cloud:** Use Claude (claude-sonnet-4-6) or GPT-4o for higher accuracy on complex topics.
- **Search:** Use DuckDuckGo (free, no key), Brave Search API, or Tavily API for web results.

## Quality Signals

Good research outputs:
- Every claim has a source
- Contradictions are noted, not hidden
- The report distinguishes between "this is in the spec" vs "this is common practice"
- Gaps section is honest about what remains unknown

Poor research outputs:
- Confident claims without sources
- No mention of alternatives or tradeoffs
- Single-source conclusions on contested topics
```

- [ ] **Step 2: Commit**

```bash
git add omega/skills/deep-research/SKILL.md
git commit -m "feat(skills): add deep-research (IterDRAG) skill"
```

---

## Task 3: SKILL.md — Protobuf / Connect-RPC

**Files:**
- Create: `omega/skills/protobuf-connect/SKILL.md`

- [ ] **Step 1: Create the skill file**

```markdown
---
name: protobuf-connect
description: Buf conventions, proto3 best practices, schema evolution rules, and Connect-ES v2 frontend patterns
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

## Buf Configuration

This project uses Buf for proto management. Key files:
- `buf.yaml` — module definition and lint/breaking rules
- `buf.gen.yaml` — code generation (Go + TypeScript targets)

Always run `buf generate` from the repo root after changing `.proto` files:
```bash
cd /path/to/omega && buf generate
```

Buf lint runs automatically in CI. Fix all lint errors before committing. Lint level: STANDARD.

## Proto3 Best Practices

### Field Naming
- Use `snake_case` for all field names (Buf lint enforces this).
- Generated Go names are `CamelCase`; TypeScript names are `camelCase`. Never change generated code.
- Boolean fields: `is_` prefix (`is_healthy`, `is_available`).
- Timestamp fields: use `google.protobuf.Timestamp`, not string.
- Duration fields: use `google.protobuf.Duration`.

### Message Design
- Prefer flat messages over deeply nested structures for RPC request/response.
- Every request message should have a unique name: `GetNodeRequest`, not `Request`.
- Every response message should have a unique name: `GetNodeResponse`, not `Response`.
- Use `oneof` for fields that are mutually exclusive.
- Avoid `repeated` fields in request messages when a single-item endpoint would work.

### Field Numbers
- Never reuse field numbers — even for removed fields. Mark removed fields as `reserved`.
- Reserve both the field number AND the name:
  ```protobuf
  reserved 5, 6;
  reserved "old_field_name", "another_removed_field";
  ```
- First 15 field numbers encode in 1 byte — use them for the most frequently populated fields.

### Schema Evolution (Backward Compatibility)

**Safe changes:**
- Adding new optional fields (any proto3 field is implicitly optional).
- Adding new enum values (add, never remove or reorder).
- Adding new RPC methods to a service.
- Renaming a message type (if you update all references).

**Breaking changes (avoid):**
- Removing or renumbering existing fields.
- Changing a field's type (even compatible types like int32→int64 break wire format).
- Removing enum values.
- Removing RPC methods from a service (clients may still call them).
- Changing a field from singular to repeated or vice versa.

Buf's breaking change detector (mode: FILE) is configured in `buf.yaml` and runs in CI.

## Connect-RPC Go Patterns

```go
// Handler signature — always context + connect.Request, return connect.Response + error
func (h *NodeHandler) Execute(
    ctx context.Context,
    req *connect.Request[omegav1.ExecuteRequest],
) (*connect.Response[omegav1.ExecuteResponse], error) {
    // Validate
    if req.Msg.NodeId == "" {
        return nil, connect.NewError(connect.CodeInvalidArgument, errors.New("node_id required"))
    }
    // Business logic
    result, err := h.node.Execute(ctx, req.Msg)
    if err != nil {
        return nil, connect.NewError(connect.CodeInternal, err)
    }
    return connect.NewResponse(&omegav1.ExecuteResponse{Result: result}), nil
}
```

Connect error codes and when to use them:
- `CodeInvalidArgument` — bad input from client
- `CodeNotFound` — resource doesn't exist
- `CodeAlreadyExists` — resource exists, can't create again
- `CodePermissionDenied` — authenticated but not authorized
- `CodeUnauthenticated` — not authenticated
- `CodeInternal` — unexpected server error (log these)
- `CodeUnavailable` — temporary outage, client should retry

## Connect-ES v2 Frontend Patterns (TypeScript)

This project uses `@connectrpc/connect` with Vite React.

```typescript
import { createClient } from "@connectrpc/connect";
import { createConnectTransport } from "@connectrpc/connect-web";
import { OrchestratorService } from "../gen/omega/v1/omega_service_connect";

// Create transport once, share across the app
const transport = createConnectTransport({
  baseUrl: import.meta.env.VITE_API_URL ?? "http://localhost:8080",
});

// Create client per service
const client = createClient(OrchestratorService, transport);

// Call RPCs — returns Promise, handles errors as ConnectError
try {
  const response = await client.getNode({ nodeId: "my-node" });
  console.log(response.node);
} catch (err) {
  if (err instanceof ConnectError) {
    console.error(err.code, err.message);
  }
}
```

For streaming RPCs:
```typescript
// Server streaming
for await (const event of client.streamEvents({ filter: "all" })) {
  handleEvent(event);
}
```

Generated types live in `dashboard/src/gen/`. Import from there, never from `proto/`.

## Omega Proto Layout

```
proto/omega/v1/
├── types.proto          # Shared message types (Node, NodeState, BrainConfig, …)
├── node_service.proto   # NodeService (Execute, Evaluate, Improve, GetState)
└── omega_service.proto  # OrchestratorService (23+ RPCs for dashboard)
```

When adding a new capability:
1. Add message types to `types.proto` (or new file for large additions).
2. Add RPC to the appropriate service proto.
3. Run `buf generate`.
4. Implement the handler in `internal/handlers/`.
5. Wire the handler in `cmd/omega-api/main.go`.
```

- [ ] **Step 2: Commit**

```bash
git add omega/skills/protobuf-connect/SKILL.md
git commit -m "feat(skills): add protobuf-connect skill"
```

---

## Task 4: SKILL.md — Testing

**Files:**
- Create: `omega/skills/testing/SKILL.md`

- [ ] **Step 1: Create the skill file**

```markdown
---
name: testing
description: Go table-driven tests, Python pytest patterns, React Testing Library patterns, property-based testing, and integration test conventions
tags:
  - testing
  - go
  - pytest
  - python
  - react
  - integration-testing
  - property-testing
---

# Testing Patterns — Omega Project

## Go Testing

### Table-Driven Tests (Standard Pattern)

Every pure function gets a table-driven test:

```go
func TestAdd(t *testing.T) {
    tests := []struct {
        name    string
        a, b    float64
        want    float64
        wantErr bool
    }{
        {"positive", 3, 4, 7, false},
        {"negative", -1, -1, -2, false},
        {"float", 1.5, 2.5, 4.0, false},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got, err := Add(tt.a, tt.b)
            if (err != nil) != tt.wantErr {
                t.Fatalf("error = %v, wantErr %v", err, tt.wantErr)
            }
            if got != tt.want {
                t.Errorf("got %v, want %v", got, tt.want)
            }
        })
    }
}
```

### Test Helpers with t.Helper()

```go
func assertNoError(t *testing.T, err error) {
    t.Helper()  // makes failures point to the caller, not here
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
}
```

### Integration Tests — Skip When Dependencies Absent

```go
func TestConnectRPCIntegration(t *testing.T) {
    addr := os.Getenv("OMEGA_API_ADDR")
    if addr == "" {
        t.Skip("OMEGA_API_ADDR not set — skipping integration test")
    }
    // ... test against real server
}
```

### Fuzzing

```go
func FuzzParseNodeID(f *testing.F) {
    f.Add("node-123")
    f.Add("")
    f.Add("node_with_underscores")
    f.Fuzz(func(t *testing.T, id string) {
        // Should never panic
        result := ParseNodeID(id)
        _ = result
    })
}
```

Run fuzz tests: `go test -fuzz FuzzParseNodeID -fuzztime 30s`

## Python Testing (pytest)

### Class-Based Test Organization (Omega Pattern)

```python
class TestCalculatorNode:
    def setup_method(self):
        """Called before each test method. Create fresh instances here."""
        self.node = CalculatorNode()

    def test_add_basic(self):
        inp = NodeInput(action="add", parameters={"a": 3, "b": 4})
        out = self.node.execute(inp)
        assert out.success
        assert out.result == 7.0

    def test_add_propagates_request_id(self):
        inp = NodeInput(action="add", parameters={"a": 1, "b": 1})
        out = self.node.execute(inp)
        assert out.request_id == inp.request_id
```

### Testing Error Cases Explicitly

```python
def test_divide_by_zero(self):
    inp = NodeInput(action="divide", parameters={"a": 10, "b": 0})
    out = self.node.execute(inp)
    assert not out.success
    assert any("zero" in e.lower() for e in out.errors)
```

### Testing State Transitions (Self-Improvement)

```python
def test_improvement_changes_version(self):
    assert self.node.version == "1.0"
    changed = self.node.improve({"improve_latency": True, "iteration": 0})
    assert changed is True
    assert self.node.version == "1.1"
```

### Temporary Directories in Tests

```python
import tempfile, os

def test_writes_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_path = os.path.join(tmpdir, "test-skill", "SKILL.md")
        # ... test file creation
        assert os.path.isfile(skill_path)
```

### Property-Based Testing with Hypothesis (when available)

```python
from hypothesis import given, strategies as st

@given(st.integers(), st.integers().filter(lambda x: x != 0))
def test_divide_never_raises(a, b):
    inp = NodeInput(action="divide", parameters={"a": a, "b": b})
    out = node.execute(inp)
    assert isinstance(out.success, bool)  # never raises, always returns NodeOutput
```

## React Testing Library

### Unit Tests for Components

```typescript
import { render, screen } from "@testing-library/react";
import { NodeCard } from "./NodeCard";

test("shows node name and health", () => {
  render(<NodeCard node={{ name: "CalculatorNode", health: 0.9 }} />);
  expect(screen.getByText("CalculatorNode")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "90");
});
```

### User Interaction Tests

```typescript
import { userEvent } from "@testing-library/user-event";

test("submits brain config form", async () => {
  const onSubmit = jest.fn();
  render(<BrainConfigPanel onSubmit={onSubmit} />);
  await userEvent.selectOptions(screen.getByLabelText("Provider"), "anthropic");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ provider: "anthropic" }));
});
```

### Mocking Connect-RPC Clients

```typescript
jest.mock("../lib/client", () => ({
  client: {
    getNode: jest.fn().mockResolvedValue({ node: { name: "Test", health: 1.0 } }),
  },
}));
```

## Integration Test Conventions (Omega)

- Integration tests live in `tests/` with `_integration` suffix in class name or test name.
- Always use `dry_run=True` or mock adapters for tests that would hit network/disk.
- SkillLoader tests use `tempfile.TemporaryDirectory()` to create isolated skill fixtures.
- Brain tests use `NoBrain` (zero latency, no API calls) unless specifically testing LLM integration.

## Test Execution

```bash
# Python — all tests
pytest tests/ -v

# Python — specific file
pytest tests/test_skill_loader.py -v

# Python — with coverage
pytest tests/ --cov=omega --cov-report=term-missing

# Go — all tests
go test ./... -v

# Go — specific package
go test ./internal/handlers/... -v

# Frontend
cd dashboard && npm test
```
```

- [ ] **Step 2: Commit**

```bash
git add omega/skills/testing/SKILL.md
git commit -m "feat(skills): add testing skill"
```

---

## Task 5: SkillLoader — Tests First

**Files:**
- Create: `tests/test_skill_loader.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_skill_loader.py
"""Unit tests for omega.core.skill_loader.SkillLoader."""

import os
import tempfile
import pytest
from omega.core.skill_loader import SkillLoader, SkillMetadata


SAMPLE_SKILL_A = """\
---
name: skill-alpha
description: Alpha skill for testing
tags:
  - go
  - testing
---

# Skill Alpha

Alpha content here.
"""

SAMPLE_SKILL_B = """\
---
name: skill-beta
description: Beta skill for testing
tags:
  - python
  - testing
---

# Skill Beta

Beta content here.
"""

SKILL_NO_FRONTMATTER = """\
# No frontmatter

Just content.
"""


@pytest.fixture
def skills_dir():
    """Create a temporary skills directory with sample skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Skill A: go + testing tags
        os.makedirs(os.path.join(tmpdir, "skill-alpha"))
        with open(os.path.join(tmpdir, "skill-alpha", "SKILL.md"), "w") as f:
            f.write(SAMPLE_SKILL_A)
        # Skill B: python + testing tags
        os.makedirs(os.path.join(tmpdir, "skill-beta"))
        with open(os.path.join(tmpdir, "skill-beta", "SKILL.md"), "w") as f:
            f.write(SAMPLE_SKILL_B)
        # Dir without SKILL.md — should be ignored
        os.makedirs(os.path.join(tmpdir, "no-skill-dir"))
        # Skill with no frontmatter — should be ignored
        os.makedirs(os.path.join(tmpdir, "bad-skill"))
        with open(os.path.join(tmpdir, "bad-skill", "SKILL.md"), "w") as f:
            f.write(SKILL_NO_FRONTMATTER)
        yield tmpdir


class TestSkillLoaderDiscovery:
    def test_discovers_skills_with_frontmatter(self, skills_dir):
        loader = SkillLoader(skills_dir)
        names = {m.name for m in loader.list_all()}
        assert "skill-alpha" in names
        assert "skill-beta" in names

    def test_ignores_dirs_without_skill_md(self, skills_dir):
        loader = SkillLoader(skills_dir)
        names = {m.name for m in loader.list_all()}
        assert "no-skill-dir" not in names

    def test_ignores_skill_md_without_frontmatter(self, skills_dir):
        loader = SkillLoader(skills_dir)
        names = {m.name for m in loader.list_all()}
        assert "bad-skill" not in names

    def test_metadata_has_correct_tags(self, skills_dir):
        loader = SkillLoader(skills_dir)
        meta = {m.name: m for m in loader.list_all()}
        assert "go" in meta["skill-alpha"].tags
        assert "testing" in meta["skill-alpha"].tags
        assert "python" in meta["skill-beta"].tags

    def test_metadata_has_description(self, skills_dir):
        loader = SkillLoader(skills_dir)
        meta = {m.name: m for m in loader.list_all()}
        assert meta["skill-alpha"].description == "Alpha skill for testing"

    def test_nonexistent_root_returns_empty(self):
        loader = SkillLoader("/nonexistent/path/to/skills")
        assert loader.list_all() == []


class TestSkillLoaderGetSkill:
    def test_get_skill_returns_content_without_frontmatter(self, skills_dir):
        loader = SkillLoader(skills_dir)
        content = loader.get_skill("skill-alpha")
        assert content is not None
        assert "# Skill Alpha" in content
        assert "Alpha content here." in content
        # Frontmatter should be stripped
        assert "---" not in content
        assert "name: skill-alpha" not in content

    def test_get_skill_unknown_name_returns_none(self, skills_dir):
        loader = SkillLoader(skills_dir)
        assert loader.get_skill("nonexistent-skill") is None


class TestSkillLoaderLoadForTags:
    def test_load_for_single_tag_returns_matching_content(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["go"])
        assert "Skill Alpha" in result
        assert "Skill Beta" not in result

    def test_load_for_shared_tag_returns_both(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["testing"])
        assert "Skill Alpha" in result
        assert "Skill Beta" in result

    def test_load_for_tags_deduplicates_skills(self, skills_dir):
        loader = SkillLoader(skills_dir)
        # skill-alpha matches both "go" and "testing"
        result = loader.load_for_tags(["go", "testing"])
        # skill-alpha should appear only once
        assert result.count("Skill Alpha") == 1

    def test_load_for_tags_no_match_returns_empty(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["rust", "haskell"])
        assert result == ""

    def test_load_for_empty_tags_returns_empty(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags([])
        assert result == ""

    def test_load_for_tags_includes_skill_name_header(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["go"])
        assert "## Skill: skill-alpha" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /path/to/omega && pytest tests/test_skill_loader.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `omega.core.skill_loader` does not exist yet.

---

## Task 6: SkillLoader — Implementation

**Files:**
- Create: `omega/core/skill_loader.py`

- [ ] **Step 1: Write the implementation**

```python
"""
omega.core.skill_loader
~~~~~~~~~~~~~~~~~~~~~~~
Discovers, indexes, and serves SKILL.md knowledge artifacts to nodes.

Skills live under a root directory. Each skill is a subdirectory containing
a SKILL.md file with YAML-style frontmatter:

    ---
    name: go-best-practices
    description: Go coding standards for Omega
    tags:
      - go
      - testing
    ---

    # Content here...

Usage::

    loader = SkillLoader("/path/to/omega/skills")
    content = loader.load_for_tags(["go", "protobuf"])  # -> str injected into domain_context
    loader.list_all()                                     # -> List[SkillMetadata]
    loader.get_skill("go-best-practices")                # -> str (content, no frontmatter)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SkillMetadata:
    """Metadata parsed from a SKILL.md frontmatter block."""

    name: str
    description: str
    tags: List[str]
    path: str  # absolute path to the SKILL.md file


class SkillLoader:
    """
    Discovers, indexes, and serves SKILL.md skills by tag.

    Scans `skills_root` on construction. Each subdirectory containing a
    ``SKILL.md`` file with valid YAML frontmatter is indexed as a skill.

    The frontmatter parser is intentionally minimal (stdlib-only, no PyYAML):
    it handles scalar values and block lists but not deeply nested structures.
    """

    def __init__(self, skills_root: str) -> None:
        self._root = skills_root
        self._index: Dict[str, SkillMetadata] = {}       # name -> metadata
        self._tag_index: Dict[str, List[str]] = {}        # tag -> [skill names]
        self._discover()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """Walk skills_root and index all valid SKILL.md files."""
        if not os.path.isdir(self._root):
            return
        for entry in sorted(os.scandir(self._root), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            skill_path = os.path.join(entry.path, "SKILL.md")
            if not os.path.isfile(skill_path):
                continue
            meta = self._parse_frontmatter(skill_path)
            if meta is None:
                continue
            self._index[meta.name] = meta
            for tag in meta.tags:
                self._tag_index.setdefault(tag, []).append(meta.name)

    def _parse_frontmatter(self, path: str) -> Optional[SkillMetadata]:
        """Parse YAML frontmatter from a SKILL.md file. Returns None if invalid."""
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return None

        match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not match:
            return None

        fm = match.group(1)
        name = self._fm_scalar(fm, "name") or os.path.basename(os.path.dirname(path))
        description = self._fm_scalar(fm, "description") or ""
        tags = self._fm_list(fm, "tags")

        return SkillMetadata(name=name, description=description, tags=tags, path=path)

    @staticmethod
    def _fm_scalar(fm: str, key: str) -> Optional[str]:
        """Extract a scalar value: `key: value` → `value`."""
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.MULTILINE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _fm_list(fm: str, key: str) -> List[str]:
        """
        Extract a YAML block list::

            tags:
              - item1
              - item2

        Falls back to inline list: ``tags: [item1, item2]``
        """
        # Block list
        block = re.search(
            rf"^{re.escape(key)}:\n((?:[ \t]+-[ \t]+.+\n?)+)",
            fm,
            re.MULTILINE,
        )
        if block:
            return [
                i.strip()
                for i in re.findall(r"^[ \t]+-[ \t]+(.+)$", block.group(1), re.MULTILINE)
            ]
        # Inline list
        inline = re.search(rf"^{re.escape(key)}:\s+\[(.+)\]$", fm, re.MULTILINE)
        if inline:
            return [t.strip().strip("\"'") for t in inline.group(1).split(",")]
        return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_all(self) -> List[SkillMetadata]:
        """Return metadata for all discovered skills, sorted by name."""
        return list(self._index.values())

    def get_skill(self, name: str) -> Optional[str]:
        """
        Return the body content of a named skill (frontmatter stripped).

        Returns None if the skill is not found.
        """
        meta = self._index.get(name)
        if meta is None:
            return None
        try:
            with open(meta.path, encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return None
        return re.sub(r"^---\n.*?\n---\n", "", raw, count=1, flags=re.DOTALL).strip()

    def load_for_tags(self, tags: List[str]) -> str:
        """
        Return concatenated skill content for all skills matching any of the given tags.

        Each matching skill appears at most once (deduplicated), ordered by
        the order tags appear in the input list, then by insertion order within
        each tag bucket.

        Returns empty string if no tags match or tags list is empty.
        """
        if not tags:
            return ""

        matched_names: List[str] = []
        seen: set[str] = set()
        for tag in tags:
            for name in self._tag_index.get(tag, []):
                if name not in seen:
                    matched_names.append(name)
                    seen.add(name)

        parts: List[str] = []
        for name in matched_names:
            content = self.get_skill(name)
            if content:
                parts.append(f"## Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts)
```

- [ ] **Step 2: Run tests to confirm they pass**

```bash
pytest tests/test_skill_loader.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add omega/core/skill_loader.py tests/test_skill_loader.py
git commit -m "feat(skills): add SkillLoader with tag indexing and tests"
```

---

## Task 7: Wire Skills into BrainRequest and Node

**Files:**
- Modify: `omega/core/brain.py` (BrainRequest)
- Modify: `omega/core/node.py` (Node.skill_tags, Node.consult_brain)

- [ ] **Step 1: Add `skill_hints` to BrainRequest in brain.py**

In `omega/core/brain.py`, update the `BrainRequest` dataclass (line ~70):

```python
@dataclass
class BrainRequest:
    """Everything we give the LLM so it can make a decision."""

    node_id: str
    operation: str                       # "execute" | "evaluate" | "improve" | "analyze"
    current_state: Dict[str, Any]        # node state snapshot
    recent_metrics: Dict[str, float]     # recent evaluation metrics
    relevant_memories: List[Dict]        # from MemoryKernel
    available_actions: List[str]         # verbs the node can take
    domain_context: str                  # node.describe() + injected skill content
    trace_id: str = ""
    skill_hints: List[str] = field(default_factory=list)  # tags used to load skills
```

- [ ] **Step 2: Add `skill_tags` and update `consult_brain` in node.py**

In `omega/core/node.py`, make two changes to the `Node` class:

**2a — Add class attribute after the class docstring:**

```python
class Node(ABC):
    """...(existing docstring)..."""

    # Subclasses override to declare which skill tags apply to this node.
    # These tags are used by consult_brain() to load relevant SKILL.md content
    # and inject it into the brain's domain_context.
    # Example: skill_tags = ["go", "protobuf"]
    skill_tags: List[str] = []
```

**2b — Replace the `consult_brain` method body to inject skills:**

```python
def consult_brain(
    self,
    operation: str,
    metrics: Optional[Dict[str, float]] = None,
    memories: Optional[List[Dict]] = None,
    trace_id: str = "",
) -> "BrainResponse":
    """
    Ask the brain for a decision.

    Builds a BrainRequest from the node's current state and calls
    brain.think(). Injects relevant skill content (from skill_tags) into
    domain_context before calling the brain.

    If brain is NoBrain (default), returns action="pass" immediately.
    """
    from omega.core.brain import BrainRequest
    state = self.get_state()
    if metrics is None:
        try:
            metrics = self.evaluate()
        except Exception:
            metrics = {}

    # Build domain context — start with node description
    domain_context = self.describe()

    # Inject relevant skill content if this node declares skill tags
    tags = list(getattr(self, "skill_tags", []))
    if tags:
        try:
            import os
            from omega.core.skill_loader import SkillLoader
            skills_root = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "skills"
            )
            loader = SkillLoader(os.path.normpath(skills_root))
            skill_content = loader.load_for_tags(tags)
            if skill_content:
                domain_context = f"{domain_context}\n\n# Relevant Skills\n\n{skill_content}"
        except Exception:
            pass  # skills are advisory — never break brain consultation

    request = BrainRequest(
        node_id=state.node_id,
        operation=operation,
        current_state={
            "version": state.version,
            "health": state.health,
            **state.metadata,
        },
        recent_metrics=metrics,
        relevant_memories=memories or [],
        available_actions=self.get_capabilities(),
        domain_context=domain_context,
        trace_id=trace_id,
        skill_hints=tags,
    )
    return self.brain.think(request)
```

- [ ] **Step 3: Run all existing tests to confirm no regressions**

```bash
pytest tests/ -v
```

Expected: All existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add omega/core/brain.py omega/core/node.py
git commit -m "feat(skills): wire SkillLoader into BrainRequest and Node.consult_brain"
```

---

## Task 8: SkillCreatorNode — Tests First

**Files:**
- Create: `tests/test_skill_creator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_skill_creator.py
"""Tests for omega.nodes.skill_creator.SkillCreatorNode."""

import os
import tempfile
import pytest
from omega.core.node import NodeInput
from omega.nodes.skill_creator import SkillCreatorNode


@pytest.fixture
def skill_node():
    """SkillCreatorNode with an isolated temp skills directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        node = SkillCreatorNode(skills_root=tmpdir)
        yield node, tmpdir


class TestSkillCreatorNodeBasic:
    def test_get_capabilities(self, skill_node):
        node, _ = skill_node
        caps = node.get_capabilities()
        assert "create_skill" in caps
        assert "list_skills" in caps
        assert "describe_skill" in caps

    def test_get_state_returns_valid_state(self, skill_node):
        node, _ = skill_node
        state = node.get_state()
        assert state.node_id
        assert state.name == "SkillCreatorNode"
        assert state.health == 1.0

    def test_describe_returns_string(self, skill_node):
        node, _ = skill_node
        desc = node.describe()
        assert isinstance(desc, str)
        assert len(desc) > 10

    def test_unknown_action_fails(self, skill_node):
        node, _ = skill_node
        inp = NodeInput(action="fly", parameters={})
        out = node.execute(inp)
        assert not out.success
        assert out.errors


class TestSkillCreatorNodeCreateSkill:
    def test_create_skill_writes_skill_md(self, skill_node):
        node, tmpdir = skill_node
        inp = NodeInput(
            action="create_skill",
            parameters={
                "name": "my-new-skill",
                "description": "Test skill",
                "tags": ["test", "demo"],
                "content": "# My New Skill\n\nContent here.",
            },
        )
        out = node.execute(inp)
        assert out.success
        skill_path = os.path.join(tmpdir, "my-new-skill", "SKILL.md")
        assert os.path.isfile(skill_path)

    def test_create_skill_file_has_frontmatter(self, skill_node):
        node, tmpdir = skill_node
        inp = NodeInput(
            action="create_skill",
            parameters={
                "name": "frontmatter-skill",
                "description": "Checks frontmatter",
                "tags": ["go"],
                "content": "# Content",
            },
        )
        node.execute(inp)
        with open(os.path.join(tmpdir, "frontmatter-skill", "SKILL.md")) as f:
            raw = f.read()
        assert raw.startswith("---\n")
        assert "name: frontmatter-skill" in raw
        assert "- go" in raw
        assert "# Content" in raw

    def test_create_skill_sanitizes_name(self, skill_node):
        node, tmpdir = skill_node
        inp = NodeInput(
            action="create_skill",
            parameters={
                "name": "My Skill With Spaces!",
                "description": "desc",
                "tags": [],
                "content": "content",
            },
        )
        out = node.execute(inp)
        assert out.success
        safe_name = out.result["skill_name"]
        assert " " not in safe_name
        assert "!" not in safe_name

    def test_create_skill_missing_name_fails(self, skill_node):
        node, _ = skill_node
        inp = NodeInput(
            action="create_skill",
            parameters={"content": "some content"},
        )
        out = node.execute(inp)
        assert not out.success
        assert out.errors

    def test_create_skill_missing_content_fails(self, skill_node):
        node, _ = skill_node
        inp = NodeInput(
            action="create_skill",
            parameters={"name": "my-skill"},
        )
        out = node.execute(inp)
        assert not out.success

    def test_request_id_propagated(self, skill_node):
        node, _ = skill_node
        inp = NodeInput(
            action="create_skill",
            parameters={"name": "id-test", "content": "c", "tags": []},
        )
        out = node.execute(inp)
        # Whether success or not, request_id must match
        assert out.request_id == inp.request_id


class TestSkillCreatorNodeListSkills:
    def test_list_skills_empty_initially(self, skill_node):
        node, _ = skill_node
        inp = NodeInput(action="list_skills", parameters={})
        out = node.execute(inp)
        assert out.success
        assert out.result == []

    def test_list_skills_shows_created_skill(self, skill_node):
        node, _ = skill_node
        # Create a skill first
        node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "listed-skill", "description": "Listed", "tags": ["go"], "content": "body"},
        ))
        # Now list
        out = node.execute(NodeInput(action="list_skills", parameters={}))
        assert out.success
        names = [s["name"] for s in out.result]
        assert "listed-skill" in names


class TestSkillCreatorNodeDescribeSkill:
    def test_describe_skill_returns_content(self, skill_node):
        node, _ = skill_node
        node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "described-skill", "description": "d", "tags": [], "content": "# Body\nHello."},
        ))
        out = node.execute(NodeInput(
            action="describe_skill",
            parameters={"name": "described-skill"},
        ))
        assert out.success
        assert "# Body" in out.result
        assert "Hello." in out.result

    def test_describe_unknown_skill_fails(self, skill_node):
        node, _ = skill_node
        out = node.execute(NodeInput(
            action="describe_skill",
            parameters={"name": "nonexistent"},
        ))
        assert not out.success


class TestSkillCreatorNodeIntegration:
    """Integration test: node loads skills via skill_tags during brain consultation."""

    def test_skill_tags_declared(self, skill_node):
        node, _ = skill_node
        assert "research" in node.skill_tags

    def test_consult_brain_returns_response_with_no_brain(self, skill_node):
        """NoBrain returns action='pass' — confirms consult_brain wiring works."""
        node, _ = skill_node
        response = node.consult_brain("improve")
        assert response.action == "pass"

    def test_evaluate_returns_metrics(self, skill_node):
        node, _ = skill_node
        metrics = node.evaluate()
        assert "execution_count" in metrics
        assert "error_rate" in metrics
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_skill_creator.py -v
```

Expected: `ImportError` — `omega.nodes.skill_creator` does not exist yet.

---

## Task 9: SkillCreatorNode — Implementation

**Files:**
- Create: `omega/nodes/skill_creator.py`

- [ ] **Step 1: Write the implementation**

```python
"""
omega.nodes.skill_creator
~~~~~~~~~~~~~~~~~~~~~~~~~
A capability node that creates and manages skill documentation files.

SkillCreatorNode writes new SKILL.md artifacts to the omega/skills/ directory.
It uses the deep-research skill (via skill_tags) when consulting its brain for
help formulating skill content.

Capabilities:
  create_skill   — write a new SKILL.md for a given domain
  list_skills    — list all known skills with metadata
  describe_skill — return the content of a specific skill
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.skill_loader import SkillLoader


class SkillCreatorNode(Node):
    """
    Creates new skill documentation artifacts.

    Writes SKILL.md files to the skills directory. Each skill file contains
    YAML frontmatter (name, description, tags) followed by markdown content.

    The node uses the deep-research skill when its brain is consulted,
    enabling an LLM brain to apply the IterDRAG pattern when generating
    comprehensive skill documentation.

    Usage::
        node = SkillCreatorNode()
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={
                "name": "my-domain",
                "description": "Best practices for my domain",
                "tags": ["my-domain", "go"],
                "content": "# My Domain\\n\\n...",
            },
        ))
    """

    skill_tags: List[str] = ["research"]

    def __init__(
        self,
        skills_root: Optional[str] = None,
        brain_config=None,
    ) -> None:
        super().__init__(brain_config)
        if skills_root is None:
            skills_root = os.path.normpath(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills")
            )
        self._skills_root = skills_root
        self._loader = SkillLoader(self._skills_root)
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        error_rate = self._error_count / max(1, self._execution_count)
        return NodeState(
            node_id=self._node_id,
            name="SkillCreatorNode",
            version=self._version,
            health=max(0.0, 1.0 - error_rate),
            capabilities=self.get_capabilities(),
            metrics={
                "execution_count": float(self._execution_count),
                "error_rate": error_rate,
                "skill_count": float(len(self._loader.list_all())),
            },
            metadata={"skills_root": self._skills_root},
        )

    def get_capabilities(self) -> List[str]:
        return ["create_skill", "list_skills", "describe_skill"]

    def describe(self) -> str:
        return (
            "SkillCreatorNode creates and manages SKILL.md knowledge artifacts. "
            "It writes new skills to the omega/skills/ directory, lists existing skills, "
            "and retrieves skill content. Use it to bootstrap new domain knowledge for nodes."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        try:
            if input.action == "create_skill":
                result = self._create_skill(input.parameters)
            elif input.action == "list_skills":
                result = self._list_skills()
            elif input.action == "describe_skill":
                result = self._describe_skill(input.parameters.get("name", ""))
            else:
                self._error_count += 1
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"SkillCreatorNode: unknown action '{input.action}'"],
                    metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
                )
            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
            )
        except Exception as exc:
            self._error_count += 1
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
            )

    def evaluate(self) -> Dict[str, float]:
        return {
            "execution_count": float(self._execution_count),
            "error_rate": self._error_count / max(1, self._execution_count),
            "skill_count": float(len(self._loader.list_all())),
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        # SkillCreatorNode improves by reloading its skill index
        old_count = len(self._loader.list_all())
        self._loader = SkillLoader(self._skills_root)
        new_count = len(self._loader.list_all())
        return new_count != old_count

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _create_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Write a new SKILL.md file to the skills directory."""
        name = str(params.get("name", "")).strip()
        tags: List[str] = list(params.get("tags", []))
        description = str(params.get("description", "")).strip()
        content = str(params.get("content", "")).strip()

        if not name:
            raise ValueError("'name' parameter is required")
        if not content:
            raise ValueError("'content' parameter is required")

        # Sanitise name for filesystem: lowercase alphanumeric + hyphens
        safe_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not safe_name:
            raise ValueError(f"'name' yields empty filesystem name after sanitisation: {name!r}")

        skill_dir = os.path.join(self._skills_root, safe_name)
        os.makedirs(skill_dir, exist_ok=True)

        tags_yaml = (
            "\n".join(f"  - {t}" for t in tags) if tags else "  - general"
        )
        skill_md = (
            f"---\n"
            f"name: {safe_name}\n"
            f"description: {description}\n"
            f"tags:\n{tags_yaml}\n"
            f"---\n\n"
            f"{content}\n"
        )

        skill_path = os.path.join(skill_dir, "SKILL.md")
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skill_md)

        # Refresh the index
        self._loader = SkillLoader(self._skills_root)

        return {"skill_name": safe_name, "path": skill_path, "tags": tags}

    def _list_skills(self) -> List[Dict[str, Any]]:
        """Return metadata for all known skills."""
        return [
            {"name": m.name, "description": m.description, "tags": m.tags}
            for m in self._loader.list_all()
        ]

    def _describe_skill(self, name: str) -> str:
        """Return the body content of a named skill (frontmatter stripped)."""
        content = self._loader.get_skill(name)
        if content is None:
            raise ValueError(f"Skill '{name}' not found in {self._skills_root!r}")
        return content
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests pass (skill_loader + skill_creator + all existing tests).

- [ ] **Step 3: Commit**

```bash
git add omega/nodes/skill_creator.py tests/test_skill_creator.py
git commit -m "feat(skills): add SkillCreatorNode with tests"
```

---

## Task 10: Final Integration Verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass, no errors.

- [ ] **Step 2: Smoke-test the complete skill system**

```python
# Run from repo root: python -c "..."
from omega.core.skill_loader import SkillLoader
import os

root = os.path.join(os.path.dirname(os.path.abspath("omega")), "omega", "skills")
loader = SkillLoader(root)
skills = loader.list_all()
print(f"Found {len(skills)} skills:")
for s in skills:
    print(f"  {s.name}: {s.tags}")

content = loader.load_for_tags(["go"])
print(f"\ngo-tagged content length: {len(content)} chars")
```

Expected: 4 skills found (go-best-practices, deep-research, protobuf-connect, testing), non-zero content for "go" tag.

- [ ] **Step 3: Commit final state**

```bash
git add -p  # review and stage any remaining changes
git commit -m "feat(skills): complete skill infrastructure — loader, 4 skills, SkillCreatorNode"
```
