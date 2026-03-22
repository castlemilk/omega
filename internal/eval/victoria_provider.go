package eval

import (
	"fmt"

	"github.com/benebsworth/omega/internal/db"
)

// VictoriaSnapshot captures all observable state from the Victoria/Vectora layer
// at a point in time. Fields are non-nil but zero-valued when the underlying
// table is empty or the DB is unavailable.
type VictoriaSnapshot struct {
	Portfolio    *db.VectoraPortfolio
	PnL          *db.VectoraPnL
	Signals      []*db.VectoraSignal
	BacktestStats *db.VectoraBacktestStats
	RiskMetrics  *db.VectoraRiskMetrics
	EquityCurve  []*db.VectoraEquityPoint

	// Source is "live-db" or "stub".
	Source string
	// Available is true when at least one metric row was found in the DB.
	Available bool
}

// VictoriaProvider abstracts data access so the eval harness works in both
// live (real SQLite) and test (deterministic stub) modes.
type VictoriaProvider interface {
	Snapshot() (*VictoriaSnapshot, error)
	IsLive() bool
	Source() string
}

// ── VectoraDBProvider ─────────────────────────────────────────────────────────

// VectoraDBProvider reads from the live Vectora SQLite database written by
// the Python trading engine.
type VectoraDBProvider struct {
	vdb *db.VectoraDB
}

// NewVectoraDBProvider opens the Vectora DB at the path from db.VectoraDBPath().
// Returns an error only if the file cannot be opened; an empty/unpopulated DB
// is accepted and will produce a snapshot with Available=false.
func NewVectoraDBProvider() (*VectoraDBProvider, error) {
	vdb, err := db.NewVectora(db.VectoraDBPath())
	if err != nil {
		return nil, fmt.Errorf("open vectora db: %w", err)
	}
	return &VectoraDBProvider{vdb: vdb}, nil
}

// Close releases the database connection.
func (p *VectoraDBProvider) Close() { p.vdb.Close() }

// IsLive returns true.
func (p *VectoraDBProvider) IsLive() bool { return true }

// Source returns the DB file path.
func (p *VectoraDBProvider) Source() string { return db.VectoraDBPath() }

// Snapshot queries all observable Victoria state from the database.
func (p *VectoraDBProvider) Snapshot() (*VictoriaSnapshot, error) {
	snap := &VictoriaSnapshot{Source: "live-db"}

	port, err := p.vdb.GetPortfolio()
	if err != nil {
		return snap, fmt.Errorf("GetPortfolio: %w", err)
	}
	snap.Portfolio = port
	// Available if Python has written at least one meaningful metric.
	snap.Available = port.PortfolioValue != 0 || port.Sharpe != 0

	pnl, err := p.vdb.GetPnL()
	if err != nil {
		return snap, fmt.Errorf("GetPnL: %w", err)
	}
	snap.PnL = pnl

	signals, err := p.vdb.GetSignals()
	if err != nil {
		return snap, fmt.Errorf("GetSignals: %w", err)
	}
	snap.Signals = signals

	bt, err := p.vdb.GetBacktestStats()
	if err != nil {
		return snap, fmt.Errorf("GetBacktestStats: %w", err)
	}
	snap.BacktestStats = bt

	rm, err := p.vdb.GetRiskMetrics()
	if err != nil {
		return snap, fmt.Errorf("GetRiskMetrics: %w", err)
	}
	snap.RiskMetrics = rm

	eq, _, err := p.vdb.GetEquityCurve(500)
	if err != nil {
		return snap, fmt.Errorf("GetEquityCurve: %w", err)
	}
	snap.EquityCurve = eq

	return snap, nil
}

// ── StubVictoriaProvider ──────────────────────────────────────────────────────

// StubVictoriaProvider returns deterministic fixture data for tests and
// offline runs. All values reflect a plausible but synthetic trading state
// that exercises every eval check.
type StubVictoriaProvider struct{}

// IsLive returns false.
func (s *StubVictoriaProvider) IsLive() bool { return false }

// Source returns "stub".
func (s *StubVictoriaProvider) Source() string { return "stub" }

