package core

// full_cycle.go — RunFullCycle wires every subsystem into one cohesive
// orchestration loop.
//
// Execution sequence per cycle:
//  1. Pre-cycle health gate (reuses existing Orchestrator.health).
//  2. BeginCycle in MemoryKernel.
//  3. For each active node:
//     a. Circuit breaker gate — skip if open.
//     b. SafetyEnvelope check — record violations; continue execution.
//     c. Execute node.
//     d. Adversarial Ring 1 — ensemble disagreement via variantOutputs.
//     e. Ring 2 / Ring 3 cascade if Ring 1 flagged.
//     f. DebateGate (optional, domain-specific).
//     g. Store episode in memory.
//     h. Update AutonomyManager metrics; request promotion if applicable.
//     i. Record circuit breaker outcome.
//  4. EndCycle in memory.
//  5. Run ImprovementEngine for due nodes.
//  6. Emit CycleCompleted event.
//  7. Return CycleReport.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"

	adversarialpkg "github.com/benebsworth/omega/internal/adversarial"
	omegaerrs "github.com/benebsworth/omega/internal/errors"
	"github.com/benebsworth/omega/internal/observability"
	"github.com/benebsworth/omega/internal/telemetry"
)

// ---------------------------------------------------------------------------
// NodeCycleContext — per-node input for safety / adversarial checks
// ---------------------------------------------------------------------------

// NodeCycleContext holds domain-specific data that the full cycle needs per
// node.  Callers supply this via FullCycleConfig.NodeContextProvider; if that
// is nil, empty defaults are used (safety passes, adversarial stays quiet).
type NodeCycleContext struct {
	// Portfolio is an asset → weight map used by SafetyEnvelope.
	Portfolio map[string]float64
	// Drawdown is the current portfolio drawdown fraction [0, 1].
	Drawdown float64
	// Signals is the current output signal map (ticker → value).
	Signals map[string]float64
	// StrategyParams are the current strategy parameters (for Ring 2 targeting).
	StrategyParams map[string]any
	// VariantOutputs is a variant_id → signal map submitted to Ring 1.
	// If empty, a single synthetic variant is created from Signals.
	VariantOutputs map[string]map[string]float64
	// FitnessFunc is used by Ring 3 tournament evaluation.
	FitnessFunc FitnessFunc
	// SignalCtx is passed to the DebateGate when DomainSupportsDebate is true.
	SignalCtx adversarialpkg.SignalContext
	// DomainSupportsDebate gates whether the DebateGate is invoked for this node.
	DomainSupportsDebate bool
}

// ---------------------------------------------------------------------------
// FullCycleConfig
// ---------------------------------------------------------------------------

// FullCycleConfig wires every subsystem into RunFullCycle.
// All fields are optional; nil means the corresponding step is skipped.
type FullCycleConfig struct {
	// Safety — hard-constraint gate applied before each node execution.
	Safety *SafetyEnvelope

	// AdversarialV2 — enhanced three-rings pressure layer with adaptive threshold,
	// outlier attribution, and FP tracking.  Replaces the old AdversarialPressure field.
	// When set, proposals are rejected (ProposalBlocked=true) if AdversarialScore > 0.4
	// (i.e. ensemble disagreement score < 0.6).
	AdversarialV2 *AdversarialPressureV2

	// Memory — episodic + semantic kernel.
	Memory *MemoryKernel

	// Improvement — self-improvement engine run after all nodes complete.
	Improvement *ImprovementEngine

	// Autonomy — per-node autonomy level tracker.
	Autonomy *AutonomyManager

	// DebateGate — bull/bear quantitative debate (optional).
	// Invoked per node when the NodeCycleContext.DomainSupportsDebate flag is set.
	DebateGate *adversarialpkg.DebateGate

	// NodeContextProvider, when set, is called once per node at the start of
	// its per-node section to supply portfolio / signal data.
	NodeContextProvider func(nodeID string) NodeCycleContext

	// AutonomyPromotionThreshold is the minimum success rate (0–1) needed to
	// request an autonomy promotion.  Default: 0.8.
	AutonomyPromotionThreshold float64
}

