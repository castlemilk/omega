package handler_test

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/handler"
)

// Fixtures under testdata/training are copies (some trimmed) of real repo files:
//
//	data/training_progress.json                → the exact bytes that used to 500
//	data/v94_gate_result.json                  → gate report (omega/eval/v49_gates.py)
//	data/bt_v132a_crisis_gate_result.json      → gate report for a backtest cell
//	data/v93-v94-forensics.json                → trimmed (arrays capped) forensics
//	                                             report (omega/tools/forensics/run_diff.py)
//	omega/nodes/victoria/training_log/*.md     → V148 (pre-registration only),
//	                                             V206b (lowercase suffix), V261 +
//	                                             V261_VERDICT, V262 + V262_AUDIT_VERDICT
const (
	fixtureDataDir = "testdata/training/data"
	fixtureLogDir  = "testdata/training/training_log"
)

// newTrainingServer mounts a TrainingHandler over the given data/log dirs.
// The *db.DB is nil: none of the file-backed endpoints under test touch it.
func newTrainingServer(t *testing.T, dataDir, logDir string) (*httptest.Server, func()) {
	t.Helper()
	h := handler.NewTrainingHandler(nil, dataDir)
	if logDir != "" {
		h.SetTrainingLogDir(logDir)
	}
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	srv := httptest.NewServer(mux)
	return srv, srv.Close
}

// copyFixture copies a fixture file into dst (usually a t.TempDir data dir).
func copyFixture(t *testing.T, src, dst string) {
	t.Helper()
	data, err := os.ReadFile(src) //nolint:gosec // src is a test fixture path
	if err != nil {
		t.Fatalf("read fixture %s: %v", src, err)
	}
	if err := os.WriteFile(dst, data, 0o600); err != nil {
		t.Fatalf("write %s: %v", dst, err)
	}
}

// copyFixtureAt copies a fixture and then stamps an explicit modification time
// on it. The "latest" resolvers order gate and verdict files by mtime, so a
// test of that rule has to control mtime rather than infer it from write order:
// two os.WriteFile calls in a row can land in the same filesystem timestamp
// tick, and then the tie-break (lexically greater name) decides instead. That
// is not hypothetical — it is how these tests failed on CI while passing on
// macOS, with "v94" beating "bt_v132a_crisis" and "v246_wf" beating "v232".
func copyFixtureAt(t *testing.T, src, dst string, mod time.Time) {
	t.Helper()
	copyFixture(t, src, dst)
	if err := os.Chtimes(dst, mod, mod); err != nil {
		t.Fatalf("chtimes %s: %v", dst, err)
	}
}

func getJSON(t *testing.T, url string, out any) *http.Response {
	t.Helper()
	resp, err := http.Get(url) //nolint:noctx,gosec // httptest server URL
	if err != nil {
		t.Fatalf("GET %s: %v", url, err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if out != nil {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
			t.Fatalf("decode %s: %v", url, err)
		}
	}
	return resp
}

// ── /api/v1/training/progress ─────────────────────────────────────────────────

// TestProgress_RealArrayFile is the regression test for the 500: the exact
// current bytes of data/training_progress.json (an ARRAY of per-cycle
// checkpoints written by scripts/run_training.py) must serve 200.
func TestProgress_RealArrayFile(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "training_progress.json"),
		filepath.Join(dir, "training_progress.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		CurrentCycle  int    `json:"current_cycle"`
		Status        string `json:"status"`
		StartedAt     string `json:"started_at"`
		CurrentRegime struct {
			Name string `json:"name"`
		} `json:"current_regime"`
		PnLHistory []struct {
			Cycle int     `json:"cycle"`
			PnL   float64 `json:"pnl"`
		} `json:"pnl_history"`
		WinRateHistory []struct {
			Cycle int `json:"cycle"`
		} `json:"win_rate_history"`
		Snapshots []any `json:"snapshots"`
		Cycles    []struct {
			Cycle        int     `json:"cycle"`
			AvgCycleTime float64 `json:"avg_cycle_time_s"`
			SitOutReason string  `json:"sit_out_reason"`
		} `json:"cycles"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/progress", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if len(body.Cycles) != 10 {
		t.Errorf("cycles = %d, want 10 (fixture length)", len(body.Cycles))
	}
	if body.CurrentCycle != 45 {
		t.Errorf("current_cycle = %d, want 45 (last checkpoint)", body.CurrentCycle)
	}
	if len(body.PnLHistory) != len(body.Cycles) || len(body.WinRateHistory) != len(body.Cycles) {
		t.Errorf("series length mismatch: pnl=%d winrate=%d cycles=%d",
			len(body.PnLHistory), len(body.WinRateHistory), len(body.Cycles))
	}
	if body.PnLHistory[0].Cycle != 1 {
		t.Errorf("pnl_history[0].cycle = %d, want 1", body.PnLHistory[0].Cycle)
	}
	if body.CurrentRegime.Name != "unknown" {
		t.Errorf("current_regime.name = %q, want %q", body.CurrentRegime.Name, "unknown")
	}
	if body.StartedAt == "" {
		t.Error("started_at empty, want first checkpoint timestamp")
	}
	// Fixture is written fresh by the test → within the running window.
	if body.Status != "running" {
		t.Errorf("status = %q, want running for a freshly-written file", body.Status)
	}
	if body.Snapshots == nil {
		t.Error("snapshots should be [] not null")
	}
	if len(body.Cycles) > 0 && body.Cycles[0].SitOutReason == "" {
		t.Error("raw checkpoint fields should be preserved in cycles[]")
	}
}

// TestProgress_LegacyObjectFile covers the object shape the handler originally
// expected (and which handleSnapshot used to persist).
func TestProgress_LegacyObjectFile(t *testing.T) {
	dir := t.TempDir()
	legacy := `{
	  "run_id": "run-legacy",
	  "total_cycles": 200,
	  "current_cycle": 37,
	  "started_at": "2026-03-28T09:15:11Z",
	  "status": "running",
	  "pnl_history": [{"cycle": 1, "pnl": 0}, {"cycle": 37, "pnl": 12.5}],
	  "win_rate_history": [{"cycle": 37, "win_rate": 0.42}],
	  "current_regime": {"name": "normal", "confidence": 0.8},
	  "snapshots": []
	}`
	if err := os.WriteFile(filepath.Join(dir, "training_progress.json"), []byte(legacy), 0o600); err != nil {
		t.Fatal(err)
	}

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		RunID        string `json:"run_id"`
		TotalCycles  int    `json:"total_cycles"`
		CurrentCycle int    `json:"current_cycle"`
		Status       string `json:"status"`
		Cycles       []any  `json:"cycles"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/progress", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.RunID != "run-legacy" || body.TotalCycles != 200 || body.CurrentCycle != 37 {
		t.Errorf("legacy fields lost: %+v", body)
	}
	if body.Status != "running" {
		t.Errorf("status = %q, want running (explicit in file)", body.Status)
	}
	if body.Cycles != nil {
		t.Errorf("cycles should be omitted for object-shaped files, got %v", body.Cycles)
	}
}

