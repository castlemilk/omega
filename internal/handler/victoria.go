package handler

import (
	"context"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.VictoriaServiceHandler = (*VictoriaHandler)(nil)

// VictoriaHandler implements VictoriaService.
type VictoriaHandler struct {
	vdb *db.VictoriaDB
}

// NewVictoria creates a VictoriaHandler backed by the given VictoriaDB.
func NewVictoria(vdb *db.VictoriaDB) *VictoriaHandler {
	return &VictoriaHandler{vdb: vdb}
}

// ── GetPortfolio ──────────────────────────────────────────────────────────────

func (h *VictoriaHandler) GetPortfolio(
	ctx context.Context,
	req *connect.Request[omegav1.GetPortfolioRequest],
) (*connect.Response[omegav1.GetPortfolioResponse], error) {
	p, err := h.vdb.GetPortfolio()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	alloc := make([]*omegav1.VictoriaAllocationSlice, 0, len(p.Allocation))
	for _, a := range p.Allocation {
		alloc = append(alloc, &omegav1.VictoriaAllocationSlice{
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

func (h *VictoriaHandler) GetPositions(
	ctx context.Context,
	req *connect.Request[omegav1.GetPositionsRequest],
) (*connect.Response[omegav1.GetPositionsResponse], error) {
	positions, err := h.vdb.GetPositions()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	protoPos := make([]*omegav1.VictoriaPosition, 0, len(positions))
	for _, p := range positions {
		protoPos = append(protoPos, &omegav1.VictoriaPosition{
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

func (h *VictoriaHandler) GetPnL(
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

func (h *VictoriaHandler) GetSignals(
	ctx context.Context,
	req *connect.Request[omegav1.GetSignalsRequest],
) (*connect.Response[omegav1.GetSignalsResponse], error) {
	signals, err := h.vdb.GetSignals()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	protoSigs := make([]*omegav1.VictoriaSignal, 0, len(signals))
	var totalConviction, totalWeight float64
	for _, s := range signals {
		protoSigs = append(protoSigs, &omegav1.VictoriaSignal{
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

func (h *VictoriaHandler) GetSignalHistory(
	ctx context.Context,
	req *connect.Request[omegav1.GetSignalHistoryRequest],
) (*connect.Response[omegav1.GetSignalHistoryResponse], error) {
	points, err := h.vdb.GetSignalHistory(req.Msg.SignalName, int(req.Msg.Limit))
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	protoPoints := make([]*omegav1.VictoriaSignalICPoint, 0, len(points))
	for _, p := range points {
		protoPoints = append(protoPoints, &omegav1.VictoriaSignalICPoint{
			T:  int32(p.T), //nolint:gosec
			Ic: p.IC,
		})
	}

	return connect.NewResponse(&omegav1.GetSignalHistoryResponse{Points: protoPoints}), nil
}

// ── GetTrades ─────────────────────────────────────────────────────────────────

func (h *VictoriaHandler) GetTrades(
	ctx context.Context,
	req *connect.Request[omegav1.GetTradesRequest],
) (*connect.Response[omegav1.GetTradesResponse], error) {
	trades, err := h.vdb.GetTrades(req.Msg.SymFilter, req.Msg.SideFilter, int(req.Msg.Limit))
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	protoTrades := make([]*omegav1.VictoriaTrade, 0, len(trades))
	for _, t := range trades {
		protoTrades = append(protoTrades, &omegav1.VictoriaTrade{
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

func (h *VictoriaHandler) GetBacktestResults(
	ctx context.Context,
	req *connect.Request[omegav1.GetBacktestResultsRequest],
) (*connect.Response[omegav1.GetBacktestResultsResponse], error) {
	s, err := h.vdb.GetBacktestStats()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&omegav1.GetBacktestResultsResponse{
		Stats: &omegav1.VictoriaBacktestStats{
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

func (h *VictoriaHandler) GetEquityCurve(
	ctx context.Context,
	req *connect.Request[omegav1.GetEquityCurveRequest],
) (*connect.Response[omegav1.GetEquityCurveResponse], error) {
	points, trainEnd, err := h.vdb.GetEquityCurve(int(req.Msg.Limit))
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	protoPoints := make([]*omegav1.VictoriaEquityPoint, 0, len(points))
	for _, p := range points {
		protoPoints = append(protoPoints, &omegav1.VictoriaEquityPoint{
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

func (h *VictoriaHandler) GetRiskMetrics(
	ctx context.Context,
	req *connect.Request[omegav1.GetRiskMetricsRequest],
) (*connect.Response[omegav1.GetRiskMetricsResponse], error) {
	m, err := h.vdb.GetRiskMetrics()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	ablation := make([]*omegav1.VictoriaAblationEntry, 0, len(m.Ablation))
	for _, a := range m.Ablation {
		ablation = append(ablation, &omegav1.VictoriaAblationEntry{
			Name:    a.Name,
			DSharpe: a.DSharpe,
			Sig:     a.Sig,
		})
	}

	regimes := make([]*omegav1.VictoriaRegime, 0, len(m.Regimes))
	for _, r := range m.Regimes {
		regimes = append(regimes, &omegav1.VictoriaRegime{
			Name:   r.Name,
			Sharpe: r.Sharpe,
			Ret:    r.Ret,
			Trades: int32(r.Trades), //nolint:gosec
			Pct:    r.Pct,
		})
	}

	crashes := make([]*omegav1.VictoriaCrashScenario, 0, len(m.Crashes))
	for _, c := range m.Crashes {
		sc := &omegav1.VictoriaCrashScenario{
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

	funding := make([]*omegav1.VictoriaFundingPoint, 0, len(m.FundingData))
	for _, f := range m.FundingData {
		funding = append(funding, &omegav1.VictoriaFundingPoint{
			T:       int32(f.T), //nolint:gosec
			Funding: f.Funding,
			Oi:      f.OI,
		})
	}

	adv := make([]*omegav1.VictoriaAdvPoint, 0, len(m.AdvSeries))
	for _, a := range m.AdvSeries {
		adv = append(adv, &omegav1.VictoriaAdvPoint{
			T:    int32(a.T), //nolint:gosec
			Flag: a.Flag,
			Fp:   a.FP,
		})
	}

	tpe := make([]*omegav1.VictoriaTpePoint, 0, len(m.TpeSeries))
	for _, t := range m.TpeSeries {
		tpe = append(tpe, &omegav1.VictoriaTpePoint{
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
