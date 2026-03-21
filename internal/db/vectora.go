package db

import (
	"database/sql"
	"encoding/json"
	"os"
)

// VectoraDBPath returns the SQLite DB path for Vectora trading state.
func VectoraDBPath() string {
	if p := os.Getenv("VECTORA_STATE_DB_PATH"); p != "" {
		return p
	}
	return "/tmp/vectora_state.db"
}

// ── Vectora DB ────────────────────────────────────────────────────────────────

// VectoraDB holds a connection to the Vectora trading state database.
// The Python trading engine writes; this Go layer reads.
type VectoraDB struct {
	db *sql.DB
}

// NewVectora opens the Vectora SQLite database. If the file doesn't exist yet,
// it creates an empty one so the server can start before the trading engine runs.
func NewVectora(path string) (*VectoraDB, error) {
	if _, err := os.Stat(path); os.IsNotExist(err) {
		f, _ := os.Create(path) //nolint:gosec
		if f != nil {
			f.Close() //nolint:errcheck,gosec
		}
	}
	d, err := openDB(path)
	if err != nil {
		return nil, err
	}
	return &VectoraDB{db: d}, nil
}

func (v *VectoraDB) Close() {
	v.db.Close() //nolint:errcheck,gosec
}

// ── Types ─────────────────────────────────────────────────────────────────────

type VectoraPortfolio struct {
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
	Allocation     []VectoraAllocationSlice
}

type VectoraAllocationSlice struct {
	Name  string
	Value float64
	Color string
}