func TestProgress_MissingFile(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), "")
	defer cleanup()

	var body struct {
		Status    string `json:"status"`
		Snapshots []any  `json:"snapshots"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/progress", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.Status != "idle" {
		t.Errorf("status = %q, want idle", body.Status)
	}
	if body.Snapshots == nil {
		t.Error("snapshots should be []")
	}
}

func TestProgress_MalformedFile(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "training_progress.json"), []byte("{not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	resp := getJSON(t, srv.URL+"/api/v1/training/progress", nil)
	if resp.StatusCode != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500 for unparseable file", resp.StatusCode)
	}
}

// TestSnapshot_DoesNotClobberRunFile guards the run-owned progress file: the
// snapshot POST must write its sidecar, never rewrite run_training.py's array.
func TestSnapshot_DoesNotClobberRunFile(t *testing.T) {
	dir := t.TempDir()
	progressPath := filepath.Join(dir, "training_progress.json")
	copyFixture(t, filepath.Join(fixtureDataDir, "training_progress.json"), progressPath)
	before, err := os.ReadFile(progressPath) //nolint:gosec // t.TempDir path
	if err != nil {
		t.Fatal(err)
	}

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	resp, err := http.Post(srv.URL+"/api/v1/training/snapshot", "application/json", nil) //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("snapshot status = %d, want 200", resp.StatusCode)
	}

	after, err := os.ReadFile(progressPath) //nolint:gosec // t.TempDir path
	if err != nil {
		t.Fatal(err)
	}
	if string(before) != string(after) {
		t.Error("training_progress.json was rewritten by the snapshot endpoint")
	}

	var snaps []struct {
		ID    string `json:"id"`
		Cycle int    `json:"cycle"`
	}
	getJSON(t, srv.URL+"/api/v1/training/snapshots", &snaps)
	if len(snaps) != 1 || snaps[0].Cycle != 45 {
		t.Errorf("snapshots = %+v, want one snapshot at cycle 45", snaps)
	}
}

// ── /api/v1/training/gates ────────────────────────────────────────────────────

func TestGates_HappyPath(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v94_gate_result.json"),
		filepath.Join(dir, "v94_gate_result.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		Version        string          `json:"version"`
		Passed         bool            `json:"passed"`
		Gates          map[string]bool `json:"gates"`
		Failures       []string        `json:"failures"`
		Baseline       json.RawMessage `json:"baseline_summary"`
		Candidate      json.RawMessage `json:"candidate_summary"`
		Raw            json.RawMessage `json:"raw"`
		ResolvedLatest bool            `json:"resolved_latest"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/gates?version=v94", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.Version != "v94" {
		t.Errorf("version = %q", body.Version)
	}
	for _, g := range []string{"pnl_floor", "regime_parity", "drawdown_ceiling",
		"trade_count_floor", "signal_integrity", "auto_apply_audit"} {
		if _, ok := body.Gates[g]; !ok {
			t.Errorf("gates missing %q", g)
		}
	}
	if body.Failures == nil {
		t.Error("failures should be [] not null")
	}
	if len(body.Baseline) == 0 || len(body.Candidate) == 0 {
		t.Error("baseline_summary/candidate_summary should be populated from v48_summary/v49_summary")
	}
	// Raw passthrough must retain the gate module's literal key names.
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(body.Raw, &raw); err != nil {
		t.Fatalf("raw not an object: %v", err)
	}
	if _, ok := raw["v48_summary"]; !ok {
		t.Error("raw passthrough lost the literal v48_summary key")
	}
	if body.ResolvedLatest {
		t.Error("resolved_latest should be false when version is explicit")
	}
}

