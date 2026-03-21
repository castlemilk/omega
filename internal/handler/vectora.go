package handler

import (
	"context"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.VectoraServiceHandler = (*VectoraHandler)(nil)

// VectoraHandler implements VectoraService.
type VectoraHandler struct {
	vdb *db.VectoraDB
}

// NewVectora creates a VectoraHandler backed by the given VectoraDB.
func NewVectora(vdb *db.VectoraDB) *VectoraHandler {
	return &VectoraHandler{vdb: vdb}
}

// ── GetPortfolio ──────────────────────────────────────────────────────────────

func (h *VectoraHandler) GetPortfolio(
	ctx context.Context,
	req *connect.Request[omegav1.GetPortfolioRequest],
) (*connect.Response[omegav1.GetPortfolioResponse], error) {
	p, err := h.vdb.GetPortfolio()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var alloc []*omegav1.VectoraAllocationSlice
	for _, a := range p.Allocation {
		alloc = append(alloc, &omegav1.VectoraAllocationSlice{
			Name:  a.Name,
			Value: a.Value,
			Color: a.Color,
		})
	}

	return connect.NewResponse(&omegav1.GetPortfolioResponse{
		PortfolioValue: p.PortfolioValue,
		UnrealisedPnl:  p.UnrealisedPnL,
		RealisedPnl:    p.RealisedPnL,
		TotalPnl:       p.TotalPnL,
		TotalReturn:    p.TotalReturn,
		AnnReturn:      p.AnnReturn,
		WinRate:        p.WinRate,
		ProfitFactor:   p.ProfitFactor,
		Sharpe:         p.Sharpe,
		AnnVol:         p.AnnVol,
		Allocation:     alloc,
	}), nil
}

// ── GetPositions ──────────────────────────────────────────────────────────────

func (h *VectoraHandler) GetPositions(
	ctx context.Context,
	req *connect.Request[omegav1.GetPositionsRequest],
) (*connect.Response[omegav1.GetPositionsResponse], error) {
	positions, err := h.vdb.GetPositions()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var protoPos []*omegav1.VectoraPosition
	for _, p := range positions {
		protoPos = append(protoPos, &omegav1.VectoraPosition{
			Sym:      p.Sym,
			Side:     p.Side,
			Size:     p.Size,
			Entry:    p.Entry,
			Mark:     p.Mark,
			Upnl:     p.Upnl,
			Pct:      p.Pct,
			Notional: p.Notional,
			Leverage: p.Leverage,
			Var95:    p.Var95,
		})
	}

	return connect.NewResponse(&omegav1.GetPositionsResponse{Positions: protoPos}), nil
}

// ── GetPnL ────────────────────────────────────────────────────────────────────

func (h *VectoraHandler) GetPnL(
	ctx context.Context,
	req *connect.Request[omegav1.GetPnLRequest],
) (*connect.Response[omegav1.GetPnLResponse], error) {
	p, err := h.vdb.GetPnL()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&omegav1.GetPnLResponse{
		UnrealisedPnl: p.UnrealisedPnL,
		RealisedPnl:   p.RealisedPnL,
		TotalPnl:      p.TotalPnL,
		TotalReturn:   p.TotalReturn,
		AnnReturn:     p.AnnReturn,
		WinRate:       p.WinRate,
		ProfitFactor:  p.ProfitFactor,
		Sharpe:        p.Sharpe,
		AnnVol:        p.AnnVol,
		MaxDd:         p.MaxDD,
		Var95:         p.Var95,
		Cvar95:        p.CVaR95,
		Sortino:       p.Sortino,
		Calmar:        p.Calmar,
	}), nil
}

// ── GetSignals ────────────────────────────────────────────────────────────────

