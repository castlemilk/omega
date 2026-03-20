---
name: testing
description: Go table-driven tests, Python pytest patterns, React Testing Library, property-based testing, and integration test conventions for Omega
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

### Test Helpers — Always Use t.Helper()

```go
func assertNoError(t *testing.T, err error) {
    t.Helper()  // failure line points to the caller, not here
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
}
```

### Integration Tests — Skip When Dependencies Absent

```go
func TestOmegaAPIIntegration(t *testing.T) {
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
    f.Fuzz(func(t *testing.T, id string) {
        result := ParseNodeID(id)  // must never panic
        _ = result
    })
}
```

Run: `go test -fuzz FuzzParseNodeID -fuzztime 30s`

---

## Python Testing (pytest)

### Class-Based Organization (Omega Pattern)

```python
class TestCalculatorNode:
    def setup_method(self):
        """Fresh instance before each test."""
        self.node = CalculatorNode()

    def test_add_basic(self):
        out = self.node.execute(NodeInput(action="add", parameters={"a": 3, "b": 4}))
        assert out.success
        assert out.result == 7.0

    def test_request_id_propagated(self):
        inp = NodeInput(action="add", parameters={"a": 1, "b": 1})
        out = self.node.execute(inp)
        assert out.request_id == inp.request_id
```

### Error Cases — Always Test Explicitly

```python
def test_divide_by_zero(self):
    out = self.node.execute(NodeInput(action="divide", parameters={"a": 10, "b": 0}))
    assert not out.success
    assert any("zero" in e.lower() for e in out.errors)
```

### State Transition Tests

```python
def test_improvement_changes_version(self):
    assert self.node.version == "1.0"
    changed = self.node.improve({"improve_latency": True, "iteration": 0})
    assert changed is True
    assert self.node.version == "1.1"
```

### Isolated Filesystem Tests

```python
import tempfile, os

def test_writes_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        node = SkillCreatorNode(skills_root=tmpdir)
        # ... test file creation in isolation
        assert os.path.isfile(os.path.join(tmpdir, "my-skill", "SKILL.md"))
```

### NoBrain for Unit Tests

When testing nodes with brain integration, use the default `NoBrain` (no API calls, zero latency):

```python
def test_consult_brain_with_no_brain(self):
    node = MyNode()  # default: NoBrain
    response = node.consult_brain("improve")
    assert response.action == "pass"  # NoBrain always returns "pass"
```

---

## React Testing Library

### Component Unit Tests

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
import userEvent from "@testing-library/user-event";

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

---

## Integration Test Conventions (Omega)

- Python integration tests: use `dry_run=True` or mock adapters for anything touching network/disk.
- SkillLoader tests: always use `tempfile.TemporaryDirectory()` — never pollute the real skills dir.
- Brain tests: use `NoBrain` unless specifically testing LLM integration.
- Go integration tests: guard with `t.Skip` when env vars absent.

## Test Execution

```bash
# Python — all tests
pytest tests/ -v

# Python — specific file
pytest tests/test_skill_loader.py -v

# Python — with coverage
pytest tests/ --cov=omega --cov-report=term-missing

# Go — all
go test ./... -v

# Frontend
cd dashboard && npm test
```