// TestGates_StandingShape covers the shape omega/eval/standing_gates.py writes
// from 2026-08-18: "gates" is an object per gate rather than a bool, and the
// file carries a top-level verdict. The pre-existing map[string]bool decode
// would have failed outright on this, returning a 500 for every new run.
func TestGates_StandingShape(t *testing.T) {
	dir := t.TempDir()
	const standing = `{
  "version": "v272_crisis_r1",
  "family": "crisis",
  "verdict": "FAIL",
  "passed": false,
  "gates": {
    "cell_pnl_floor": {"status": "fail", "family": "crisis", "candidate_pnl_usd": -186.45, "floor_usd": 0.0, "margin_usd": -186.45, "campaign_mean_usd": 599.0},
    "trade_count_floor": {"status": "pass", "trades": 24, "floor": 20},
    "drawdown_ceiling": {"status": "not_evaluated", "reason": "observability.max_drawdown_usd absent"}
  },
  "failures": ["cell_pnl_floor[crisis]: candidate -186.45 < per-cell floor +0.00 (margin -186.45)"],
  "notes": ["candidate trade fingerprint (timestamp column dropped): e6289844ea6023a5"],
  "standing_baseline_used": {"family": "crisis", "family_source": "snapshot_pattern", "per_cell_floor_usd": 0.0, "campaign_mean_usd": 599.0},
  "candidate_summary": {"version": "v272_crisis_r1", "pnl": -186.45, "trades": 24, "win_rate": 0.4167, "max_drawdown": null},
  "sibling_comparison": {"status": "informational", "sibling_label": "v271_crisis_r1", "delta_pnl_usd": 0.0}
}`
	if err := os.WriteFile(filepath.Join(dir, "v272_crisis_r1_gate_result.json"), []byte(standing), 0o600); err != nil {
		t.Fatal(err)
	}

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		Version     string                     `json:"version"`
		Passed      bool                       `json:"passed"`
		Verdict     string                     `json:"verdict"`
		Family      string                     `json:"family"`
		Gates       map[string]bool            `json:"gates"`
		GateDetails map[string]json.RawMessage `json:"gate_details"`
		Failures    []string                   `json:"failures"`
		Notes       []string                   `json:"notes"`
		Standing    json.RawMessage            `json:"standing_baseline_used"`
		Sibling     json.RawMessage            `json:"sibling_comparison"`
		Baseline    json.RawMessage            `json:"baseline_summary"`
		Candidate   struct {
			Version string  `json:"version"`
			PnL     float64 `json:"pnl"`
		} `json:"candidate_summary"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/gates?version=v272_crisis_r1", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.Verdict != "FAIL" || body.Family != "crisis" || body.Passed {
		t.Errorf("verdict/family/passed = %q/%q/%v", body.Verdict, body.Family, body.Passed)
	}
	// The lossy bool projection: pass -> true, fail -> false, not_evaluated
	// OMITTED (guessing a bool for it would be the exact lie this replaces).
	if v, ok := body.Gates["cell_pnl_floor"]; !ok || v {
		t.Errorf("gates[cell_pnl_floor] = %v, %v; want false, true", v, ok)
	}
	if v, ok := body.Gates["trade_count_floor"]; !ok || !v {
		t.Errorf("gates[trade_count_floor] = %v, %v; want true, true", v, ok)
	}
	if _, ok := body.Gates["drawdown_ceiling"]; ok {
		t.Error("a not_evaluated gate must not appear in the bool map")
	}
	// The unlossy projection keeps all three, with their numbers.
	for _, g := range []string{"cell_pnl_floor", "trade_count_floor", "drawdown_ceiling"} {
		if _, ok := body.GateDetails[g]; !ok {
			t.Errorf("gate_details missing %q", g)
		}
	}
	if len(body.Baseline) != 0 {
		t.Error("a standing-gate file has no baseline run; baseline_summary should be omitted")
	}
	if body.Candidate.Version != "v272_crisis_r1" || body.Candidate.PnL != -186.45 {
		t.Errorf("candidate_summary = %+v", body.Candidate)
	}
	if len(body.Notes) != 1 || len(body.Standing) == 0 || len(body.Sibling) == 0 {
		t.Errorf("notes/standing_baseline_used/sibling_comparison not passed through: %+v", body)
	}
}

// TestGates_StandingAdvisory covers the 2026-08-19 revision: the per-cell bar is
// per_cell_floor_usd ($0), and a cell above it but below its family's
// campaign_mean_usd PASSES carrying advisory="below_campaign_mean".
//
// What this pins on the handler is that the advisory survives. Per-gate objects
// are held as json.RawMessage and re-emitted verbatim, so a field the handler
// has never heard of reaches the board intact — but the bool projection is
// decoded, and it must read this gate as a PASS. A file whose gate says "pass"
// while the board tints it red would be exactly the cry-wolf alarm the revision
// removes.
func TestGates_StandingAdvisory(t *testing.T) {
	dir := t.TempDir()
	const standing = `{
  "version": "v273_crisis_r1",
  "family": "crisis",
  "verdict": "PASS",
  "passed": true,
  "gates": {
    "cell_pnl_floor": {"status": "pass", "family": "crisis", "candidate_pnl_usd": 412.55, "floor_usd": 0.0, "margin_usd": 412.55, "campaign_mean_usd": 599.0, "campaign_mean_margin_usd": -186.45, "advisory": "below_campaign_mean"},
    "trade_count_floor": {"status": "pass", "trades": 24, "floor": 20}
  },
  "failures": [],
  "notes": ["ADVISORY below_campaign_mean[crisis]: candidate +412.55 clears the per-cell floor +0.00"],
  "standing_baseline_used": {"family": "crisis", "per_cell_floor_usd": 0.0, "campaign_mean_usd": 599.0},
  "candidate_summary": {"version": "v273_crisis_r1", "pnl": 412.55, "trades": 24}
}`
	if err := os.WriteFile(filepath.Join(dir, "v273_crisis_r1_gate_result.json"), []byte(standing), 0o600); err != nil {
		t.Fatal(err)
	}

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		Verdict     string                     `json:"verdict"`
		Passed      bool                       `json:"passed"`
		Gates       map[string]bool            `json:"gates"`
		GateDetails map[string]json.RawMessage `json:"gate_details"`
		Failures    []string                   `json:"failures"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/gates?version=v273_crisis_r1", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.Verdict != "PASS" || !body.Passed {
		t.Errorf("verdict/passed = %q/%v, want PASS/true", body.Verdict, body.Passed)
	}
	if v, ok := body.Gates["cell_pnl_floor"]; !ok || !v {
		t.Errorf("gates[cell_pnl_floor] = %v, %v; want true, true — an advisory is not a failure", v, ok)
	}
	if len(body.Failures) != 0 {
		t.Errorf("failures = %v, want empty: an advisory never enters failures", body.Failures)
	}
	var detail struct {
		Status             string  `json:"status"`
		Advisory           string  `json:"advisory"`
		CampaignMeanUSD    float64 `json:"campaign_mean_usd"`
		CampaignMeanMargin float64 `json:"campaign_mean_margin_usd"`
		FloorUSD           float64 `json:"floor_usd"`
	}
	if err := json.Unmarshal(body.GateDetails["cell_pnl_floor"], &detail); err != nil {
		t.Fatalf("gate_details[cell_pnl_floor]: %v", err)
	}
	if detail.Status != "pass" || detail.Advisory != "below_campaign_mean" {
		t.Errorf("status/advisory = %q/%q", detail.Status, detail.Advisory)
	}
	if detail.FloorUSD != 0.0 || detail.CampaignMeanUSD != 599.0 || detail.CampaignMeanMargin != -186.45 {
		t.Errorf("floor/mean/margin = %v/%v/%v", detail.FloorUSD, detail.CampaignMeanUSD, detail.CampaignMeanMargin)
	}
}

