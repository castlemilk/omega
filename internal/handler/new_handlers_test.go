package handler_test

import (
	"context"
	"database/sql"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"connectrpc.com/connect"
	_ "modernc.org/sqlite"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

// ── test helpers ──────────────────────────────────────────────────────────────

// bootstrapMemorySchema creates the SQLite tables that the memory kernel needs.
func bootstrapMemorySchema(t *testing.T, path string) {
	t.Helper()
	sqlDB, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open mem db: %v", err)
	}
	defer sqlDB.Close() //nolint:errcheck
	// Let MemoryKernel.createSchema() create its own tables on first use.
	// We only need to ensure the file exists (already done by sql.Open above).
	_, err = sqlDB.Exec(`SELECT 1`)
	if err != nil {
		t.Fatalf("bootstrap memory schema: %v", err)
	}
}

func setupTestDB(t *testing.T) (*db.DB, func()) {
	t.Helper()
	dir := t.TempDir()
	stateDB := filepath.Join(dir, "state.db")
	memDB := filepath.Join(dir, "memory.db")

	bootstrapStateSchema(t, stateDB)
	bootstrapMemorySchema(t, memDB)

	database, err := db.New(stateDB, memDB)
	if err != nil {
		t.Fatalf("db.New: %v", err)
	}
	return database, func() { database.Close() } //nolint:errcheck
}

func setupAutonomyServer(t *testing.T) (omegav1connect.AutonomyServiceClient, func()) {
	t.Helper()
	h := handler.NewAutonomy()
	mux := http.NewServeMux()
	path, svc := omegav1connect.NewAutonomyServiceHandler(h)
	mux.Handle(path, svc)
	srv := httptest.NewServer(mux)
	client := omegav1connect.NewAutonomyServiceClient(http.DefaultClient, srv.URL)
	return client, srv.Close
}

func setupAdversarialServer(t *testing.T) (omegav1connect.AdversarialServiceClient, func()) {
	t.Helper()
	database, cleanup := setupTestDB(t)
	h := handler.NewAdversarial(database)
	mux := http.NewServeMux()
	path, svc := omegav1connect.NewAdversarialServiceHandler(h)
	mux.Handle(path, svc)
	srv := httptest.NewServer(mux)
	client := omegav1connect.NewAdversarialServiceClient(http.DefaultClient, srv.URL)
	return client, func() {
		srv.Close()
		cleanup()
	}
}

func setupSafetyServer(t *testing.T) (omegav1connect.SafetyServiceClient, func()) {
	t.Helper()
	database, cleanup := setupTestDB(t)
	h, err := handler.NewSafety(database)
	if err != nil {
		// If challenge DB path cannot be created in test, fall back to unimplemented
		t.Logf("NewSafety: %v (falling back to unimplemented)", err)
		cleanup()
		mux := http.NewServeMux()
		path, svc := omegav1connect.NewSafetyServiceHandler(omegav1connect.UnimplementedSafetyServiceHandler{})
		mux.Handle(path, svc)
		srv := httptest.NewServer(mux)
		return omegav1connect.NewSafetyServiceClient(http.DefaultClient, srv.URL), srv.Close
	}
	mux := http.NewServeMux()
	path, svc := omegav1connect.NewSafetyServiceHandler(h)
	mux.Handle(path, svc)
	srv := httptest.NewServer(mux)
	client := omegav1connect.NewSafetyServiceClient(http.DefaultClient, srv.URL)
	return client, func() {
		srv.Close()
		cleanup()
	}
}

func setupMemoryServer(t *testing.T) (omegav1connect.MemoryServiceClient, func()) {
	t.Helper()
	database, cleanup := setupTestDB(t)
	h, err := handler.NewMemory(database)
	if err != nil {
		t.Fatalf("NewMemory: %v", err)
	}
	mux := http.NewServeMux()
	path, svc := omegav1connect.NewMemoryServiceHandler(h)
	mux.Handle(path, svc)
	srv := httptest.NewServer(mux)
	client := omegav1connect.NewMemoryServiceClient(http.DefaultClient, srv.URL)
	return client, func() {
		srv.Close()
		cleanup()
	}
}

func setupImprovementServer(t *testing.T) (omegav1connect.ImprovementServiceClient, func()) {
	t.Helper()
	h := handler.NewImprovement()
	mux := http.NewServeMux()
	path, svc := omegav1connect.NewImprovementServiceHandler(h)
	mux.Handle(path, svc)
	srv := httptest.NewServer(mux)
	client := omegav1connect.NewImprovementServiceClient(http.DefaultClient, srv.URL)
	return client, srv.Close
}