// Snapshot returns deterministic fixture data.
func (s *StubVictoriaProvider) Snapshot() (*VictoriaSnapshot, error) {
	recovDays := 14.0
	return &VictoriaSnapshot{
		Source:    "stub",
		Available: true,
		Portfolio: &db.VectoraPortfolio{
			PortfolioValue: 100_000,
			UnrealisedPnL:  1_200,
			RealisedPnL:    8_500,
			TotalPnL:       9_700,
			TotalReturn:    0.097,
			AnnReturn:      0.142,
			WinRate:        0.58,
			ProfitFactor:   1.42,
			Sharpe:         1.21,
			AnnVol:         0.18,
		},
		PnL: &db.VectoraPnL{
			UnrealisedPnL: 1_200,
			RealisedPnL:   8_500,
			TotalPnL:      9_700,
			TotalReturn:   0.097,
			AnnReturn:     0.142,
			WinRate:       0.58,
			ProfitFactor:  1.42,
			Sharpe:        1.21,
			AnnVol:        0.18,
			MaxDD:         0.083,
			Var95:         0.024,
			CVaR95:        0.037,
			Sortino:       1.74,
			Calmar:        1.71,
		},
		Signals: []*db.VectoraSignal{
			{Name: "momentum", AvgIC: 0.12, Weight: 0.35, HalfLife: 5, Conviction: 0.68, BrierScore: 0.21, CurrentValue: 0.4, Trend: "up"},
			{Name: "microstructure", AvgIC: 0.09, Weight: 0.25, HalfLife: 2, Conviction: 0.55, BrierScore: 0.24, CurrentValue: 0.2, Trend: "flat"},
			{Name: "sentiment", AvgIC: 0.06, Weight: 0.20, HalfLife: 10, Conviction: 0.48, BrierScore: 0.27, CurrentValue: -0.1, Trend: "down"},
			{Name: "funding", AvgIC: 0.04, Weight: 0.20, HalfLife: 8, Conviction: 0.41, BrierScore: 0.29, CurrentValue: 0.05, Trend: "flat"},
		},
		BacktestStats: &db.VectoraBacktestStats{
			SharpeAnn:    1.31,
			SortinoAnn:   1.89,
			MaxDDPct:     0.092,
			Calmar:       1.62,
			SharpeIS:     1.45,
			SharpeOOS:    1.31,
			VaR:          0.023,
			CVaR:         0.036,
			MeanR:        0.0004,
			StdR:         0.011,
			AnnReturn:    0.148,
			TotalReturn:  0.148,
			PortfolioVal: 100_000,
			WinRate:      0.59,
			ProfitFactor: 1.48,
		},
		RiskMetrics: &db.VectoraRiskMetrics{
			Ablation: []db.VectoraAblationEntry{
				{Name: "momentum", DSharpe: 0.38, Sig: true},
				{Name: "microstructure", DSharpe: 0.22, Sig: true},
				{Name: "sentiment", DSharpe: 0.09, Sig: false},
				{Name: "funding", DSharpe: 0.06, Sig: false},
			},
			Regimes: []db.VectoraRegime{
				{Name: "trending", Sharpe: 1.82, Ret: 0.21, Trades: 48, Pct: 0.38},
				{Name: "ranging", Sharpe: 0.44, Ret: 0.04, Trades: 62, Pct: 0.41},
				{Name: "high-vol", Sharpe: -0.31, Ret: -0.08, Trades: 19, Pct: 0.21},
			},
			Crashes: []db.VectoraCrashScenario{
				{Name: "COVID-2020", Sym: "BTC", DD: 0.52, Recov: &recovDays, SL: 2, Pnl: -0.04, Pass: true},
				{Name: "May-2021", Sym: "BTC", DD: 0.54, Recov: &recovDays, SL: 1, Pnl: -0.03, Pass: true},
				{Name: "LUNA-2022", Sym: "BTC", DD: 0.59, Recov: nil, SL: 3, Pnl: -0.06, Pass: false},
			},
		},
		EquityCurve: stubEquityCurve(120),
	}, nil
}

// stubEquityCurve returns n synthetic equity points with a deterministic walk.
func stubEquityCurve(n int) []*db.VectoraEquityPoint {
	pts := make([]*db.VectoraEquityPoint, n)
	omega, btc := 1.0, 1.0
	for i := 0; i < n; i++ {
		omega *= 1.0 + 0.0012 - float64(i%7)*0.0001
		btc *= 1.0 + 0.0008 - float64(i%11)*0.0001
		dd := 0.0
		if i >= 10 && i < 20 {
			dd = -0.04 * float64(i-10) / 10.0
		}
		pts[i] = &db.VectoraEquityPoint{
			Date:  fmt.Sprintf("2024-%02d-%02d", (i/30)+1, (i%30)+1),
			I:     i,
			Omega: omega,
			Btc:   btc,
			DD:    dd,
		}
	}
	return pts
}