func (h *VectoraHandler) GetSignals(
	ctx context.Context,
	req *connect.Request[omegav1.GetSignalsRequest],
) (*connect.Response[omegav1.GetSignalsResponse], error) {
	signals, err := h.vdb.GetSignals()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var protoSigs []*omegav1.VectoraSignal
	var totalConviction, totalWeight float64
	for _, s := range signals {
		protoSigs = append(protoSigs, &omegav1.VectoraSignal{
			Name:         s.Name,
			AvgIc:        s.AvgIC,
			Weight:       s.Weight,
			HalfLife:     int32(s.HalfLife), //nolint:gosec
			Color:        s.Color,
			Conviction:   s.Conviction,
			BrierScore:   s.BrierScore,
			CurrentValue: s.CurrentValue,
			Trend:        s.Trend,
		})
		totalConviction += s.Conviction * s.Weight
		totalWeight += s.Weight
	}

	compositeScore := 0.0
	if totalWeight > 0 {
		compositeScore = totalConviction / totalWeight
	}
	compositeDir := "NEUTRAL"
	if compositeScore > 0.5 {
		compositeDir = "LONG"
	} else if compositeScore < 0.4 {
		compositeDir = "SHORT"
	}

	// OOS Sharpe from backtest table
	bt, _ := h.vdb.GetBacktestStats()
	oosSharpe := 0.0
	if bt != nil {
		oosSharpe = bt.SharpeOOS
	}

	return connect.NewResponse(&omegav1.GetSignalsResponse{
		Signals:            protoSigs,
		CompositeScore:     compositeScore,
		CompositeDirection: compositeDir,
		OosSharpe:          oosSharpe,
	}), nil
}

// ── GetSignalHistory ──────────────────────────────────────────────────────────

func (h *VectoraHandler) GetSignalHistory(
	ctx context.Context,
	req *connect.Request[omegav1.GetSignalHistoryRequest],
) (*connect.Response[omegav1.GetSignalHistoryResponse], error) {
	points, err := h.vdb.GetSignalHistory(req.Msg.SignalName, int(req.Msg.Limit))
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var protoPoints []*omegav1.VectoraSignalICPoint
	for _, p := range points {
		protoPoints = append(protoPoints, &omegav1.VectoraSignalICPoint{
			T:  int32(p.T), //nolint:gosec
			Ic: p.IC,
		})
	}

	return connect.NewResponse(&omegav1.GetSignalHistoryResponse{Points: protoPoints}), nil
}

// ── GetTrades ─────────────────────────────────────────────────────────────────

func (h *VectoraHandler) GetTrades(
	ctx context.Context,
	req *connect.Request[omegav1.GetTradesRequest],
) (*connect.Response[omegav1.GetTradesResponse], error) {
	trades, err := h.vdb.GetTrades(req.Msg.SymFilter, req.Msg.SideFilter, int(req.Msg.Limit))
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var protoTrades []*omegav1.VectoraTrade
	for _, t := range trades {
		protoTrades = append(protoTrades, &omegav1.VectoraTrade{
			Ts:         t.Ts,
			Sym:        t.Sym,
			Side:       t.Side,
			Size:       t.Size,
			Entry:      t.Entry,
			ExitPrice:  t.ExitPrice,
			Pnl:        t.Pnl,
			Slippage:   t.Slippage,
			Duration:   t.Duration,
		})
	}

	return connect.NewResponse(&omegav1.GetTradesResponse{Trades: protoTrades}), nil
}

// ── GetBacktestResults ────────────────────────────────────────────────────────

func (h *VectoraHandler) GetBacktestResults(
	ctx context.Context,
	req *connect.Request[omegav1.GetBacktestResultsRequest],
) (*connect.Response[omegav1.GetBacktestResultsResponse], error) {
	s, err := h.vdb.GetBacktestStats()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&omegav1.GetBacktestResultsResponse{
		Stats: &omegav1.VectoraBacktestStats{
			SharpeAnn:     s.SharpeAnn,
			SortinoAnn:    s.SortinoAnn,
			MaxDdPct:      s.MaxDDPct,
			Calmar:        s.Calmar,
			SharpeIs:      s.SharpeIS,
			SharpeOos:     s.SharpeOOS,
			Var:           s.VaR,
			Cvar:          s.CVaR,
			MeanR:         s.MeanR,
			StdR:          s.StdR,
			AnnReturn:     s.AnnReturn,
			TotalReturn:   s.TotalReturn,
			PortfolioValue: s.PortfolioVal,
			MaxDdDuration: int32(s.MaxDDDuration), //nolint:gosec
			WinRate:       s.WinRate,
			ProfitFactor:  s.ProfitFactor,
			TrainEnd:      int32(s.TrainEnd), //nolint:gosec
		},
	}), nil
}