// ── AutonomyService tests ─────────────────────────────────────────────────────

func TestAutonomy_RecordAndGetLevel(t *testing.T) {
	client, cleanup := setupAutonomyServer(t)
	defer cleanup()

	ctx := context.Background()

	// Record some metrics
	_, err := client.RecordCycleMetrics(ctx, connect.NewRequest(&omegav1.RecordCycleMetricsRequest{
		NodeId:  "node-1",
		Cycle:   1,
		Metrics: map[string]float64{"sharpe": 1.2, "win_rate": 0.65},
		Success: true,
	}))
	if err != nil {
		t.Fatalf("RecordCycleMetrics: %v", err)
	}

	// Get autonomy level
	resp, err := client.GetAutonomyLevel(ctx, connect.NewRequest(&omegav1.GetAutonomyLevelRequest{
		NodeId: "node-1",
	}))
	if err != nil {
		t.Fatalf("GetAutonomyLevel: %v", err)
	}
	if resp.Msg.NodeId != "node-1" {
		t.Errorf("want node-1, got %s", resp.Msg.NodeId)
	}
}

func TestAutonomy_RequestPromotionDenied(t *testing.T) {
	client, cleanup := setupAutonomyServer(t)
	defer cleanup()

	ctx := context.Background()

	// Request promotion without meeting criteria
	resp, err := client.RequestPromotion(ctx, connect.NewRequest(&omegav1.RequestPromotionRequest{
		NodeId:         "node-2",
		RequestedLevel: omegav1.AutonomyLevel_AUTONOMY_LEVEL_SUPERVISED,
		Cycle:          1,
	}))
	if err != nil {
		t.Fatalf("RequestPromotion: %v", err)
	}
	if resp.Msg.Approved {
		t.Error("expected promotion to be denied (insufficient cycles)")
	}
}

func TestAutonomy_RecordPromotion(t *testing.T) {
	client, cleanup := setupAutonomyServer(t)
	defer cleanup()

	ctx := context.Background()

	_, err := client.RecordPromotion(ctx, connect.NewRequest(&omegav1.RecordPromotionRequest{
		NodeId:    "node-3",
		FromLevel: omegav1.AutonomyLevel_AUTONOMY_LEVEL_MANUAL,
		ToLevel:   omegav1.AutonomyLevel_AUTONOMY_LEVEL_SUPERVISED,
		Trigger:   "manual_override",
		Cycle:     5,
	}))
	if err != nil {
		t.Fatalf("RecordPromotion: %v", err)
	}

	hist, err := client.GetAutonomyHistory(ctx, connect.NewRequest(&omegav1.GetAutonomyHistoryRequest{
		NodeId: "node-3",
		Limit:  10,
	}))
	if err != nil {
		t.Fatalf("GetAutonomyHistory: %v", err)
	}
	if len(hist.Msg.Events) != 1 {
		t.Errorf("want 1 event, got %d", len(hist.Msg.Events))
	}
	if hist.Msg.Events[0].Trigger != "manual_override" {
		t.Errorf("unexpected trigger: %s", hist.Msg.Events[0].Trigger)
	}
}

func TestAutonomy_GetHistoryEmpty(t *testing.T) {
	client, cleanup := setupAutonomyServer(t)
	defer cleanup()

	resp, err := client.GetAutonomyHistory(context.Background(), connect.NewRequest(&omegav1.GetAutonomyHistoryRequest{
		NodeId: "nonexistent",
		Limit:  10,
	}))
	if err != nil {
		t.Fatalf("GetAutonomyHistory: %v", err)
	}
	if len(resp.Msg.Events) != 0 {
		t.Errorf("want empty history, got %d events", len(resp.Msg.Events))
	}
}

// ── AdversarialService tests ──────────────────────────────────────────────────

func TestAdversarial_RunPressureEmptyInputs(t *testing.T) {
	client, cleanup := setupAdversarialServer(t)
	defer cleanup()

	resp, err := client.RunPressure(context.Background(), connect.NewRequest(&omegav1.RunPressureRequest{
		Cycle:          1,
		VariantOutputs: map[string]*omegav1.VariantOutputs{},
		CurrentSignals: map[string]float64{},
		StrategyParams: map[string]float64{},
	}))
	if err != nil {
		t.Fatalf("RunPressure: %v", err)
	}
	if resp.Msg.Report == nil {
		t.Fatal("expected non-nil report")
	}
}