type VectoraPosition struct {
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

type VectoraPnL struct {
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

type VectoraSignal struct {
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

type VectoraSignalICPoint struct {
	T  int
	IC float64
}

type VectoraTrade struct {
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

type VectoraBacktestStats struct {
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

type VectoraEquityPoint struct {
	Date  string
	I     int
	Omega float64
	Btc   float64
	DD    float64
}

type VectoraAblationEntry struct {
	Name   string  `json:"name"`
	DSharpe float64 `json:"dSharpe"`
	Sig    bool    `json:"sig"`
}

type VectoraRegime struct {
	Name   string  `json:"name"`
	Sharpe float64 `json:"sharpe"`
	Ret    float64 `json:"ret"`
	Trades int     `json:"trades"`
	Pct    float64 `json:"pct"`
}

type VectoraCrashScenario struct {
	Name    string   `json:"name"`
	Sym     string   `json:"sym"`
	DD      float64  `json:"dd"`
	Recov   *float64 `json:"recov"`
	SL      int      `json:"sl"`
	Pnl     float64  `json:"pnl"`
	Pass    bool     `json:"pass"`
}

type VectoraFundingPoint struct {
	T       int     `json:"t"`
	Funding float64 `json:"funding"`
	OI      float64 `json:"oi"`
}

type VectoraAdvPoint struct {
	T    int     `json:"t"`
	Flag float64 `json:"flag"`
	FP   float64 `json:"fp"`
}

type VectoraTpePoint struct {
	T     int     `json:"t"`
	Score float64 `json:"score"`
	Best  float64 `json:"best"`
}

type VectoraRiskMetrics struct {
	Ablation         []VectoraAblationEntry
	Regimes          []VectoraRegime
	CurrentRegimeIdx int
	Crashes          []VectoraCrashScenario
	FundingData      []VectoraFundingPoint
	AdvSeries        []VectoraAdvPoint
	TpeSeries        []VectoraTpePoint
	LatestFunding    float64
	LatestOI         float64
}

// ── Query helpers ─────────────────────────────────────────────────────────────

// tableExists checks if a table exists in the database.
func (v *VectoraDB) tableExists(name string) bool {
	var count int
	v.db.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?`, name).Scan(&count) //nolint:errcheck,gosec
	return count > 0
}

// ── Portfolio ─────────────────────────────────────────────────────────────────

func (v *VectoraDB) GetPortfolio() (*VectoraPortfolio, error) {
	p := &VectoraPortfolio{}

	if !v.tableExists("vectora_portfolio") {
		return p, nil
	}

	row := v.db.QueryRow(`
		SELECT portfolio_value, unrealised_pnl, realised_pnl, total_pnl,
		       total_return, ann_return, win_rate, profit_factor, sharpe, ann_vol,
		       COALESCE(allocation_json, '[]')
		FROM vectora_portfolio ORDER BY updated_at DESC LIMIT 1`)
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

func (v *VectoraDB) GetPositions() ([]*VectoraPosition, error) {
	if !v.tableExists("vectora_positions") {
		return nil, nil
	}

	rows, err := v.db.Query(`
		SELECT sym, side, size, entry, mark, upnl, pct, notional, leverage, var95
		FROM vectora_positions ORDER BY notional DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var positions []*VectoraPosition
	for rows.Next() {
		p := &VectoraPosition{}
		if err := rows.Scan(&p.Sym, &p.Side, &p.Size, &p.Entry, &p.Mark,
			&p.Upnl, &p.Pct, &p.Notional, &p.Leverage, &p.Var95); err != nil {
			return nil, err
		}
		positions = append(positions, p)
	}
	return positions, nil
}

// ── PnL ──────────────────────────────────────────────────────────────────────

func (v *VectoraDB) GetPnL() (*VectoraPnL, error) {
	p := &VectoraPnL{}

	if !v.tableExists("vectora_pnl") {
		return p, nil
	}

	row := v.db.QueryRow(`
		SELECT unrealised_pnl, realised_pnl, total_pnl, total_return, ann_return,
		       win_rate, profit_factor, sharpe, ann_vol, max_dd, var95, cvar95, sortino, calmar
		FROM vectora_pnl ORDER BY updated_at DESC LIMIT 1`)
	err := row.Scan(&p.UnrealisedPnL, &p.RealisedPnL, &p.TotalPnL, &p.TotalReturn,
		&p.AnnReturn, &p.WinRate, &p.ProfitFactor, &p.Sharpe, &p.AnnVol,
		&p.MaxDD, &p.Var95, &p.CVaR95, &p.Sortino, &p.Calmar)
	if err == sql.ErrNoRows {
		return p, nil
	}
	return p, err
}

// ── Signals ──────────────────────────────────────────────────────────────────

func (v *VectoraDB) GetSignals() ([]*VectoraSignal, error) {
	if !v.tableExists("vectora_signals") {
		return nil, nil
	}

	rows, err := v.db.Query(`
		SELECT name, avg_ic, weight, half_life, color, conviction, brier_score, current_value, trend
		FROM vectora_signals ORDER BY weight DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var signals []*VectoraSignal
	for rows.Next() {
		s := &VectoraSignal{}
		if err := rows.Scan(&s.Name, &s.AvgIC, &s.Weight, &s.HalfLife, &s.Color,
			&s.Conviction, &s.BrierScore, &s.CurrentValue, &s.Trend); err != nil {
			return nil, err
		}
		signals = append(signals, s)
	}
	return signals, nil
}

func (v *VectoraDB) GetSignalHistory(signalName string, limit int) ([]*VectoraSignalICPoint, error) {
	if !v.tableExists("vectora_signal_history") {
		return nil, nil
	}
	if limit <= 0 {
		limit = 60
	}

	rows, err := v.db.Query(`
		SELECT t, ic FROM vectora_signal_history
		WHERE signal_name = ?
		ORDER BY t DESC LIMIT ?`, signalName, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var points []*VectoraSignalICPoint
	for rows.Next() {
		p := &VectoraSignalICPoint{}
		if err := rows.Scan(&p.T, &p.IC); err != nil {
			return nil, err
		}
		points = append(points, p)
	}
	// Reverse to chronological order
	for i, j := 0, len(points)-1; i < j; i, j = i+1, j-1 {
		points[i], points[j] = points[j], points[i]
	}
	return points, nil
}

// ── Trades ───────────────────────────────────────────────────────────────────

func (v *VectoraDB) GetTrades(symFilter, sideFilter string, limit int) ([]*VectoraTrade, error) {
	if !v.tableExists("vectora_trades") {
		return nil, nil
	}
	if limit <= 0 {
		limit = 100
	}

	query := `SELECT ts, sym, side, size, entry, exit_price, pnl, slippage, duration
		FROM vectora_trades WHERE 1=1`
	args := []any{}
	if symFilter != "" {
		query += " AND sym = ?"
		args = append(args, symFilter)
	}
	if sideFilter != "" {
		query += " AND side = ?"
		args = append(args, sideFilter)
	}
	query += " ORDER BY recorded_at DESC LIMIT ?"
	args = append(args, limit)

	rows, err := v.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var trades []*VectoraTrade
	for rows.Next() {
		t := &VectoraTrade{}
		if err := rows.Scan(&t.Ts, &t.Sym, &t.Side, &t.Size, &t.Entry,
			&t.ExitPrice, &t.Pnl, &t.Slippage, &t.Duration); err != nil {
			return nil, err
		}
		trades = append(trades, t)
	}
	return trades, nil
}

// ── Backtest ─────────────────────────────────────────────────────────────────

func (v *VectoraDB) GetBacktestStats() (*VectoraBacktestStats, error) {
	s := &VectoraBacktestStats{}

	if !v.tableExists("vectora_backtest") {
		return s, nil
	}

	row := v.db.QueryRow(`
		SELECT sharpe_ann, sortino_ann, max_dd_pct, calmar, sharpe_is, sharpe_oos,
		       var, cvar, mean_r, std_r, ann_return, total_return, portfolio_value,
		       max_dd_duration, win_rate, profit_factor, train_end
		FROM vectora_backtest ORDER BY updated_at DESC LIMIT 1`)
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

func (v *VectoraDB) GetEquityCurve(limit int) ([]*VectoraEquityPoint, int, error) {
	if !v.tableExists("vectora_equity_curve") {
		return nil, 0, nil
	}
	if limit <= 0 {
		limit = 1000
	}

	rows, err := v.db.Query(`
		SELECT date, i, omega, btc, dd
		FROM vectora_equity_curve
		ORDER BY i ASC LIMIT ?`, limit)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var points []*VectoraEquityPoint
	for rows.Next() {
		p := &VectoraEquityPoint{}
		if err := rows.Scan(&p.Date, &p.I, &p.Omega, &p.Btc, &p.DD); err != nil {
			return nil, 0, err
		}
		points = append(points, p)
	}

	var trainEnd int
	v.db.QueryRow(`SELECT COALESCE(MAX(train_end), 0) FROM vectora_equity_curve`).Scan(&trainEnd) //nolint:errcheck,gosec

	return points, trainEnd, nil
}

// ── Risk Metrics ─────────────────────────────────────────────────────────────

func (v *VectoraDB) GetRiskMetrics() (*VectoraRiskMetrics, error) {
	m := &VectoraRiskMetrics{}

	if !v.tableExists("vectora_risk_metrics") {
		return m, nil
	}

	row := v.db.QueryRow(`
		SELECT COALESCE(ablation_json,'[]'), COALESCE(regimes_json,'[]'),
		       current_regime_idx,
		       COALESCE(crashes_json,'[]'), COALESCE(funding_json,'[]'),
		       COALESCE(adv_series_json,'[]'), COALESCE(tpe_series_json,'[]')
		FROM vectora_risk_metrics ORDER BY updated_at DESC LIMIT 1`)

	var ablationJSON, regimesJSON, crashesJSON, fundingJSON, advJSON, tpeJSON string
	err := row.Scan(&ablationJSON, &regimesJSON, &m.CurrentRegimeIdx,
		&crashesJSON, &fundingJSON, &advJSON, &tpeJSON)
	if err == sql.ErrNoRows {
		return m, nil
	}
	if err != nil {
		return nil, err
	}

	json.Unmarshal([]byte(ablationJSON), &m.Ablation)  //nolint:errcheck,gosec
	json.Unmarshal([]byte(regimesJSON), &m.Regimes)    //nolint:errcheck,gosec
	json.Unmarshal([]byte(crashesJSON), &m.Crashes)    //nolint:errcheck,gosec
	json.Unmarshal([]byte(fundingJSON), &m.FundingData) //nolint:errcheck,gosec
	json.Unmarshal([]byte(advJSON), &m.AdvSeries)      //nolint:errcheck,gosec
	json.Unmarshal([]byte(tpeJSON), &m.TpeSeries)      //nolint:errcheck,gosec

	if len(m.FundingData) > 0 {
		last := m.FundingData[len(m.FundingData)-1]
		m.LatestFunding = last.Funding
		m.LatestOI = last.OI
	}

	return m, nil
}
