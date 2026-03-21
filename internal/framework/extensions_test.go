package framework_test

import (
	"context"
	"errors"
	"testing"

	"github.com/benebsworth/omega/internal/framework"
)

// --- stub hooks ---

type stubPreCycleHook struct {
	calls []int64
	err   error
}

func (h *stubPreCycleHook) PreCycle(_ context.Context, cycle int64) error {
	h.calls = append(h.calls, cycle)
	return h.err
}

type stubPostCycleHook struct {
	calls []int64
	errs  []error
}

func (h *stubPostCycleHook) PostCycle(_ context.Context, cycle int64, err error) error {
	h.calls = append(h.calls, cycle)
	h.errs = append(h.errs, err)
	return nil
}

type stubNodeRegHook struct {
	ids []string
}

func (h *stubNodeRegHook) OnNodeRegistered(_ context.Context, nodeID string) error {
	h.ids = append(h.ids, nodeID)
	return nil
}

type stubMetricHook struct {
	metrics []framework.Metric
}

func (h *stubMetricHook) OnMetricCollected(_ context.Context, m framework.Metric) {
	h.metrics = append(h.metrics, m)
}

// --- tests ---

func TestExtensionRegistry_PreCycleHooks(t *testing.T) {
	reg := framework.NewExtensionRegistry()

	h1 := &stubPreCycleHook{}
	h2 := &stubPreCycleHook{}

	reg.AddPreCycleHook(h1)
	reg.AddPreCycleHook(h2)

	if err := reg.RunPreCycle(context.Background(), 7); err != nil {
		t.Fatalf("RunPreCycle: %v", err)
	}

	if len(h1.calls) != 1 || h1.calls[0] != 7 {
		t.Fatalf("h1: expected calls=[7], got %v", h1.calls)
	}
	if len(h2.calls) != 1 || h2.calls[0] != 7 {
		t.Fatalf("h2: expected calls=[7], got %v", h2.calls)
	}
}

func TestExtensionRegistry_PreCycleHookErrorStops(t *testing.T) {
	reg := framework.NewExtensionRegistry()

	boom := errors.New("boom")
	h1 := &stubPreCycleHook{err: boom}
	h2 := &stubPreCycleHook{}

	reg.AddPreCycleHook(h1)
	reg.AddPreCycleHook(h2)

	err := reg.RunPreCycle(context.Background(), 1)
	if !errors.Is(err, boom) {
		t.Fatalf("expected boom error, got %v", err)
	}
	// h2 should not have been called since h1 failed
	if len(h2.calls) != 0 {
		t.Fatal("expected h2 not called after h1 error")
	}
}

func TestExtensionRegistry_PostCycleHooks(t *testing.T) {
	reg := framework.NewExtensionRegistry()

	h := &stubPostCycleHook{}
	reg.AddPostCycleHook(h)

	cycleErr := errors.New("cycle failed")
	if err := reg.RunPostCycle(context.Background(), 3, cycleErr); err != nil {
		t.Fatalf("RunPostCycle: %v", err)
	}

	if len(h.calls) != 1 || h.calls[0] != 3 {
		t.Fatalf("expected calls=[3], got %v", h.calls)
	}
	if !errors.Is(h.errs[0], cycleErr) {
		t.Fatalf("expected cycleErr passed through, got %v", h.errs[0])
	}
}

func TestExtensionRegistry_NodeRegistrationHooks(t *testing.T) {
	reg := framework.NewExtensionRegistry()

	h := &stubNodeRegHook{}
	reg.AddNodeRegistrationHook(h)

	if err := reg.RunNodeRegistered(context.Background(), "node-xyz"); err != nil {
		t.Fatalf("RunNodeRegistered: %v", err)
	}

	if len(h.ids) != 1 || h.ids[0] != "node-xyz" {
		t.Fatalf("expected ids=[node-xyz], got %v", h.ids)
	}
}

func TestExtensionRegistry_MetricCollectionHooks(t *testing.T) {
	reg := framework.NewExtensionRegistry()

	h := &stubMetricHook{}
	reg.AddMetricCollectionHook(h)

	m := framework.Metric{Name: "latency_ms", Value: 42.5, Labels: map[string]string{"node": "n1"}}
	reg.RunMetricCollected(context.Background(), m)

	if len(h.metrics) != 1 {
		t.Fatalf("expected 1 metric, got %d", len(h.metrics))
	}
	if h.metrics[0].Name != "latency_ms" || h.metrics[0].Value != 42.5 {
		t.Fatalf("unexpected metric: %+v", h.metrics[0])
	}
}

func TestExtensionRegistry_RemoveHooks(t *testing.T) {
	reg := framework.NewExtensionRegistry()

	h := &stubPreCycleHook{}
	id := reg.AddPreCycleHook(h)
	reg.RemovePreCycleHook(id)

	_ = reg.RunPreCycle(context.Background(), 1)
	if len(h.calls) != 0 {
		t.Fatal("expected hook removed, but it was called")
	}
}

func TestExtensionRegistry_MultipleRunsAccumulate(t *testing.T) {
	reg := framework.NewExtensionRegistry()

	h := &stubPreCycleHook{}
	reg.AddPreCycleHook(h)

	for i := int64(0); i < 5; i++ {
		_ = reg.RunPreCycle(context.Background(), i)
	}

	if len(h.calls) != 5 {
		t.Fatalf("expected 5 calls, got %d", len(h.calls))
	}
}