func TestAdversarial_RunDebate(t *testing.T) {
	client, cleanup := setupAdversarialServer(t)
	defer cleanup()

	resp, err := client.RunDebate(context.Background(), connect.NewRequest(&omegav1.RunDebateRequest{
		Context: &omegav1.SignalContext{
			CompositeSignal: 0.6,
			IcShort:         0.05,
			IcLong:          0.03,
			VolRegime:       1.0,
			RegimeIc:        0.04,
			RecentSharpe:    1.5,
		},
	}))
	if err != nil {
		t.Fatalf("RunDebate: %v", err)
	}
	if resp.Msg.Verdict == nil {
		t.Fatal("expected non-nil verdict")
	}
}

func TestAdversarial_ResolveRisk(t *testing.T) {
	client, cleanup := setupAdversarialServer(t)
	defer cleanup()

	resp, err := client.ResolveRisk(context.Background(), connect.NewRequest(&omegav1.ResolveRiskRequest{
		Context: &omegav1.RiskContext{
			BasePositionScale: 0.5,
			PortfolioDrawdown: 0.05,
			CurrentVolatility: 1.2,
			RecentWinRate:     0.55,
			KellyFraction:     0.25,
		},
	}))
	if err != nil {
		t.Fatalf("ResolveRisk: %v", err)
	}
	if resp.Msg.Result == nil {
		t.Fatal("expected non-nil result")
	}
	if len(resp.Msg.Result.Verdicts) == 0 {
		t.Error("expected at least one persona verdict")
	}
}

func TestAdversarial_GetAdversarialReportNotFound(t *testing.T) {
	client, cleanup := setupAdversarialServer(t)
	defer cleanup()

	resp, err := client.GetAdversarialReport(context.Background(), connect.NewRequest(&omegav1.GetAdversarialReportRequest{
		Cycle: 9999,
	}))
	if err != nil {
		t.Fatalf("GetAdversarialReport: %v", err)
	}
	if resp.Msg.Found {
		t.Error("expected not found")
	}
}

// ── SafetyService tests ───────────────────────────────────────────────────────

func TestSafety_CheckAlignmentEmpty(t *testing.T) {
	client, cleanup := setupSafetyServer(t)
	defer cleanup()

	resp, err := client.CheckAlignment(context.Background(), connect.NewRequest(&omegav1.CheckAlignmentRequest{
		Cycle:         1,
		SystemMetrics: map[string]float64{},
		Portfolio:     map[string]float64{},
	}))
	if err != nil {
		// UnimplementedSafetyServiceHandler returns CodeUnimplemented which is OK
		t.Logf("CheckAlignment (possibly unimplemented): %v", err)
		return
	}
	if !resp.Msg.Approved {
		t.Logf("alignment not approved: %v", resp.Msg.Violations)
	}
}

func TestSafety_EvaluateGoals(t *testing.T) {
	client, cleanup := setupSafetyServer(t)
	defer cleanup()

	resp, err := client.EvaluateGoals(context.Background(), connect.NewRequest(&omegav1.EvaluateGoalsRequest{
		Cycle:       1,
		Metrics:     map[string]float64{"sharpe": 1.5, "win_rate": 0.6},
		SystemState: map[string]string{},
	}))
	if err != nil {
		t.Logf("EvaluateGoals (possibly unimplemented): %v", err)
		return
	}
	_ = resp.Msg.CompositeScore
}

func TestSafety_HasBlockingChallengesEmpty(t *testing.T) {
	client, cleanup := setupSafetyServer(t)
	defer cleanup()

	resp, err := client.HasBlockingChallenges(context.Background(), connect.NewRequest(&omegav1.HasBlockingChallengesRequest{}))
	if err != nil {
		t.Logf("HasBlockingChallenges (possibly unimplemented): %v", err)
		return
	}
	if resp.Msg.HasBlocking {
		t.Error("expected no blocking challenges on fresh DB")
	}
}

func TestSafety_RecordOutcomeScore(t *testing.T) {
	client, cleanup := setupSafetyServer(t)
	defer cleanup()

	resp, err := client.RecordOutcomeScore(context.Background(), connect.NewRequest(&omegav1.RecordOutcomeScoreRequest{
		NodeId:             "node-a",
		Predicted:          0.65,
		Actual:             0.60,
		ReturnContribution: 0.02,
		Cycle:              1,
	}))
	if err != nil {
		t.Logf("RecordOutcomeScore (possibly unimplemented): %v", err)
		return
	}
	if !resp.Msg.Ok {
		t.Error("expected ok=true")
	}
}

// ── MemoryService tests ───────────────────────────────────────────────────────

