package db

import (
	"database/sql"
	"encoding/json"
)

// VictoriaDB provides read access to Victoria trading state tables.
// The Python trading engine writes these tables; Go reads them for the dashboard.
// With Postgres, they live in the same database as all other Omega tables.
type VictoriaDB struct {
	db *sql.DB
}

// NewVictoria creates a VictoriaDB reader backed by the shared Omega database.
func NewVictoria(db *sql.DB) *VictoriaDB {
	return &VictoriaDB{db: db}
}

// Close is a no-op — the underlying db is shared with the main DB pool.
func (v *VictoriaDB) Close() {}

// ── Types ─────────────────────────────────────────────────────────────────────

type VictoriaPortfolio struct {
	PortfolioValue float64
	UnrealisedPnL  float64
	RealisedPnL    float64
	TotalPnL       float64
	TotalReturn    float64
	AnnReturn      float64
	WinRate        float64
	ProfitFactor   float64
	Sharpe         float64
	AnnVol         float64
	Allocation     []VictoriaAllocationSlice
}

type VictoriaAllocationSlice struct {
	Name  string
	Value float64
	Color string
}

type VictoriaPosition struct {
	Sym      string
	Side     string
	Size     float64
	Entry    float64
	Mark     float64
	Upnl     float64
	Pct      float64
	Notional float64
	Leverage float64
	Var95    float64
}

type VictoriaPnL struct {
	UnrealisedPnL float64
	RealisedPnL   float64
	TotalPnL      float64
	TotalReturn   float64
	AnnReturn     float64
	WinRate       float64
	ProfitFactor  float64
	Sharpe        float64
	AnnVol        float64
	MaxDD         float64
	Var95         float64
	CVaR95        float64
	Sortino       float64
	Calmar        float64
}

type VictoriaSignal struct {
	Name         string
	AvgIC        float64
	Weight       float64
	HalfLife     int
	Color        string
	Conviction   float64
	BrierScore   float64
	CurrentValue float64
	Trend        string
}

type VictoriaSignalICPoint struct {
	T  int
	IC float64
}

type VictoriaTrade struct {
	Ts        string
	Sym       string
	Side      string
	Size      float64
	Entry     float64
	ExitPrice float64
	Pnl       float64
	Slippage  float64
	Duration  string
}

type VictoriaBacktestStats struct {
	SharpeAnn     float64
	SortinoAnn    float64
	MaxDDPct      float64
	Calmar        float64
	SharpeIS      float64
	SharpeOOS     float64
	VaR           float64
	CVaR          float64
	MeanR         float64
	StdR          float64
	AnnReturn     float64
	TotalReturn   float64
	PortfolioVal  float64
	MaxDDDuration int
	WinRate       float64
	ProfitFactor  float64
	TrainEnd      int
}

type VictoriaEquityPoint struct {
	Date  string
	I     int
	Omega float64
	Btc   float64
	DD    float64
}

type VictoriaAblationEntry struct {
	Name    string  `json:"name"`
	DSharpe float64 `json:"dSharpe"`
	Sig     bool    `json:"sig"`
}

type VictoriaRegime struct {
	Name   string  `json:"name"`
	Sharpe float64 `json:"sharpe"`
	Ret    float64 `json:"ret"`
	Trades int     `json:"trades"`
	Pct    float64 `json:"pct"`
}

type VictoriaCrashScenario struct {
	Name  string   `json:"name"`
	Sym   string   `json:"sym"`
	DD    float64  `json:"dd"`
	Recov *float64 `json:"recov"`
	SL    int      `json:"sl"`
	Pnl   float64  `json:"pnl"`
	Pass  bool     `json:"pass"`
}

type VictoriaFundingPoint struct {
	T       int     `json:"t"`
	Funding float64 `json:"funding"`
	OI      float64 `json:"oi"`
}

type VictoriaAdvPoint struct {
	T    int     `json:"t"`
	Flag float64 `json:"flag"`
	FP   float64 `json:"fp"`
}