// TestGates_BacktestCellVersion covers cell names like bt_v132a_crisis.
func TestGates_BacktestCellVersion(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "bt_v132a_crisis_gate_result.json"),
		filepath.Join(dir, "bt_v132a_crisis_gate_result.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		Version  string `json:"version"`
		Passed   bool   `json:"passed"`
		Failures []string
		Baseline struct {
			Version string `json:"version"`
		} `json:"baseline_summary"`
		Candidate struct {
			Version string `json:"version"`
		} `json:"candidate_summary"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/gates?version=bt_v132a_crisis", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.Passed {
		t.Error("fixture is a failing gate report; passed should be false")
	}
	// The literal v48_/v49_ keys carry the REAL cell names inside.
	if body.Baseline.Version != "bt_v131a_crisis" {
		t.Errorf("baseline_summary.version = %q, want bt_v131a_crisis", body.Baseline.Version)
	}
	if body.Candidate.Version != "bt_v132a_crisis" {
		t.Errorf("candidate_summary.version = %q, want bt_v132a_crisis", body.Candidate.Version)
	}
}

func TestGates_LatestWhenNoVersion(t *testing.T) {
	dir := t.TempDir()
	base := time.Date(2026, 8, 19, 12, 0, 0, 0, time.UTC)
	copyFixtureAt(t, filepath.Join(fixtureDataDir, "v94_gate_result.json"),
		filepath.Join(dir, "v94_gate_result.json"), base)
	copyFixtureAt(t, filepath.Join(fixtureDataDir, "bt_v132a_crisis_gate_result.json"),
		filepath.Join(dir, "bt_v132a_crisis_gate_result.json"), base.Add(time.Hour))
	// bt_v132a_crisis carries the newer mtime → "latest". It is also the
	// lexically smaller name, so a resolver that sorted by name would fail here.

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		Version        string `json:"version"`
		ResolvedLatest bool   `json:"resolved_latest"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/gates", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.Version != "bt_v132a_crisis" {
		t.Errorf("latest version = %q, want bt_v132a_crisis", body.Version)
	}
	if !body.ResolvedLatest {
		t.Error("resolved_latest should be true")
	}
}

func TestGates_NotFound(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v94_gate_result.json"),
		filepath.Join(dir, "v94_gate_result.json"))
	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	resp, err := http.Get(srv.URL + "/api/v1/training/gates?version=v999") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	msg := readBody(t, resp)
	if !strings.Contains(msg, "v999") {
		t.Errorf("404 body %q should name the missing version", msg)
	}
}

func TestGates_NoGateFilesAtAll(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), "")
	defer cleanup()

	resp, err := http.Get(srv.URL + "/api/v1/training/gates") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
}

