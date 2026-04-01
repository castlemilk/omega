package controlplane

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/heartbeat"
)

func newTestHandler() *Handler {
	store := heartbeat.New()
	ls := heartbeat.NewLifecycleStore()
	ds := heartbeat.NewDecisionStore()
	h := New(store, nil)
	h.WithLifecycleStore(ls).WithDecisionStore(ds)
	return h
}

// ── Lifecycle endpoints ───────────────────────────────────────────────────────

func TestHandlePostLifecycle(t *testing.T) {
	h := newTestHandler()
	body := `{"from_state":"STARTING","to_state":"RUNNING","reason":"ready"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/nodes/node-a/lifecycle", bytes.NewBufferString(body))
	w := httptest.NewRecorder()

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("want 200, got %d: %s", w.Code, w.Body.String())
	}
}

func TestHandleGetLifecycle(t *testing.T) {
	h := newTestHandler()
	h.lifecycle.RecordEvent(heartbeat.LifecycleEvent{
		NodeID:    "node-a",
		FromState: heartbeat.StateStarting,
		ToState:   heartbeat.StateRunning,
		Reason:    "test",
		Timestamp: time.Now(),
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/nodes/node-a/lifecycle", nil)
	w := httptest.NewRecorder()

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	var resp lifecycleResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if len(resp.Events) != 1 {
		t.Errorf("want 1 event, got %d", len(resp.Events))
	}
}

// ── Decision endpoints ────────────────────────────────────────────────────────

func TestHandlePostDecision(t *testing.T) {
	h := newTestHandler()
	body := `{"cycle":5,"snapshot_json":"{\"regime\":\"bull\"}"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/nodes/node-b/decisions", bytes.NewBufferString(body))
	w := httptest.NewRecorder()

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("want 200, got %d: %s", w.Code, w.Body.String())
	}
}

func TestHandleGetDecisions(t *testing.T) {
	h := newTestHandler()
	h.decisions.RecordDecision(heartbeat.DecisionEntry{
		NodeID: "node-b", Cycle: 5, ReceivedAt: time.Now(), SnapshotJSON: `{}`,
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/nodes/node-b/decisions", nil)
	w := httptest.NewRecorder()

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	var resp decisionsResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if len(resp.Decisions) != 1 {
		t.Errorf("want 1 decision, got %d", len(resp.Decisions))
	}
}

func TestHandleGetDecisionByCycle(t *testing.T) {
	h := newTestHandler()
	h.decisions.RecordDecision(heartbeat.DecisionEntry{
		NodeID: "node-c", Cycle: 42, ReceivedAt: time.Now(), SnapshotJSON: `{"cycle":42}`,
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/nodes/node-c/decisions/42", nil)
	w := httptest.NewRecorder()

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
}

// ── Health endpoint ───────────────────────────────────────────────────────────

func TestHandleNodeHealth(t *testing.T) {
	h := newTestHandler()
	h.store.RecordHeartbeat(&omegav1.Heartbeat{
		NodeId:   "node-d",
		NodeType: "TRAINING_LOOP",
		Health:   omegav1.NodeHealth_NODE_HEALTH_HEALTHY,
		Metrics:  map[string]string{"closed_trades": "5", "active_signals": "7", "total_signals": "10", "regime": "bull"},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/nodes/node-d/health", nil)
	w := httptest.NewRecorder()

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp nodeHealthJSON
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp.Score < 0 || resp.Score > 100 {
		t.Errorf("score out of range: %d", resp.Score)
	}
}

// ── Platform status endpoint ──────────────────────────────────────────────────

func TestHandlePlatformStatus(t *testing.T) {
	h := newTestHandler()
	h.store.RecordHeartbeat(&omegav1.Heartbeat{
		NodeId:  "node-e",
		Health:  omegav1.NodeHealth_NODE_HEALTH_HEALTHY,
		Metrics: map[string]string{"closed_trades": "3", "pnl": "100.5"},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/platform/status", nil)
	w := httptest.NewRecorder()

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp platformStatusJSON
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Nodes) != 1 {
		t.Errorf("want 1 node, got %d", len(resp.Nodes))
	}
}
