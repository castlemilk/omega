package middleware

import (
	"context"
	"errors"
	"testing"
	"time"
)

// ── Helpers ────────────────────────────────────────────────────────────────

// echoFinal is a FinalHandler that returns the payload as the result.
func echoFinal(_ context.Context, req *ExecutionRequest) (*ExecutionResponse, error) {
	return &ExecutionResponse{Result: req.Payload, Metadata: make(map[string]string)}, nil
}

// errorFinal always returns an error.
func errorFinal(_ context.Context, _ *ExecutionRequest) (*ExecutionResponse, error) {
	return nil, errors.New("final handler error")
}

// orderMiddleware appends its label to the response Metadata["order"] so tests
// can verify execution order.
type orderMiddleware struct{ label string }

func (o *orderMiddleware) Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error) {
	resp, err := next(ctx, req)
	if err != nil {
		return nil, err
	}
	resp.Metadata["order"] += o.label
	return resp, nil
}

// recordingMemoryStore captures calls for assertion.
type recordingMemoryStore struct {
	queryResult string
	queryErr    error
	storedKey   string
	storedValue string
}

func (r *recordingMemoryStore) QueryRelevant(_ context.Context, nodeID, action string) (string, error) {
	r.storedKey = nodeID + ":" + action
	return r.queryResult, r.queryErr
}
func (r *recordingMemoryStore) StoreLearning(_ context.Context, _, _, learning string) error {
	r.storedValue = learning
	return nil
}

func newReq(action string) *ExecutionRequest {
	return &ExecutionRequest{
		NodeID:        "node-1",
		Action:        action,
		Payload:       []byte("data"),
		Metadata:      make(map[string]string),
		AutonomyLevel: AutonomyAutonomous,
	}
}

// ── Tests ──────────────────────────────────────────────────────────────────

func TestChainExecutionOrder(t *testing.T) {
	a := &orderMiddleware{"A"}
	b := &orderMiddleware{"B"}
	c := &orderMiddleware{"C"}

	chain := NewChain(echoFinal, a, b, c)
	req := newReq("read")

	resp, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Post-processing runs in reverse order: C → B → A
	want := "CBA"
	if got := resp.Metadata["order"]; got != want {
		t.Errorf("execution order: got %q, want %q", got, want)
	}
}

func TestChainEmptyMiddleware(t *testing.T) {
	chain := NewChain(echoFinal)
	req := newReq("read")
	req.Payload = []byte("hello")

	resp, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(resp.Result) != "hello" {
		t.Errorf("result: got %q, want %q", resp.Result, "hello")
	}
}

// ── Loop detection ─────────────────────────────────────────────────────────

func TestLoopDetectionWarn(t *testing.T) {
	ld := NewLoopDetectionMiddleware()
	chain := NewChain(echoFinal, ld)
	req := newReq("read")

	// Call up to warn threshold − 1: should succeed silently.
	for i := 0; i < loopWarnThreshold-1; i++ {
		_, err := chain.Execute(context.Background(), req)
		if err != nil {
			t.Fatalf("call %d: unexpected error: %v", i+1, err)
		}
	}

	// Call at warn threshold: should succeed (warn only).
	_, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Errorf("warn-threshold call should succeed, got error: %v", err)
	}
}

func TestLoopDetectionTerminate(t *testing.T) {
	ld := NewLoopDetectionMiddleware()
	chain := NewChain(echoFinal, ld)
	req := newReq("read")

	// Exhaust calls up to error threshold − 1.
	for i := 0; i < loopErrorThreshold-1; i++ {
		_, _ = chain.Execute(context.Background(), req)
	}

	// This call hits the error threshold and must fail.
	_, err := chain.Execute(context.Background(), req)
	if err == nil {
		t.Error("expected loop detection error at error threshold, got nil")
	}
}

// ── Autonomy gating ────────────────────────────────────────────────────────

func TestAutonomyGatePICOBlocked(t *testing.T) {
	gate := NewAutonomyGateMiddleware()
	chain := NewChain(echoFinal, gate)

	req := newReq("delete")
	req.AutonomyLevel = AutonomyPICO

	_, err := chain.Execute(context.Background(), req)
	if err == nil {
		t.Error("expected PICO gate to block 'delete', got nil error")
	}
}

func TestAutonomyGatePICOAllowsRead(t *testing.T) {
	gate := NewAutonomyGateMiddleware()
	chain := NewChain(echoFinal, gate)

	req := newReq("read")
	req.AutonomyLevel = AutonomyPICO

	_, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Errorf("PICO should allow 'read', got error: %v", err)
	}
}

func TestAutonomyGateSupervisedFlagsDangerous(t *testing.T) {
	gate := NewAutonomyGateMiddleware()
	chain := NewChain(echoFinal, gate)

	req := newReq("delete")
	req.AutonomyLevel = AutonomySupervisedLevel

	_, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("SUPERVISED should allow 'delete', got error: %v", err)
	}
	if req.Metadata[MetaKeyDangerousFlagged] != "delete" {
		t.Errorf("expected dangerous flag set to 'delete', got %q", req.Metadata[MetaKeyDangerousFlagged])
	}
}