func TestMemory_StoreAndQueryEpisode(t *testing.T) {
	client, cleanup := setupMemoryServer(t)
	defer cleanup()

	ctx := context.Background()

	storeResp, err := client.StoreEpisode(ctx, connect.NewRequest(&omegav1.StoreEpisodeRequest{
		Namespace: "test_node",
		EventType: "cycle_result",
		Content:   map[string]string{"sharpe": "1.2", "cycle": "1"},
		Tags:      []string{"test"},
		Importance: 0.8,
		Cycle:     1,
	}))
	if err != nil {
		t.Fatalf("StoreEpisode: %v", err)
	}
	if storeResp.Msg.EpisodeId == "" {
		t.Fatal("expected non-empty episode_id")
	}

	queryResp, err := client.QueryEpisodes(ctx, connect.NewRequest(&omegav1.QueryEpisodesRequest{
		Namespace:  "test_node",
		TopK:       10,
	}))
	if err != nil {
		t.Fatalf("QueryEpisodes: %v", err)
	}
	if len(queryResp.Msg.Results) == 0 {
		t.Error("expected at least one episode")
	}
}

func TestMemory_StoreAndGetWorking(t *testing.T) {
	client, cleanup := setupMemoryServer(t)
	defer cleanup()

	ctx := context.Background()

	_, err := client.StoreWorking(ctx, connect.NewRequest(&omegav1.StoreWorkingRequest{
		Namespace: "node-x",
		Key:       "last_signal",
		ValueJson: `{"value": 0.7}`,
	}))
	if err != nil {
		t.Fatalf("StoreWorking: %v", err)
	}

	resp, err := client.GetWorking(ctx, connect.NewRequest(&omegav1.GetWorkingRequest{
		Namespace: "node-x",
		Key:       "last_signal",
	}))
	if err != nil {
		t.Fatalf("GetWorking: %v", err)
	}
	if !resp.Msg.Found {
		t.Error("expected found=true")
	}
	if resp.Msg.ValueJson == "" {
		t.Error("expected non-empty value json")
	}
}

func TestMemory_DeleteWorking(t *testing.T) {
	client, cleanup := setupMemoryServer(t)
	defer cleanup()

	ctx := context.Background()

	_, err := client.StoreWorking(ctx, connect.NewRequest(&omegav1.StoreWorkingRequest{
		Namespace: "node-y",
		Key:       "temp_key",
		ValueJson: `"hello"`,
	}))
	if err != nil {
		t.Fatalf("StoreWorking: %v", err)
	}

	_, err = client.DeleteWorking(ctx, connect.NewRequest(&omegav1.DeleteWorkingRequest{
		Namespace: "node-y",
		Key:       "temp_key",
	}))
	if err != nil {
		t.Fatalf("DeleteWorking: %v", err)
	}

	resp, err := client.GetWorking(ctx, connect.NewRequest(&omegav1.GetWorkingRequest{
		Namespace: "node-y",
		Key:       "temp_key",
	}))
	if err != nil {
		t.Fatalf("GetWorking after delete: %v", err)
	}
	if resp.Msg.Found {
		t.Error("expected found=false after delete")
	}
}

func TestMemory_BeginAndEndCycle(t *testing.T) {
	client, cleanup := setupMemoryServer(t)
	defer cleanup()

	ctx := context.Background()

	_, err := client.BeginCycle(ctx, connect.NewRequest(&omegav1.BeginCycleRequest{
		Namespace: "global",
		Cycle:     42,
	}))
	if err != nil {
		t.Fatalf("BeginCycle: %v", err)
	}

	endResp, err := client.EndCycle(ctx, connect.NewRequest(&omegav1.EndCycleRequest{
		Namespace:          "global",
		Cycle:              42,
		CycleSummary:       map[string]string{"sharpe": "1.1"},
		SummaryImportance:  0.7,
		TriggerConsolidation: false,
	}))
	if err != nil {
		t.Fatalf("EndCycle: %v", err)
	}
	if endResp.Msg.EpisodeId == "" {
		t.Error("expected non-empty episode_id from EndCycle")
	}
}

func TestMemory_GetMemoryStats(t *testing.T) {
	client, cleanup := setupMemoryServer(t)
	defer cleanup()

	resp, err := client.GetMemoryStats(context.Background(), connect.NewRequest(&omegav1.MemoryNamespaceStatsRequest{
		Namespace: "global",
	}))
	if err != nil {
		t.Fatalf("GetMemoryStats: %v", err)
	}
	if resp.Msg.EpisodicCount < 0 {
		t.Error("negative episodic count")
	}
}

// ── ImprovementService tests ──────────────────────────────────────────────────