// ---------------------------------------------------------------------------
// RunFullCycle
// ---------------------------------------------------------------------------

// RunFullCycle executes one full orchestration cycle with every subsystem
// wired together.  It is safe to call concurrently; each invocation gets its
// own cycle ID.
func (o *Orchestrator) RunFullCycle(ctx context.Context, cfg FullCycleConfig) (*CycleReport, error) {
	if cfg.AutonomyPromotionThreshold == 0 {
		cfg.AutonomyPromotionThreshold = 0.8
	}

	cycleID := o.nextCycleID()
	start := time.Now()

	// Create a parent span for the entire orchestration cycle.
	tracer := telemetry.Tracer()
	spanCtx, cycleSpan := tracer.Start(ctx, telemetry.SpanOrchestratorCycle,
		trace.WithAttributes(telemetry.AttrCycleID.Int64(int64(cycleID))),
	)
	defer cycleSpan.End()

	cycleCtx, cancel := context.WithTimeout(spanCtx, o.cfg.CycleTimeout)
	defer cancel()

	report := &CycleReport{
		CycleID: cycleID,
		PerNode: make(map[string]*PerNodeReport),
	}

	// ── 1. Pre-cycle health gate ──────────────────────────────────────────
	if o.health != nil {
		hCtx, hCancel := context.WithTimeout(cycleCtx, o.cfg.HealthCheckTimeout)
		healthReport := o.health.Check(hCtx)
		hCancel()
		if o.metrics != nil {
			o.metrics.SetHealthScore(healthScoreFromState(healthReport.State))
		}
		if healthReport.State == observability.HealthStateUnhealthy {
			o.logger.Warn("full_cycle: system unhealthy, aborting",
				"cycle_id", cycleID, "state", healthReport.State.String())
			return nil, fmt.Errorf("full cycle %d aborted: system health is %s", cycleID, healthReport.State)
		}
	}

	// ── 2. BeginCycle in memory ───────────────────────────────────────────
	cycleNum := int(cycleID)
	if cfg.Memory != nil {
		if err := cfg.Memory.BeginCycle(cycleCtx, cycleNum); err != nil {
			o.logger.Warn("full_cycle: BeginCycle failed", "cycle_id", cycleID, "err", err)
			// Non-fatal — continue without memory for this cycle.
		}
	}

	// ── 3. Emit CycleStarted ─────────────────────────────────────────────
	activeNodes := o.snapshotActiveNodes()
	nodeIDs := make([]string, 0, len(activeNodes))
	for _, e := range activeNodes {
		nodeIDs = append(nodeIDs, e.executor.NodeID())
	}
	if o.bus != nil {
		o.bus.PublishCycleStarted(observability.CycleStartedPayload{
			Cycle:       cycleID,
			ActiveNodes: nodeIDs,
		})
	}
	o.logger.Info("full_cycle: started", "cycle_id", cycleID, "nodes", len(activeNodes))

	// ── 4. Per-node loop ──────────────────────────────────────────────────
	for _, entry := range activeNodes {
		nodeID := entry.executor.NodeID()
		nr := &PerNodeReport{NodeID: nodeID}
		report.PerNode[nodeID] = nr

		// Fetch per-node context (domain signals, portfolio, etc.).
		var nctx NodeCycleContext
		if cfg.NodeContextProvider != nil {
			nctx = cfg.NodeContextProvider(nodeID)
		}

		// ── 4a. Circuit breaker ───────────────────────────────────────────
		if !o.circuit.AllowExecution(nodeID) {
			nr.Skipped = true
			nr.SkipReason = observability.ErrCircuitOpen.Error()
			nr.ErrorClass = omegaerrs.ErrorClassDependencyFailure
			nr.ErrorCode = "circuit_open"
			nr.IsRetryable = true
			o.logger.Info("full_cycle: node skipped (circuit open)", "node_id", nodeID)
			o.updateNodeState(nodeID, "active", "skipped", "circuit open")
			if o.metrics != nil {
				o.metrics.IncNodeExecution(nodeID, "skipped")
			}
			if cfg.Autonomy != nil {
				cfg.Autonomy.RecordCycleMetrics(nodeID, cycleID, nil, false)
			}
			continue
		}

		// ── 4b. Safety alignment check ────────────────────────────────────
		if cfg.Safety != nil {
			portfolio := nctx.Portfolio
			if portfolio == nil {
				portfolio = map[string]float64{}
			}
			ok, violations := cfg.Safety.Check(portfolio, nctx.Drawdown, nil)
			nr.SafetyPassed = ok
			nr.SafetyViolations = violations
			if !ok {
				for _, v := range violations {
					report.SafetyViolations = append(report.SafetyViolations, fmt.Sprintf("[%s] %s", nodeID, v))
					o.EmitSafetyViolation(nodeID, "safety_envelope", "high", v)
					if o.metrics != nil {
						o.metrics.IncIssue("high", "safety_envelope")
					}
				}
			}
		} else {
			nr.SafetyPassed = true
		}

		// ── 4c. Execute node ──────────────────────────────────────────────
		nodeCtx, nodeCancel := context.WithTimeout(cycleCtx, o.cfg.NodeTimeout)
		nodeStart := time.Now()
		nodeCtx, nodeSpan := tracer.Start(nodeCtx, telemetry.SpanNodeExecution,
			trace.WithAttributes(
				telemetry.AttrNodeName.String(nodeID),
				telemetry.AttrCycleID.Int64(int64(cycleID)),
			),
		)
		execErr := entry.executor.Execute(nodeCtx)
		nr.Duration = time.Since(nodeStart)
		nodeSpan.SetAttributes(attribute.Key("omega.node.duration_ms").Int64(nr.Duration.Milliseconds()))
		if execErr != nil {
			nodeSpan.RecordError(execErr)
			nodeSpan.SetStatus(codes.Error, execErr.Error())
		}
		nodeSpan.End()
		nodeCancel()

		if execErr != nil {
			nr.Executed = false
			nr.ExecutionErr = execErr.Error()
			cls := omegaerrs.Classify(execErr)
			nr.ErrorClass = cls.Class
			nr.ErrorCode = cls.Code
			nr.IsRetryable = cls.Retryable
			o.circuit.RecordFailure(nodeID)
			o.logger.Error("full_cycle: node execution failed",
				"node_id", nodeID, "cycle_id", cycleID, "err", execErr,
				"error_class", cls.Class, "error_code", cls.Code, "retryable", cls.Retryable)
			if o.metrics != nil {
				o.metrics.RecordNodeExecution(nodeID, nr.Duration.Seconds(), false)
				o.metrics.IncNodeExecution(nodeID, "error")
				o.metrics.ObserveNodeDuration(nodeID, nr.Duration.Seconds())
				o.metrics.IncError(nodeID, errorClassName(cls.Class))
			}
		} else {
			nr.Executed = true
			o.circuit.RecordSuccess(nodeID)
			if o.metrics != nil {
				o.metrics.RecordNodeExecution(nodeID, nr.Duration.Seconds(), true)
				o.metrics.IncNodeExecution(nodeID, "success")
				o.metrics.ObserveNodeDuration(nodeID, nr.Duration.Seconds())
			}
		}

		// ── 4d. Adversarial gate (AdversarialPressureV2) ─────────────────
		// AdversarialPressureV2 is always required; production callers must wire it.
		// Proposals (node outputs) are REJECTED (ProposalBlocked=true) when
		// the adversarial score exceeds the quality threshold (disagreement > 0.4,
		// i.e. score = 1 - disagreement < 0.6).
		const adversarialScoreThreshold = 0.4
		if cfg.AdversarialV2 != nil {
			variantOutputs := nctx.VariantOutputs
			if len(variantOutputs) == 0 && len(nctx.Signals) > 0 {
				// Synthesise a single-node variant from node signals so Ring 1
				// has something to inspect even without multi-variant setup.
				variantOutputs = map[string]map[string]float64{nodeID: nctx.Signals}
			}

			adversarialReport := cfg.AdversarialV2.RunV2(
				cycleCtx,
				cycleNum,
				variantOutputs,
				nctx.Signals,
				nctx.StrategyParams,
				nctx.FitnessFunc,
				nil, // strategyCallable — optional Ring 2 simulation
			)

			if adversarialReport.BaseReport.Ring1Result != nil {
				nr.AdversarialFlagged = adversarialReport.BaseReport.Ring1Result.Flagged
				nr.AdversarialScore = adversarialReport.BaseReport.Ring1Result.MaxDisagreement
			}

			// Block proposal when disagreement is too high (score < 0.6).
			if nr.AdversarialScore > adversarialScoreThreshold {
				nr.ProposalBlocked = true
				slog.Warn("full_cycle: proposal blocked by adversarial gate",
					"node_id", nodeID,
					"cycle_id", cycleID,
					"adversarial_score", nr.AdversarialScore,
					"score", 1.0-nr.AdversarialScore,
					"threshold", adversarialScoreThreshold,
				)
			}

			// ── 4e. Ring 2 / Ring 3 cascade ──────────────────────────────
			if nr.AdversarialFlagged {
				nr.Ring2Triggered = len(adversarialReport.BaseReport.Ring2Scenarios) > 0
				nr.Ring3Triggered = adversarialReport.BaseReport.Ring3Result != nil

				if o.metrics != nil {
					o.metrics.IncIssue("medium", "adversarial")
				}
				o.EmitAdversarialAlert(1, nodeID, nr.AdversarialScore,
					cfg.AdversarialV2.Ring1().DisagreementThreshold)

				report.AdversarialAlerts = append(report.AdversarialAlerts, AdversarialAlert{
					NodeID:          nodeID,
					MaxDisagreement: nr.AdversarialScore,
					Ring2Triggered:  nr.Ring2Triggered,
					Ring3Triggered:  nr.Ring3Triggered,
				})
			}
		}

		// ── 4f. DebateGate ────────────────────────────────────────────────
		if cfg.DebateGate != nil && nctx.DomainSupportsDebate {
			verdict := cfg.DebateGate.Evaluate(nctx.SignalCtx)
			nr.DebateVerdict = string(verdict.Direction)
			slog.Debug("full_cycle: debate gate",
				"node_id", nodeID, "verdict", verdict.Direction,
				"confidence", verdict.Confidence)
		}

		// ── 4g. Store episode in memory ───────────────────────────────────
		if cfg.Memory != nil {
			content := map[string]any{
				"cycle":       cycleNum,
				"executed":    nr.Executed,
				"exec_err":    nr.ExecutionErr,
				"safety_ok":   nr.SafetyPassed,
				"adversarial": nr.AdversarialFlagged,
				"debate":      nr.DebateVerdict,
			}
			importance := 0.5
			if !nr.SafetyPassed || nr.AdversarialFlagged {
				importance = 0.9
			} else if nr.Executed {
				importance = 0.7
			}
			if _, err := cfg.Memory.GetNodeMemory(nodeID).StoreEpisode(
				cycleCtx,
				"cycle_execution",
				content,
				[]string{"cycle", "execution"},
				importance,
				cycleNum,
			); err != nil {
				o.logger.Warn("full_cycle: StoreEpisode failed", "node_id", nodeID, "err", err)
			}
		}

		// ── 4h. Autonomy metrics & promotion ─────────────────────────────
		if cfg.Autonomy != nil {
			metrics := map[string]float64{
				"adversarial_score": nr.AdversarialScore,
			}
			if nr.Duration > 0 {
				metrics["execution_latency_ms"] = float64(nr.Duration.Milliseconds())
			}
			cfg.Autonomy.RecordCycleMetrics(nodeID, cycleID, metrics, nr.Executed)

			// Request promotion when node has been running cleanly.
			state := cfg.Autonomy.GetLevel(nodeID)
			if state != nil {
				nr.AutonomyLevel = state.Level
				if nr.Executed && !nr.AdversarialFlagged && nr.SkipReason == "" {
					successRate := float64(state.CyclesAtLevel) / float64(state.CyclesAtLevel+1)
					if successRate >= cfg.AutonomyPromotionThreshold && state.Level < AutonomyLevelFull {
						result := cfg.Autonomy.RequestPromotion(
							cycleCtx, nodeID,
							state.Level+1,
							metrics,
							cycleID,
						)
						if result.Approved {
							cfg.Autonomy.RecordPromotion(nodeID, state.Level, result.GrantedLevel, "full_cycle_auto", cycleID)
							o.PromoteNode(nodeID, float64(state.Level), float64(result.GrantedLevel))
							report.AutonomyChanges = append(report.AutonomyChanges, AutonomyChange{
								NodeID:    nodeID,
								FromLevel: state.Level,
								ToLevel:   result.GrantedLevel,
								Reason:    "auto_promotion",
							})
						}
					}
				}
			}
		}
	}

	// ── 5. EndCycle in memory ─────────────────────────────────────────────
	if cfg.Memory != nil {
		passed, failed, skipped := 0, 0, 0
		for _, nr := range report.PerNode {
			switch {
			case nr.Skipped:
				skipped++
			case nr.Executed:
				passed++
			default:
				failed++
			}
		}
		summary := map[string]any{
			"cycle_id":  cycleID,
			"total":     len(report.PerNode),
			"passed":    passed,
			"failed":    failed,
			"skipped":   skipped,
			"safety_violations": len(report.SafetyViolations),
			"adversarial_alerts": len(report.AdversarialAlerts),
		}
		if _, err := cfg.Memory.EndCycle(cycleCtx, cycleNum, summary); err != nil {
			o.logger.Warn("full_cycle: EndCycle failed", "cycle_id", cycleID, "err", err)
		}
	}

	// ── 6. Improvement engine ─────────────────────────────────────────────
	if cfg.Improvement != nil {
		if err := cfg.Improvement.RunImprovementCycle(cycleCtx); err != nil {
			o.logger.Warn("full_cycle: improvement cycle error", "cycle_id", cycleID, "err", err)
		}
	}

	// ── 7. Build summary ──────────────────────────────────────────────────
	duration := time.Since(start)
	passed, failed, skipped := 0, 0, 0
	for _, nr := range report.PerNode {
		switch {
		case nr.Skipped:
			skipped++
		case nr.Executed:
			passed++
		default:
			failed++
		}
	}
	report.Summary = CycleSummary{
		TotalNodes: len(activeNodes),
		Passed:     passed,
		Failed:     failed,
		Skipped:    skipped,
		Duration:   duration,
	}

	// ── 8. Emit CycleCompleted ────────────────────────────────────────────
	if o.bus != nil {
		o.bus.PublishCycleCompleted(observability.CycleCompletedPayload{
			Cycle:        cycleID,
			DurationSecs: duration.Seconds(),
			NodeCount:    len(activeNodes),
			Success:      failed == 0,
			ErrorText:    fmt.Sprintf("%d node(s) failed", failed),
		})
	}
	if o.metrics != nil {
		status := "success"
		if failed > 0 {
			status = "error"
		}
		o.metrics.RecordCycle(duration.Seconds(), status)
		o.metrics.IncCycles()
	}

	o.logger.Info("full_cycle: completed",
		"cycle_id", cycleID,
		"duration_ms", duration.Milliseconds(),
		"passed", passed,
		"failed", failed,
		"skipped", skipped,
		"safety_violations", len(report.SafetyViolations),
		"adversarial_alerts", len(report.AdversarialAlerts),
	)

	return report, nil
}

// healthScoreFromState converts a HealthState to a numeric score (0–100).
func healthScoreFromState(state observability.HealthState) float64 {
	switch state {
	case observability.HealthStateHealthy:
		return 100
	case observability.HealthStateDegraded:
		return 50
	default:
		return 0
	}
}

// errorClassName returns a readable string label for a given ErrorClass.
func errorClassName(cls omegaerrs.ErrorClass) string {
	switch cls {
	case omegaerrs.ErrorClassTimeout:
		return "timeout"
	case omegaerrs.ErrorClassDataQuality:
		return "data_quality"
	case omegaerrs.ErrorClassDependencyFailure:
		return "dependency_failure"
	case omegaerrs.ErrorClassResourceExhaustion:
		return "resource_exhaustion"
	case omegaerrs.ErrorClassValidationError:
		return "validation_error"
	case omegaerrs.ErrorClassLLMError:
		return "llm_error"
	default:
		return "unknown"
	}
}