// ── /api/v1/training/grid-ruler ───────────────────────────────────────────────
//
// Fixtures are REAL ruler output, not hand-written JSON:
//
//   - v246_wf_grid_verdict.json — omega/eval/grid_ruler.check_grid_ruler() over
//     the V246 exit-adaptivity grid committed in tests/fixtures/v247_paired_grids.json,
//     declared low-coupling. Its pooled mean-Δ (+$626.94) and pooled MDE ($875.12)
//     are V247_RULER.md §3/§4's published +$627 and $875.
//   - v232_grid_verdict.json — the ruler run against the real v232 crisis-snapshot
//     cells in the repo's data directory. Those are not walk-forward manifest
//     windows, so the honest answer is INSUFFICIENT_GRID with 0/32 coverage.
//
// The handler must not interpret either: its whole job is to find the right file
// and hand it over intact.

// gridVerdictBody is the wire shape of gridRulerResponse, as a consumer sees it.
type gridVerdictBody struct {
	RunLabel   string                     `json:"run_label"`
	Verdict    string                     `json:"verdict"`
	Passed     bool                       `json:"passed"`
	Families   map[string]json.RawMessage `json:"families"`
	Coverage   json.RawMessage            `json:"coverage"`
	Failures   []string                   `json:"failures"`
	RulerNotes []string                   `json:"ruler_notes"`
	Standing   json.RawMessage            `json:"standing_distribution_used"`
	Provenance json.RawMessage            `json:"provenance"`
	Raw        json.RawMessage            `json:"raw"`

	ResolvedLatest bool   `json:"resolved_latest"`
	ResolvedPrefix bool   `json:"resolved_prefix"`
	Requested      string `json:"requested"`
}