type VictoriaTpePoint struct {
	T     int     `json:"t"`
	Score float64 `json:"score"`
	Best  float64 `json:"best"`
}

type VictoriaRiskMetrics struct {
	Ablation         []VictoriaAblationEntry
	Regimes          []VictoriaRegime
	CurrentRegimeIdx int
	Crashes          []VictoriaCrashScenario
	FundingData      []VictoriaFundingPoint
	AdvSeries        []VictoriaAdvPoint
	TpeSeries        []VictoriaTpePoint
	LatestFunding    float64
	LatestOI         float64
}

// ── Portfolio ─────────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetPortfolio() (*VictoriaPortfolio, error) {
	p := &VictoriaPortfolio{}
	row := v.db.QueryRow(`
		SELECT portfolio_value, unrealised_pnl, realised_pnl, total_pnl,
		       total_return, ann_return, win_rate, profit_factor, sharpe, ann_vol,
		       COALESCE(allocation::text, '[]')
		FROM victoria_portfolio ORDER BY updated_at DESC LIMIT 1`)
	var allocJSON string
	if err := row.Scan(&p.PortfolioValue, &p.UnrealisedPnL, &p.RealisedPnL, &p.TotalPnL,
		&p.TotalReturn, &p.AnnReturn, &p.WinRate, &p.ProfitFactor,
		&p.Sharpe, &p.AnnVol, &allocJSON); err != nil {
		if err == sql.ErrNoRows {
			return p, nil
		}
		return nil, err
	}
	json.Unmarshal([]byte(allocJSON), &p.Allocation) //nolint:errcheck,gosec
	return p, nil
}

// ── Positions ─────────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetPositions() ([]*VictoriaPosition, error) {
	rows, err := v.db.Query(`
		SELECT sym, side, size, entry, mark, upnl, pct, notional, leverage, var95
		FROM victoria_positions ORDER BY notional DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var positions []*VictoriaPosition
	for rows.Next() {
		p := &VictoriaPosition{}
		if err := rows.Scan(&p.Sym, &p.Side, &p.Size, &p.Entry, &p.Mark,
			&p.Upnl, &p.Pct, &p.Notional, &p.Leverage, &p.Var95); err != nil {
			return nil, err
		}
		positions = append(positions, p)
	}
	return positions, nil
}

// ── PnL ──────────────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetPnL() (*VictoriaPnL, error) {
	p := &VictoriaPnL{}
	row := v.db.QueryRow(`
		SELECT unrealised_pnl, realised_pnl, total_pnl, total_return, ann_return,
		       win_rate, profit_factor, sharpe, ann_vol, max_dd, var95, cvar95, sortino, calmar
		FROM victoria_pnl ORDER BY updated_at DESC LIMIT 1`)
	err := row.Scan(&p.UnrealisedPnL, &p.RealisedPnL, &p.TotalPnL, &p.TotalReturn,
		&p.AnnReturn, &p.WinRate, &p.ProfitFactor, &p.Sharpe, &p.AnnVol,
		&p.MaxDD, &p.Var95, &p.CVaR95, &p.Sortino, &p.Calmar)
	if err == sql.ErrNoRows {
		return p, nil
	}
	return p, err
}

// ── Signals ──────────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetSignals() ([]*VictoriaSignal, error) {
	rows, err := v.db.Query(`
		SELECT name, avg_ic, weight, half_life, color, conviction, brier_score, current_value, trend
		FROM victoria_signals ORDER BY weight DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var signals []*VictoriaSignal
	for rows.Next() {
		s := &VictoriaSignal{}
		if err := rows.Scan(&s.Name, &s.AvgIC, &s.Weight, &s.HalfLife, &s.Color,
			&s.Conviction, &s.BrierScore, &s.CurrentValue, &s.Trend); err != nil {
			return nil, err
		}
		signals = append(signals, s)
	}
	return signals, nil
}

