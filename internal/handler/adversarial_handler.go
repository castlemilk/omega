package handler

import (
	"context"
	"fmt"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/adversarial"
	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/db"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.AdversarialServiceHandler = (*AdversarialHandler)(nil)

// AdversarialHandler implements AdversarialService — adversarial pressure and debate gates.
type AdversarialHandler struct {
	ap         *core.AdversarialPressureV2
	debateGate *adversarial.DebateGate
	riskDebate *adversarial.RiskDebate
	db         *db.DB
}

// NewAdversarial creates an AdversarialHandler with default configurations.
func NewAdversarial(database *db.DB) *AdversarialHandler {
	cfg := core.DefaultAdversarialPressureV2Config()
	ap := core.NewAdversarialPressureV2(cfg)

	bull := &adversarial.BullCaseBuilder{}
	bear := &adversarial.BearCaseBuilder{}
	judge := &adversarial.Judge{}
	dg := adversarial.NewDebateGate(bull, bear, judge)

	rd := adversarial.NewRiskDebate(
		&adversarial.AggressivePersona{},
		&adversarial.ConservativePersona{},
		&adversarial.NeutralPersona{},
	)

	return &AdversarialHandler{
		ap:         ap,
		debateGate: dg,
		riskDebate: rd,
		db:         database,
	}
}

// ── RunPressure ───────────────────────────────────────────────────────────────

func (h *AdversarialHandler) RunPressure(
	ctx context.Context,
	req *connect.Request[omegav1.RunPressureRequest],
) (*connect.Response[omegav1.RunPressureResponse], error) {
	// Convert proto VariantOutputs → map[string]map[string]float64
	variantOutputs := make(map[string]map[string]float64, len(req.Msg.VariantOutputs))
	for k, v := range req.Msg.VariantOutputs {
		if v != nil {
			variantOutputs[k] = v.Metrics
		}
	}

	// Convert StrategyParams (float64 map) → map[string]any
	strategyParams := make(map[string]any, len(req.Msg.StrategyParams))
	for k, v := range req.Msg.StrategyParams {
		strategyParams[k] = v
	}

	report := h.ap.RunV2(
		ctx,
		int(req.Msg.Cycle),
		variantOutputs,
		req.Msg.CurrentSignals,
		strategyParams,
		nil, // fitnessFn — optional
		nil, // strategyCallable — optional
	)

	protoReport := coreReportToProto(req.Msg.Cycle, report)
	return connect.NewResponse(&omegav1.RunPressureResponse{
		Report: protoReport,
	}), nil
}

// ── RunDebate ─────────────────────────────────────────────────────────────────

func (h *AdversarialHandler) RunDebate(
	ctx context.Context,
	req *connect.Request[omegav1.RunDebateRequest],
) (*connect.Response[omegav1.RunDebateResponse], error) {
	if req.Msg.Context == nil {
		return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("signal context is required"))
	}
	sc := protoSignalContextToCore(req.Msg.Context)
	verdict := h.debateGate.Evaluate(sc)
	return connect.NewResponse(&omegav1.RunDebateResponse{
		Verdict: coreVerdictToProto(verdict),
	}), nil
}

// ── ResolveRisk ───────────────────────────────────────────────────────────────

func (h *AdversarialHandler) ResolveRisk(
	ctx context.Context,
	req *connect.Request[omegav1.ResolveRiskRequest],
) (*connect.Response[omegav1.ResolveRiskResponse], error) {
	if req.Msg.Context == nil {
		return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("risk context is required"))
	}
	rc := protoRiskContextToCore(req.Msg.Context)
	result := h.riskDebate.Resolve(rc)
	return connect.NewResponse(&omegav1.ResolveRiskResponse{
		Result: coreRiskResultToProto(result),
	}), nil
}

// ── RecordGateResult ──────────────────────────────────────────────────────────

func (h *AdversarialHandler) RecordGateResult(
	ctx context.Context,
	req *connect.Request[omegav1.RecordGateResultRequest],
) (*connect.Response[omegav1.RecordGateResultResponse], error) {
	passed := req.Msg.Result == "pass" || req.Msg.Result == "PASS"
	_, err := h.db.RecordAdversarialResult(
		req.Msg.Cycle, 2, false,
		0, 1,
		nil,
		map[string]any{
			"gate_name": req.Msg.GateName,
			"result":    req.Msg.Result,
			"details":   req.Msg.Details,
			"passed":    passed,
		},
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordGateResultResponse{Ok: true}), nil
}

// ── GetAdversarialReport ──────────────────────────────────────────────────────