func TestGridRuler_HappyPath(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v246_wf_grid_verdict.json"),
		filepath.Join(dir, "v246_wf_grid_verdict.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body gridVerdictBody
	resp := getJSON(t, srv.URL+"/api/v1/training/grid-ruler?run=v246_wf", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.RunLabel != "v246_wf" {
		t.Errorf("run_label = %q, want v246_wf", body.RunLabel)
	}
	if body.Verdict != "PASS" || !body.Passed {
		t.Errorf("verdict = %q passed = %v, want PASS/true", body.Verdict, body.Passed)
	}
	if body.ResolvedLatest {
		t.Error("resolved_latest should be false when a run was named")
	}
	if body.ResolvedPrefix {
		t.Error("resolved_prefix should be false when the run has its own file")
	}
	// The four families V247_RULER.md rules on. Pooled is the one the doc calls
	// the decision-relevant instrument, so its absence would gut the card.
	for _, fam := range []string{"crisis", "recent", "trend", "pooled"} {
		if _, ok := body.Families[fam]; !ok {
			t.Errorf("families missing %q", fam)
		}
	}
	if len(body.Coverage) == 0 {
		t.Error("coverage should be passed through")
	}
	// [] not null, same rule as failures: a clean run legitimately has zero
	// conservative choices to flag, but the FIELD must always arrive so "no
	// notes" stays distinguishable from "handler dropped them".
	if body.RulerNotes == nil {
		t.Error("ruler_notes should be passed through as [] — every conservative choice lives there when present")
	}
	if len(body.Standing) == 0 {
		t.Error("standing_distribution_used should be passed through")
	}
	if body.Failures == nil {
		t.Error("failures should be [] not null")
	}
}

// The pooled ruling must survive the handler with its arithmetic intact: this is
// the number the card draws its bar from, and V247_RULER.md §4 fixes both values.
func TestGridRuler_PooledRulingSurvivesUntouched(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v246_wf_grid_verdict.json"),
		filepath.Join(dir, "v246_wf_grid_verdict.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body gridVerdictBody
	getJSON(t, srv.URL+"/api/v1/training/grid-ruler?run=v246_wf", &body)

	var pooled struct {
		Family    string  `json:"family"`
		Status    string  `json:"status"`
		N         int     `json:"n"`
		MeanDelta float64 `json:"mean_delta_usd"`
		MDE       float64 `json:"mde_usd"`
	}
	if err := json.Unmarshal(body.Families["pooled"], &pooled); err != nil {
		t.Fatalf("unmarshal pooled ruling: %v", err)
	}
	if pooled.N != 32 {
		t.Errorf("pooled n = %d, want 32 (the manifest's window count)", pooled.N)
	}
	if pooled.Status != "pass" {
		t.Errorf("pooled status = %q, want pass", pooled.Status)
	}
	// V247_RULER.md §3: v246_exit_adapt pooled Δ mean +$627.
	if pooled.MeanDelta < 626 || pooled.MeanDelta > 628 {
		t.Errorf("pooled mean_delta_usd = %v, want ≈+627 (V247_RULER.md §3)", pooled.MeanDelta)
	}
	// V247_RULER.md §4: a V246-class low-coupling pooled MDE at n=32 is $875.
	if pooled.MDE < 874 || pooled.MDE > 876 {
		t.Errorf("pooled mde_usd = %v, want ≈875 (V247_RULER.md §4)", pooled.MDE)
	}
}

// INSUFFICIENT_GRID must reach the board as itself. It is emphatically not a
// pass, and the handler flattening it into one would defeat the whole ruler.
func TestGridRuler_InsufficientGridIsNotAPass(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v232_grid_verdict.json"),
		filepath.Join(dir, "v232_grid_verdict.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body gridVerdictBody
	resp := getJSON(t, srv.URL+"/api/v1/training/grid-ruler?run=v232", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200 — an insufficient grid is a verdict, not an error", resp.StatusCode)
	}
	if body.Verdict != "INSUFFICIENT_GRID" {
		t.Errorf("verdict = %q, want INSUFFICIENT_GRID", body.Verdict)
	}
	if body.Passed {
		t.Error("INSUFFICIENT_GRID must never arrive as passed=true")
	}

	// The missing window ids are the entire point of the loud verdict.
	var coverage struct {
		Complete  bool `json:"complete"`
		PerFamily map[string]struct {
			Expected int      `json:"expected"`
			Covered  int      `json:"covered"`
			Missing  []string `json:"missing"`
		} `json:"per_family"`
	}
	if err := json.Unmarshal(body.Coverage, &coverage); err != nil {
		t.Fatalf("unmarshal coverage: %v", err)
	}
	if coverage.Complete {
		t.Error("coverage.complete should be false")
	}
	if len(coverage.PerFamily["crisis"].Missing) != 12 {
		t.Errorf("crisis missing = %d windows, want 12",
			len(coverage.PerFamily["crisis"].Missing))
	}
}

// A CELL label finds the GRID it belongs to, and says that it did so.
func TestGridRuler_ResolvesACellLabelToItsGridByPrefix(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v246_wf_grid_verdict.json"),
		filepath.Join(dir, "v246_wf_grid_verdict.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body gridVerdictBody
	cell := "v246_wf_snap_wf_20230912_on_trend_r1"
	resp := getJSON(t, srv.URL+"/api/v1/training/grid-ruler?run="+cell, &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.RunLabel != "v246_wf" {
		t.Errorf("run_label = %q, want the grid v246_wf", body.RunLabel)
	}
	if !body.ResolvedPrefix {
		t.Error("resolved_prefix must be true — the board has to be able to say this is the grid's verdict, not the cell's")
	}
	if body.Requested != cell {
		t.Errorf("requested = %q, want the cell label %q", body.Requested, cell)
	}
	if body.ResolvedLatest {
		t.Error("resolved_latest should be false — a run was named")
	}
}

// Prefix resolution must pick the LONGEST match, never merely the first: v2 and
// v246_wf both prefix a v246_wf cell and only one of them is its grid.
func TestGridRuler_PrefixResolutionPicksTheLongestMatch(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v246_wf_grid_verdict.json"),
		filepath.Join(dir, "v246_wf_grid_verdict.json"))
	copyFixture(t, filepath.Join(fixtureDataDir, "v232_grid_verdict.json"),
		filepath.Join(dir, "v2_grid_verdict.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body gridVerdictBody
	getJSON(t, srv.URL+"/api/v1/training/grid-ruler?run=v246_wf_snap_wf_20230912", &body)
	// run_label comes from the file's own field, so assert on what was served.
	if body.Verdict != "PASS" {
		t.Errorf("verdict = %q — the shorter v2 prefix won over v246_wf", body.Verdict)
	}
	if body.RunLabel != "v246_wf" {
		t.Errorf("run_label = %q, want v246_wf", body.RunLabel)
	}
}

func TestGridRuler_ResolvesLatestWhenNoRunAsked(t *testing.T) {
	dir := t.TempDir()
	base := time.Date(2026, 8, 19, 12, 0, 0, 0, time.UTC)
	copyFixtureAt(t, filepath.Join(fixtureDataDir, "v246_wf_grid_verdict.json"),
		filepath.Join(dir, "v246_wf_grid_verdict.json"), base)
	copyFixtureAt(t, filepath.Join(fixtureDataDir, "v232_grid_verdict.json"),
		filepath.Join(dir, "v232_grid_verdict.json"), base.Add(time.Hour))
	// v232 carries the newer mtime → "latest", same rule as /gates. It is also
	// the lexically smaller name, so name-ordering would fail here too.

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body gridVerdictBody
	resp := getJSON(t, srv.URL+"/api/v1/training/grid-ruler", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.RunLabel != "v232" {
		t.Errorf("latest run_label = %q, want v232", body.RunLabel)
	}
	if !body.ResolvedLatest {
		t.Error("resolved_latest should be true")
	}
}

// A label that no grid verdict prefixes is a 404 — "the ruler never ran for
// this" — and must name what was asked for. It is not an empty pass.
func TestGridRuler_NotFound(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v246_wf_grid_verdict.json"),
		filepath.Join(dir, "v246_wf_grid_verdict.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	resp, err := http.Get(srv.URL + "/api/v1/training/grid-ruler?run=v999_wf") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	if msg := readBody(t, resp); !strings.Contains(msg, "v999_wf") {
		t.Errorf("404 body %q should name the run that was asked for", msg)
	}
}

func TestGridRuler_NoVerdictFilesAtAll(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), "")
	defer cleanup()

	resp, err := http.Get(srv.URL + "/api/v1/training/grid-ruler") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
}

// A grid verdict must never be served for a traversal-shaped label, on the same
// isSafeVersion guard the rest of the file-backed endpoints use.
func TestGridRuler_RejectsPathTraversal(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), "")
	defer cleanup()

	for _, run := range []string{"../../etc/passwd", "v246/../../secret", "v246 wf"} {
		resp, err := http.Get(srv.URL + "/api/v1/training/grid-ruler?run=" + url.QueryEscape(run)) //nolint:noctx
		if err != nil {
			t.Fatal(err)
		}
		_ = resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			t.Errorf("run=%q returned 200, want a rejection", run)
		}
	}
}

// ── /api/v1/training/forensics ────────────────────────────────────────────────

func TestForensics_HappyPath(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v93-v94-forensics.json"),
		filepath.Join(dir, "v93-v94-forensics.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		Baseline  string `json:"baseline"`
		Target    string `json:"target"`
		File      string `json:"file"`
		Forensics struct {
			SchemaVersion string `json:"schema_version"`
			Status        string `json:"status"`
			Hypotheses    []any  `json:"hypotheses"`
		} `json:"forensics"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/forensics?baseline=v93&target=v94", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.Baseline != "v93" || body.Target != "v94" || body.File != "v93-v94-forensics.json" {
		t.Errorf("envelope wrong: %+v", body)
	}
	if body.Forensics.SchemaVersion == "" || body.Forensics.Status == "" {
		t.Error("forensics payload not passed through")
	}
	if len(body.Forensics.Hypotheses) == 0 {
		t.Error("expected hypotheses in the forensics payload")
	}
}

func TestForensics_List(t *testing.T) {
	dir := t.TempDir()
	copyFixture(t, filepath.Join(fixtureDataDir, "v93-v94-forensics.json"),
		filepath.Join(dir, "v93-v94-forensics.json"))
	copyFixture(t, filepath.Join(fixtureDataDir, "v93-v94-forensics.json"),
		filepath.Join(dir, "v48-v50-forensics.json"))
	// Real repo also holds non-paired names like v240_universe_forensics.json.
	copyFixture(t, filepath.Join(fixtureDataDir, "v93-v94-forensics.json"),
		filepath.Join(dir, "v240_universe_forensics.json"))

	srv, cleanup := newTrainingServer(t, dir, "")
	defer cleanup()

	var body struct {
		Forensics []struct {
			Baseline  string `json:"baseline"`
			Target    string `json:"target"`
			File      string `json:"file"`
			SizeBytes int64  `json:"size_bytes"`
		} `json:"forensics"`
		Unpaired []string `json:"unpaired"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/forensics", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if len(body.Forensics) != 2 {
		t.Fatalf("forensics = %+v, want 2 paired reports", body.Forensics)
	}
	seen := map[string]string{}
	for _, f := range body.Forensics {
		seen[f.Baseline] = f.Target
		if f.SizeBytes == 0 {
			t.Errorf("%s missing size_bytes", f.File)
		}
	}
	if seen["v93"] != "v94" || seen["v48"] != "v50" {
		t.Errorf("pair parsing wrong: %v", seen)
	}
	if len(body.Unpaired) != 1 || body.Unpaired[0] != "v240_universe_forensics.json" {
		t.Errorf("unpaired = %v", body.Unpaired)
	}
}

func TestForensics_NotFound(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), "")
	defer cleanup()

	resp, err := http.Get(srv.URL + "/api/v1/training/forensics?baseline=v1&target=v2") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	if msg := readBody(t, resp); !strings.Contains(msg, "v1") || !strings.Contains(msg, "v2") {
		t.Errorf("404 body %q should name both versions", msg)
	}
}

func TestForensics_PartialParams(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), "")
	defer cleanup()

	resp, err := http.Get(srv.URL + "/api/v1/training/forensics?baseline=v93") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", resp.StatusCode)
	}
}