func (v *VictoriaDB) GetSignalHistory(signalName string, limit int) ([]*VictoriaSignalICPoint, error) {
	if limit <= 0 {
		limit = 60
	}
	rows, err := v.db.Query(`
		SELECT t, ic FROM victoria_signal_history
		WHERE signal_name = $1
		ORDER BY t DESC LIMIT $2`, signalName, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var points []*VictoriaSignalICPoint
	for rows.Next() {
		p := &VictoriaSignalICPoint{}
		if err := rows.Scan(&p.T, &p.IC); err != nil {
			return nil, err
		}
		points = append(points, p)
	}
	for i, j := 0, len(points)-1; i < j; i, j = i+1, j-1 {
		points[i], points[j] = points[j], points[i]
	}
	return points, nil
}

// ── Trades ───────────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetTrades(symFilter, sideFilter string, limit int) ([]*VictoriaTrade, error) {
	if limit <= 0 {
		limit = 100
	}
	query := `SELECT ts, sym, side, size, entry, exit_price, pnl, slippage, duration
		FROM victoria_trades WHERE TRUE`
	args := []any{}
	argN := 1
	if symFilter != "" {
		query += ` AND sym = $` + itoa(argN)
		args = append(args, symFilter)
		argN++
	}
	if sideFilter != "" {
		query += ` AND side = $` + itoa(argN)
		args = append(args, sideFilter)
		argN++
	}
	query += ` ORDER BY recorded_at DESC LIMIT $` + itoa(argN) //nolint:gosec
	args = append(args, limit)

	rows, err := v.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var trades []*VictoriaTrade
	for rows.Next() {
		t := &VictoriaTrade{}
		if err := rows.Scan(&t.Ts, &t.Sym, &t.Side, &t.Size, &t.Entry,
			&t.ExitPrice, &t.Pnl, &t.Slippage, &t.Duration); err != nil {
			return nil, err
		}
		trades = append(trades, t)
	}
	return trades, nil
}

// ── Backtest ─────────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetBacktestStats() (*VictoriaBacktestStats, error) {
	s := &VictoriaBacktestStats{}
	row := v.db.QueryRow(`
		SELECT sharpe_ann, sortino_ann, max_dd_pct, calmar, sharpe_is, sharpe_oos,
		       var, cvar, mean_r, std_r, ann_return, total_return, portfolio_value,
		       max_dd_duration, win_rate, profit_factor, train_end
		FROM victoria_backtest ORDER BY updated_at DESC LIMIT 1`)
	err := row.Scan(&s.SharpeAnn, &s.SortinoAnn, &s.MaxDDPct, &s.Calmar, &s.SharpeIS,
		&s.SharpeOOS, &s.VaR, &s.CVaR, &s.MeanR, &s.StdR, &s.AnnReturn,
		&s.TotalReturn, &s.PortfolioVal, &s.MaxDDDuration, &s.WinRate,
		&s.ProfitFactor, &s.TrainEnd)
	if err == sql.ErrNoRows {
		return s, nil
	}
	return s, err
}

// ── Equity Curve ─────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetEquityCurve(limit int) ([]*VictoriaEquityPoint, int, error) {
	if limit <= 0 {
		limit = 1000
	}
	rows, err := v.db.Query(`
		SELECT date, i, omega, btc, dd
		FROM victoria_equity_curve
		ORDER BY i ASC LIMIT $1`, limit)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var points []*VictoriaEquityPoint
	for rows.Next() {
		p := &VictoriaEquityPoint{}
		if err := rows.Scan(&p.Date, &p.I, &p.Omega, &p.Btc, &p.DD); err != nil {
			return nil, 0, err
		}
		points = append(points, p)
	}

	var trainEnd int
	v.db.QueryRow(`SELECT COALESCE(MAX(train_end), 0) FROM victoria_equity_curve`).Scan(&trainEnd) //nolint:errcheck,gosec

	return points, trainEnd, nil
}

// ── Risk Metrics ─────────────────────────────────────────────────────────────