// ── GetEquityCurve ────────────────────────────────────────────────────────────

func (h *VectoraHandler) GetEquityCurve(
	ctx context.Context,
	req *connect.Request[omegav1.GetEquityCurveRequest],
) (*connect.Response[omegav1.GetEquityCurveResponse], error) {
	points, trainEnd, err := h.vdb.GetEquityCurve(int(req.Msg.Limit))
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var protoPoints []*omegav1.VectoraEquityPoint
	for _, p := range points {
		protoPoints = append(protoPoints, &omegav1.VectoraEquityPoint{
			Date:  p.Date,
			I:     int32(p.I), //nolint:gosec
			Omega: p.Omega,
			Btc:   p.Btc,
			Dd:    p.DD,
		})
	}

	return connect.NewResponse(&omegav1.GetEquityCurveResponse{
		Points:   protoPoints,
		TrainEnd: int32(trainEnd), //nolint:gosec
	}), nil
}

// ── GetRiskMetrics ────────────────────────────────────────────────────────────

func (h *VectoraHandler) GetRiskMetrics(
	ctx context.Context,
	req *connect.Request[omegav1.GetRiskMetricsRequest],
) (*connect.Response[omegav1.GetRiskMetricsResponse], error) {
	m, err := h.vdb.GetRiskMetrics()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var ablation []*omegav1.VectoraAblationEntry
	for _, a := range m.Ablation {
		ablation = append(ablation, &omegav1.VectoraAblationEntry{
			Name:    a.Name,
			DSharpe: a.DSharpe,
			Sig:     a.Sig,
		})
	}

	var regimes []*omegav1.VectoraRegime
	for _, r := range m.Regimes {
		regimes = append(regimes, &omegav1.VectoraRegime{
			Name:   r.Name,
			Sharpe: r.Sharpe,
			Ret:    r.Ret,
			Trades: int32(r.Trades), //nolint:gosec
			Pct:    r.Pct,
		})
	}

	var crashes []*omegav1.VectoraCrashScenario
	for _, c := range m.Crashes {
		sc := &omegav1.VectoraCrashScenario{
			Name:     c.Name,
			Sym:      c.Sym,
			Dd:       c.DD,
			Sl:       int32(c.SL), //nolint:gosec
			Pnl:      c.Pnl,
			Pass:     c.Pass,
			HasRecov: c.Recov != nil,
		}
		if c.Recov != nil {
			sc.Recov = *c.Recov
		}
		crashes = append(crashes, sc)
	}

	var funding []*omegav1.VectoraFundingPoint
	for _, f := range m.FundingData {
		funding = append(funding, &omegav1.VectoraFundingPoint{
			T:       int32(f.T), //nolint:gosec
			Funding: f.Funding,
			Oi:      f.OI,
		})
	}

	var adv []*omegav1.VectoraAdvPoint
	for _, a := range m.AdvSeries {
		adv = append(adv, &omegav1.VectoraAdvPoint{
			T:    int32(a.T), //nolint:gosec
			Flag: a.Flag,
			Fp:   a.FP,
		})
	}

	var tpe []*omegav1.VectoraTpePoint
	for _, t := range m.TpeSeries {
		tpe = append(tpe, &omegav1.VectoraTpePoint{
			T:     int32(t.T), //nolint:gosec
			Score: t.Score,
			Best:  t.Best,
		})
	}

	return connect.NewResponse(&omegav1.GetRiskMetricsResponse{
		Ablation:         ablation,
		Regimes:          regimes,
		CurrentRegimeIdx: int32(m.CurrentRegimeIdx), //nolint:gosec
		Crashes:          crashes,
		FundingData:      funding,
		AdvSeries:        adv,
		TpeSeries:        tpe,
		LatestFunding:    m.LatestFunding,
		LatestOi:         m.LatestOI,
	}), nil
}