// ── /api/v1/training/log ──────────────────────────────────────────────────────

func TestTrainingLog_PreRegistrationAndVerdict(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), fixtureLogDir)
	defer cleanup()

	var body struct {
		Version         string   `json:"version"`
		PreRegistration string   `json:"preRegistration"`
		Verdict         string   `json:"verdict"`
		Files           []string `json:"files"`
		VerdictFiles    []string `json:"verdictFiles"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/log?version=V261", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if !strings.Contains(body.PreRegistration, "#") {
		t.Errorf("preRegistration should be raw markdown, got %q", body.PreRegistration)
	}
	if body.Verdict == "" {
		t.Error("expected V261_VERDICT.md content")
	}
	if len(body.Files) != 2 {
		t.Errorf("files = %v, want pre-registration + verdict", body.Files)
	}
	if len(body.VerdictFiles) != 1 || body.VerdictFiles[0] != "V261_VERDICT.md" {
		t.Errorf("verdictFiles = %v", body.VerdictFiles)
	}
}

// TestTrainingLog_CaseInsensitive: the real tree mixes cases (V206b.md), so a
// lowercase cell id must still resolve.
func TestTrainingLog_CaseInsensitive(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), fixtureLogDir)
	defer cleanup()

	for _, v := range []string{"v206b", "V206b", "V206B"} {
		var body struct {
			PreRegistration string `json:"preRegistration"`
		}
		resp := getJSON(t, srv.URL+"/api/v1/training/log?version="+v, &body)
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("version=%s status = %d, want 200", v, resp.StatusCode)
		}
		if body.PreRegistration == "" {
			t.Errorf("version=%s returned empty pre-registration", v)
		}
	}
}

// TestTrainingLog_VerdictOnlySuffix: V262's verdict is V262_AUDIT_VERDICT.md,
// not V262_VERDICT.md.
func TestTrainingLog_SuffixedVerdict(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), fixtureLogDir)
	defer cleanup()

	var body struct {
		Verdict      string   `json:"verdict"`
		VerdictFiles []string `json:"verdictFiles"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/log?version=V262", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if len(body.VerdictFiles) != 1 || body.VerdictFiles[0] != "V262_AUDIT_VERDICT.md" {
		t.Errorf("verdictFiles = %v, want [V262_AUDIT_VERDICT.md]", body.VerdictFiles)
	}
	if !strings.Contains(body.Verdict, "VERDICT") {
		t.Errorf("verdict content unexpected: %q", body.Verdict)
	}
}