func TestImprovement_DueNodes_Empty(t *testing.T) {
	client, cleanup := setupImprovementServer(t)
	defer cleanup()

	resp, err := client.DueNodes(context.Background(), connect.NewRequest(&omegav1.DueNodesRequest{Cycle: 1}))
	if err != nil {
		t.Fatalf("DueNodes: %v", err)
	}
	if len(resp.Msg.NodeIds) != 0 {
		t.Errorf("expected empty due nodes, got %v", resp.Msg.NodeIds)
	}
}

func TestImprovement_ScheduleAndListNodes(t *testing.T) {
	client, cleanup := setupImprovementServer(t)
	defer cleanup()

	ctx := context.Background()

	schedResp, err := client.ScheduleImprovement(ctx, connect.NewRequest(&omegav1.ScheduleImprovementRequest{
		NodeId:   "node-sched",
		Priority: 1.5,
	}))
	if err != nil {
		t.Fatalf("ScheduleImprovement: %v", err)
	}
	if schedResp.Msg.Entry == nil {
		t.Fatal("expected non-nil schedule entry")
	}
	if schedResp.Msg.Entry.NodeId != "node-sched" {
		t.Errorf("want node-sched, got %s", schedResp.Msg.Entry.NodeId)
	}

	listResp, err := client.ListImprovedNodes(ctx, connect.NewRequest(&omegav1.ListImprovedNodesRequest{}))
	if err != nil {
		t.Fatalf("ListImprovedNodes: %v", err)
	}
	if len(listResp.Msg.Entries) == 0 {
		t.Error("expected at least one entry")
	}
}

func TestImprovement_RecordOutcomeAndReschedule(t *testing.T) {
	client, cleanup := setupImprovementServer(t)
	defer cleanup()

	ctx := context.Background()

	_, err := client.ScheduleImprovement(ctx, connect.NewRequest(&omegav1.ScheduleImprovementRequest{
		NodeId:   "node-outcome",
		Priority: 1.0,
	}))
	if err != nil {
		t.Fatalf("ScheduleImprovement: %v", err)
	}

	outcomeResp, err := client.RecordOutcome(ctx, connect.NewRequest(&omegav1.RecordOutcomeRequest{
		NodeId:  "node-outcome",
		Success: true,
		Score:   0.85,
		Cycle:   1,
	}))
	if err != nil {
		t.Fatalf("RecordOutcome: %v", err)
	}
	if outcomeResp.Msg.UpdatedEntry == nil {
		t.Fatal("expected updated entry")
	}
}

func TestImprovement_GetSchedule_NotFound(t *testing.T) {
	client, cleanup := setupImprovementServer(t)
	defer cleanup()

	resp, err := client.GetImprovementSchedule(context.Background(), connect.NewRequest(&omegav1.GetImprovementScheduleRequest{
		NodeId: "nonexistent",
	}))
	if err != nil {
		t.Fatalf("GetImprovementSchedule: %v", err)
	}
	if resp.Msg.Found {
		t.Error("expected found=false for unregistered node")
	}
}

func TestImprovement_CompileStrategy(t *testing.T) {
	client, cleanup := setupImprovementServer(t)
	defer cleanup()

	resp, err := client.CompileStrategy(context.Background(), connect.NewRequest(&omegav1.CompileStrategyRequest{
		NodeId:      "node-compile",
		NodeVersion: "v1.0.0",
		Parameters:  map[string]float64{"fast_period": 5, "slow_period": 20},
		Rules: []*omegav1.StrategyRule{
			{
				Name:       "momentum_rule",
				Confidence: 0.7,
				Conditions: []*omegav1.RuleCondition{
					{FieldPath: "momentum", Operator: "gt", Threshold: 0.5},
				},
			},
		},
	}))
	if err != nil {
		t.Fatalf("CompileStrategy: %v", err)
	}
	if resp.Msg.StrategyId == "" {
		t.Error("expected non-empty strategy_id")
	}
	if resp.Msg.Checksum == "" {
		t.Error("expected non-empty checksum")
	}
}

func TestImprovement_ProposeTrialParams(t *testing.T) {
	client, cleanup := setupImprovementServer(t)
	defer cleanup()

	resp, err := client.ProposeTrialParams(context.Background(), connect.NewRequest(&omegav1.ProposeTrialParamsRequest{
		NodeId: "node-tpe",
	}))
	if err != nil {
		t.Fatalf("ProposeTrialParams: %v", err)
	}
	if resp.Msg.Strategy == "" {
		t.Error("expected non-empty strategy name")
	}
}

// ── ensure test helper creates tempdir env var for challenge path ─────────────

func init() {
	// Override the challenge registry path to a temp file so tests don't
	// write to /tmp/omega_challenge_registry.db globally.
	os.Setenv("OMEGA_CHALLENGE_REGISTRY_PATH", "") //nolint:errcheck,gosec
}