func (h *AdversarialHandler) GetAdversarialReport(
	ctx context.Context,
	req *connect.Request[omegav1.GetAdversarialReportRequest],
) (*connect.Response[omegav1.GetAdversarialReportResponse], error) {
	results, err := h.db.RecentAdversarialResults(100)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	for _, r := range results {
		if r.Cycle == req.Msg.Cycle {
			return connect.NewResponse(&omegav1.GetAdversarialReportResponse{
				Found: true,
				Report: &omegav1.AdversarialReportV2{
					Cycle:          r.Cycle,
					OverallFlagged: r.Severity == "high" || r.Severity == "critical",
					CompletedAt:    timestamppb.New(time.Now()),
				},
			}), nil
		}
	}
	return connect.NewResponse(&omegav1.GetAdversarialReportResponse{Found: false}), nil
}

// ── StreamPressureEvents ──────────────────────────────────────────────────────

func (h *AdversarialHandler) StreamPressureEvents(
	ctx context.Context,
	req *connect.Request[omegav1.StreamPressureEventsRequest],
	stream *connect.ServerStream[omegav1.AdversarialPressureEvent],
) error {
	<-ctx.Done()
	return nil
}

// ── helpers ───────────────────────────────────────────────────────────────────

func coreReportToProto(cycle int64, r core.AdversarialReportV2) *omegav1.AdversarialReportV2 {
	flagged := r.BaseReport.Ring1Result != nil && r.BaseReport.Ring1Result.Flagged
	proto := &omegav1.AdversarialReportV2{
		Cycle:          cycle,
		OverallFlagged: flagged,
		CompletedAt:    timestamppb.Now(),
	}
	if r.DebateVerdict != nil {
		proto.DebateVerdict = coreVerdictToProto(*r.DebateVerdict)
	}
	if r.RiskDebateResult != nil {
		proto.RiskDebate = coreRiskResultToProto(*r.RiskDebateResult)
	}
	return proto
}

func protoSignalContextToCore(p *omegav1.SignalContext) adversarial.SignalContext {
	volRegime := "normal_vol"
	if p.VolRegime > 1.5 {
		volRegime = "high_vol"
	} else if p.VolRegime < 0.5 {
		volRegime = "low_vol"
	}
	return adversarial.SignalContext{
		CompositeSignal: p.CompositeSignal,
		ICShort:         p.IcShort,
		ICLong:          p.IcLong,
		VolRegime:       volRegime,
		RegimeIC:        map[string]float64{volRegime: p.RegimeIc},
		RecentSharpe:    p.RecentSharpe,
		NodeErrorRate:   p.NodeErrorRate,
		ATLDistance:     p.AtlDistance,
		RSI:             p.Rsi,
	}
}

func coreVerdictToProto(v adversarial.DebateVerdict) *omegav1.DebateVerdict {
	dir := omegav1.TradeDirection_TRADE_DIRECTION_HOLD
	switch v.Direction {
	case adversarial.DirectionBuy:
		dir = omegav1.TradeDirection_TRADE_DIRECTION_BUY
	case adversarial.DirectionSell:
		dir = omegav1.TradeDirection_TRADE_DIRECTION_SELL
	}
	return &omegav1.DebateVerdict{
		Direction:     dir,
		Confidence:    v.Confidence,
		PositionScale: v.PositionScale,
	}
}

func protoRiskContextToCore(p *omegav1.RiskContext) adversarial.RiskContext {
	volRegime := "normal_vol"
	if p.CurrentVolatility > 1.5 {
		volRegime = "high_vol"
	} else if p.CurrentVolatility < 0.5 {
		volRegime = "low_vol"
	}
	return adversarial.RiskContext{
		DebateConfidence: p.BasePositionScale,
		MaxDrawdown:      p.PortfolioDrawdown,
		VolRegime:        volRegime,
	}
}

func coreRiskResultToProto(r adversarial.RiskDebateResult) *omegav1.RiskDebateResult {
	verdicts := []*omegav1.PersonaVerdict{
		{
			Persona:          r.AggressiveVerdict.Persona,
			RecommendedScale: r.AggressiveVerdict.RecommendedScale,
			Credibility:      r.AggressiveVerdict.Credibility,
			Rationale:        r.AggressiveVerdict.Reasoning,
		},
		{
			Persona:          r.ConservativeVerdict.Persona,
			RecommendedScale: r.ConservativeVerdict.RecommendedScale,
			Credibility:      r.ConservativeVerdict.Credibility,
			Rationale:        r.ConservativeVerdict.Reasoning,
		},
		{
			Persona:          r.NeutralVerdict.Persona,
			RecommendedScale: r.NeutralVerdict.RecommendedScale,
			Credibility:      r.NeutralVerdict.Credibility,
			Rationale:        r.NeutralVerdict.Reasoning,
		},
	}
	return &omegav1.RiskDebateResult{
		FinalPositionScale: r.PositionScale,
		Verdicts:           verdicts,
		DominantPersona:    r.NeutralVerdict.Persona,
	}
}