// TestTrainingLog_PreRegistrationOnly: V148 has no verdict.
func TestTrainingLog_PreRegistrationOnly(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), fixtureLogDir)
	defer cleanup()

	var body struct {
		PreRegistration string   `json:"preRegistration"`
		Verdict         string   `json:"verdict"`
		VerdictFiles    []string `json:"verdictFiles"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/log?version=V148", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if body.PreRegistration == "" {
		t.Error("expected V148 pre-registration content")
	}
	if body.Verdict != "" || len(body.VerdictFiles) != 0 {
		t.Errorf("V148 has no verdict, got %q / %v", body.Verdict, body.VerdictFiles)
	}
}

func TestTrainingLog_NotFound(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), fixtureLogDir)
	defer cleanup()

	resp, err := http.Get(srv.URL + "/api/v1/training/log?version=V9999") //nolint:noctx
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	if msg := readBody(t, resp); !strings.Contains(msg, "V9999") {
		t.Errorf("404 body %q should name the version", msg)
	}
}

func TestTrainingLog_List(t *testing.T) {
	srv, cleanup := newTrainingServer(t, t.TempDir(), fixtureLogDir)
	defer cleanup()

	var body struct {
		Entries []struct {
			Version            string   `json:"version"`
			HasPreRegistration bool     `json:"hasPreRegistration"`
			VerdictFiles       []string `json:"verdictFiles"`
		} `json:"entries"`
	}
	resp := getJSON(t, srv.URL+"/api/v1/training/log", &body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	byVersion := map[string][]string{}
	pre := map[string]bool{}
	for _, e := range body.Entries {
		byVersion[e.Version] = e.VerdictFiles
		pre[e.Version] = e.HasPreRegistration
	}
	for _, want := range []string{"V148", "V206b", "V261", "V262"} {
		if !pre[want] {
			t.Errorf("entry %s missing / not marked as having a pre-registration", want)
		}
	}
	if len(byVersion["V261"]) != 1 || byVersion["V261"][0] != "V261_VERDICT.md" {
		t.Errorf("V261 verdicts = %v", byVersion["V261"])
	}
	if len(byVersion["V262"]) != 1 || byVersion["V262"][0] != "V262_AUDIT_VERDICT.md" {
		t.Errorf("V262 verdicts = %v", byVersion["V262"])
	}
	if len(byVersion["V148"]) != 0 {
		t.Errorf("V148 should have no verdicts, got %v", byVersion["V148"])
	}
}

// ── Path traversal ────────────────────────────────────────────────────────────

func TestVersionParamTraversalRejected(t *testing.T) {
	// A file the traversal must never reach.
	outside := t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "secret_gate_result.json"), []byte(`{"passed":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	dataDir := filepath.Join(outside, "data")
	if err := os.Mkdir(dataDir, 0o750); err != nil {
		t.Fatal(err)
	}

	srv, cleanup := newTrainingServer(t, dataDir, fixtureLogDir)
	defer cleanup()

	bad := []string{
		"../../etc/passwd",
		"v1/../x",
		"../secret",
		"..",
		"./v94",
		"v94%00",
		"v94.json",
		`\..\..\v94`,
	}
	paths := []string{"/api/v1/training/gates?version=", "/api/v1/training/log?version="}
	for _, p := range paths {
		for _, v := range bad {
			url := srv.URL + p + url.QueryEscape(v)
			resp, err := http.Get(url) //nolint:noctx,gosec // httptest server URL
			if err != nil {
				t.Fatalf("GET %s: %v", url, err)
			}
			body := readBody(t, resp)
			resp.Body.Close() //nolint:errcheck,gosec
			if resp.StatusCode != http.StatusBadRequest {
				t.Errorf("%s%q → status %d, want 400 (body %q)", p, v, resp.StatusCode, body)
			}
			if strings.Contains(body, "root:") || strings.Contains(body, "passed") {
				t.Errorf("%s%q leaked file content: %q", p, v, body)
			}
		}
	}

	// Forensics interpolates two params — both must be validated.
	for _, q := range []string{
		"baseline=../../etc/passwd&target=v94",
		"baseline=v93&target=../secret",
	} {
		resp, err := http.Get(srv.URL + "/api/v1/training/forensics?" + q) //nolint:noctx
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close() //nolint:errcheck,gosec
		if resp.StatusCode != http.StatusBadRequest {
			t.Errorf("forensics?%s → status %d, want 400", q, resp.StatusCode)
		}
	}
}

// ── helpers ───────────────────────────────────────────────────────────────────

func readBody(t *testing.T, resp *http.Response) string {
	t.Helper()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	return string(data)
}