func TestAutonomyGateAutonomousUnrestricted(t *testing.T) {
	gate := NewAutonomyGateMiddleware()
	chain := NewChain(echoFinal, gate)

	for _, action := range []string{"delete", "drop", "execute", "deploy"} {
		req := newReq(action)
		req.AutonomyLevel = AutonomyAutonomous
		_, err := chain.Execute(context.Background(), req)
		if err != nil {
			t.Errorf("AUTONOMOUS should allow %q, got error: %v", action, err)
		}
	}
}

// ── Context recovery ───────────────────────────────────────────────────────

func TestContextRecoverySignalInjection(t *testing.T) {
	cr := NewContextRecoveryMiddleware(5)
	chain := NewChain(echoFinal, cr)

	req := newReq("read")
	req.Depth = 5 // exactly at threshold

	resp, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	_ = resp // recovery is injected into req.Metadata before final handler runs
	if req.Metadata[MetaKeyContextRecovery] != "true" {
		t.Errorf("expected context_recovery=true in metadata, got %q", req.Metadata[MetaKeyContextRecovery])
	}
}

func TestContextRecoveryNoSignalBelowThreshold(t *testing.T) {
	cr := NewContextRecoveryMiddleware(10)
	chain := NewChain(echoFinal, cr)

	req := newReq("read")
	req.Depth = 9

	_, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if v := req.Metadata[MetaKeyContextRecovery]; v != "" {
		t.Errorf("expected no recovery signal below threshold, got %q", v)
	}
}

// ── Metrics timing ─────────────────────────────────────────────────────────

func TestMetricsTimingAccuracy(t *testing.T) {
	const sleep = 10 * time.Millisecond

	slowFinal := func(_ context.Context, req *ExecutionRequest) (*ExecutionResponse, error) {
		time.Sleep(sleep)
		return &ExecutionResponse{Result: req.Payload, Metadata: make(map[string]string)}, nil
	}

	counters := new(Counters)
	mc := NewMetricsCollectorMiddleware(counters)
	chain := NewChain(slowFinal, mc)

	resp, err := chain.Execute(context.Background(), newReq("read"))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if resp.Duration < sleep {
		t.Errorf("duration %v is less than sleep %v", resp.Duration, sleep)
	}
	if counters.Total.Load() != 1 {
		t.Errorf("total counter: got %d, want 1", counters.Total.Load())
	}
	if counters.Success.Load() != 1 {
		t.Errorf("success counter: got %d, want 1", counters.Success.Load())
	}
	if counters.Errors.Load() != 0 {
		t.Errorf("error counter: got %d, want 0", counters.Errors.Load())
	}
}

func TestMetricsCountsErrors(t *testing.T) {
	counters := new(Counters)
	mc := NewMetricsCollectorMiddleware(counters)
	chain := NewChain(errorFinal, mc)

	_, err := chain.Execute(context.Background(), newReq("read"))
	if err == nil {
		t.Fatal("expected error from errorFinal")
	}

	if counters.Errors.Load() != 1 {
		t.Errorf("error counter: got %d, want 1", counters.Errors.Load())
	}
	if counters.Success.Load() != 0 {
		t.Errorf("success counter: got %d, want 0", counters.Success.Load())
	}
}

// ── Ring validation ────────────────────────────────────────────────────────

func TestRingValidationFlagSet(t *testing.T) {
	rv := NewRingValidationMiddleware()
	chain := NewChain(echoFinal, rv)

	req := newReq("deploy")
	req.AutonomyLevel = AutonomySupervisedLevel

	_, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if req.Metadata[MetaKeyRingValidationRequired] != "deploy" {
		t.Errorf("expected ring_validation_required=deploy, got %q", req.Metadata[MetaKeyRingValidationRequired])
	}
}

func TestRingValidationNotSetForPICO(t *testing.T) {
	rv := NewRingValidationMiddleware()
	chain := NewChain(echoFinal, rv)

	req := newReq("deploy")
	req.AutonomyLevel = AutonomyPICO

	_, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if v := req.Metadata[MetaKeyRingValidationRequired]; v != "" {
		t.Errorf("ring validation should not be set at PICO level, got %q", v)
	}
}

// ── Memory injection ───────────────────────────────────────────────────────

func TestMemoryInjectionContextInjected(t *testing.T) {
	store := &recordingMemoryStore{queryResult: "prior context"}
	mi := NewMemoryInjectionMiddleware(store)
	chain := NewChain(echoFinal, mi)

	req := newReq("read")
	_, err := chain.Execute(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if req.Metadata[MetaKeyMemoryContext] != "prior context" {
		t.Errorf("memory context not injected: got %q", req.Metadata[MetaKeyMemoryContext])
	}
}

func TestMemoryInjectionLearningStored(t *testing.T) {
	store := &recordingMemoryStore{}
	mi := NewMemoryInjectionMiddleware(store)

	learningFinal := func(_ context.Context, req *ExecutionRequest) (*ExecutionResponse, error) {
		return &ExecutionResponse{
			Result: req.Payload,
			Metadata: map[string]string{
				MetaKeyMemoryLearnings: "learned something",
			},
		}, nil
	}

	chain := NewChain(learningFinal, mi)
	_, err := chain.Execute(context.Background(), newReq("read"))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if store.storedValue != "learned something" {
		t.Errorf("expected learning stored, got %q", store.storedValue)
	}
}