func (v *VictoriaDB) GetRiskMetrics() (*VictoriaRiskMetrics, error) {
	m := &VictoriaRiskMetrics{}
	row := v.db.QueryRow(`
		SELECT COALESCE(ablation::text,'[]'), COALESCE(regimes::text,'[]'),
		       current_regime_idx,
		       COALESCE(crashes::text,'[]'), COALESCE(funding::text,'[]'),
		       COALESCE(adv_series::text,'[]'), COALESCE(tpe_series::text,'[]')
		FROM victoria_risk_metrics ORDER BY updated_at DESC LIMIT 1`)

	var ablationJSON, regimesJSON, crashesJSON, fundingJSON, advJSON, tpeJSON string
	err := row.Scan(&ablationJSON, &regimesJSON, &m.CurrentRegimeIdx,
		&crashesJSON, &fundingJSON, &advJSON, &tpeJSON)
	if err == sql.ErrNoRows {
		return m, nil
	}
	if err != nil {
		return nil, err
	}

	json.Unmarshal([]byte(ablationJSON), &m.Ablation)   //nolint:errcheck,gosec
	json.Unmarshal([]byte(regimesJSON), &m.Regimes)     //nolint:errcheck,gosec
	json.Unmarshal([]byte(crashesJSON), &m.Crashes)     //nolint:errcheck,gosec
	json.Unmarshal([]byte(fundingJSON), &m.FundingData)  //nolint:errcheck,gosec
	json.Unmarshal([]byte(advJSON), &m.AdvSeries)       //nolint:errcheck,gosec
	json.Unmarshal([]byte(tpeJSON), &m.TpeSeries)       //nolint:errcheck,gosec

	if len(m.FundingData) > 0 {
		last := m.FundingData[len(m.FundingData)-1]
		m.LatestFunding = last.Funding
		m.LatestOI = last.OI
	}

	return m, nil
}

// ── Signal Performance ────────────────────────────────────────────────────────

// SignalPerfRow holds the latest performance snapshot for one signal.
type SignalPerfRow struct {
	SignalName     string
	Cycle          int
	IC             float64
	HitRate        float64
	ValueAdded     float64
	Stability      float64
	CompositeScore float64
	Timestamp      string
}

// GetSignalPerformance returns the latest signal_performance row per signal,
// ordered by composite_score descending.
//
// The signal_performance table is written by the Python SignalPerformanceTracker
// and read here for the CLI leaderboard and attention router quality feed.
func (v *VictoriaDB) GetSignalPerformance() ([]*SignalPerfRow, error) {
	rows, err := v.db.Query(`
		SELECT DISTINCT ON (signal_name)
			signal_name, cycle, ic, hit_rate, value_added, stability,
			composite_score, TO_CHAR(timestamp, 'YYYY-MM-DD HH24:MI:SS')
		FROM signal_performance
		ORDER BY signal_name, cycle DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var result []*SignalPerfRow
	for rows.Next() {
		r := &SignalPerfRow{}
		if err := rows.Scan(
			&r.SignalName, &r.Cycle, &r.IC, &r.HitRate,
			&r.ValueAdded, &r.Stability, &r.CompositeScore, &r.Timestamp,
		); err != nil {
			return nil, err
		}
		result = append(result, r)
	}
	return result, rows.Err()
}

// GetAvgSignalQuality returns the average composite_score across all signals
// from their most recent cycle.  Used by the coordination layer to feed signal
// quality back into the RoutingWeightAdapter.
func (v *VictoriaDB) GetAvgSignalQuality() (float64, error) {
	var avg float64
	err := v.db.QueryRow(`
		SELECT COALESCE(AVG(latest.composite_score), 0.5)
		FROM (
			SELECT DISTINCT ON (signal_name)
				composite_score
			FROM signal_performance
			ORDER BY signal_name, cycle DESC
		) latest`).Scan(&avg)
	if err != nil {
		return 0.5, err
	}
	return avg, nil
}

// itoa converts int to string for query building (avoids fmt import).
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	b := make([]byte, 0, 3)
	for n > 0 {
		b = append([]byte{byte('0' + n%10)}, b...)
		n /= 10
	}
	return string(b)
}
