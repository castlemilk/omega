package handler_test

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ── /api/v1/training/jsonl ────────────────────────────────────────────────────

// TestJSONL_PrefersDurableCopy: run_training.py copies the per-cycle metrics
// JSONL into the data dir at run end; the handler must serve that copy rather
// than the ephemeral /tmp sink (which may be gone after a reboot).
func TestJSONL_PrefersDurableCopy(t *testing.T) {
	dataDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dataDir, "v901_metrics.jsonl"),
		[]byte("{\"cycle\":1,\"pnl\":10.5}\n{\"cycle\":2,\"pnl\":-3.25}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	srv, closeFn := newTrainingServer(t, dataDir, "")
	defer closeFn()

	var rows []map[string]any
	resp := getJSON(t, srv.URL+"/api/v1/training/jsonl?version=v901", &rows)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if len(rows) != 2 {
		t.Fatalf("rows = %d, want 2", len(rows))
	}
	if rows[0]["cycle"].(float64) != 1 || rows[1]["pnl"].(float64) != -3.25 {
		t.Fatalf("unexpected rows: %v", rows)
	}
}

// TestJSONL_RejectsUnsafeVersion: a version with path separators must never be
// interpolated into a filename; the response is an empty array, not a probe.
func TestJSONL_RejectsUnsafeVersion(t *testing.T) {
	srv, closeFn := newTrainingServer(t, t.TempDir(), "")
	defer closeFn()

	resp, err := http.Get(srv.URL + "/api/v1/training/jsonl?version=..%2F..%2Fetc%2Fpasswd") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	body, _ := io.ReadAll(resp.Body)
	var rows []json.RawMessage
	if err := json.Unmarshal(body, &rows); err != nil {
		t.Fatalf("body %q not a JSON array: %v", body, err)
	}
	if len(rows) != 0 {
		t.Fatalf("rows = %d, want 0", len(rows))
	}
}

// TestJSONL_MissingFileIsEmptyArray keeps the established contract: no metrics
// file (durable or /tmp) answers 200 with [].
func TestJSONL_MissingFileIsEmptyArray(t *testing.T) {
	srv, closeFn := newTrainingServer(t, t.TempDir(), "")
	defer closeFn()

	var rows []json.RawMessage
	resp := getJSON(t, srv.URL+"/api/v1/training/jsonl?version=v902_never_ran", &rows)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if len(rows) != 0 {
		t.Fatalf("rows = %d, want 0", len(rows))
	}
}

// ── /api/v1/signals/ic-history ────────────────────────────────────────────────

func TestICHistory_ServesFileVerbatim(t *testing.T) {
	dataDir := t.TempDir()
	fixture := map[string]any{
		"updated_at":        "2026-07-01T00:00:00Z",
		"signals":           map[string]any{},
		"seeded_pooled_ics": map[string]any{"rsi_signal": 0.031, "macd_crossover": -0.008},
		"seeded_regime_ics": map[string]any{
			"rsi_signal": map[string]any{"normal": 0.04, "crisis": 0.01, "high_vol": 0.02},
		},
		"seed_provenance": map[string]any{"version": "v212"},
	}
	raw, _ := json.Marshal(fixture)
	if err := os.WriteFile(filepath.Join(dataDir, "signal_ic_history.json"), raw, 0o600); err != nil {
		t.Fatal(err)
	}
	srv, closeFn := newTrainingServer(t, dataDir, "")
	defer closeFn()

	var got map[string]any
	resp := getJSON(t, srv.URL+"/api/v1/signals/ic-history", &got)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	pooled, ok := got["seeded_pooled_ics"].(map[string]any)
	if !ok {
		t.Fatalf("seeded_pooled_ics missing: %v", got)
	}
	if pooled["rsi_signal"].(float64) != 0.031 {
		t.Fatalf("rsi_signal = %v, want 0.031", pooled["rsi_signal"])
	}
	if got["seed_provenance"].(map[string]any)["version"] != "v212" {
		t.Fatalf("seed_provenance not passed through: %v", got["seed_provenance"])
	}
}

// TestICHistory_MissingFileIs404: absence must be loud and name the path —
// an empty-200 here would render as "no signals" and hide a misconfigured
// data dir.
func TestICHistory_MissingFileIs404(t *testing.T) {
	srv, closeFn := newTrainingServer(t, t.TempDir(), "")
	defer closeFn()

	resp, err := http.Get(srv.URL + "/api/v1/signals/ic-history") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	body, _ := io.ReadAll(resp.Body)
	if want := "signal_ic_history.json"; !strings.Contains(string(body), want) {
		t.Fatalf("404 body %q does not name %q", body, want)
	}
}
