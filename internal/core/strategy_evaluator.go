package core

// strategy_evaluator.go — StrategyEvaluator interface and SimpleEvaluator.
//
// SimpleEvaluator scores two DeterministicStrategies against a set of
// historical episodes by running each strategy's Execute() against every
// episode's content (treated as market data).  Aggregate confidence and
// activity-rate are combined via NashWelfareAggregator into a scalar welfare
// score.  The strategy with higher welfare wins.

// ---------------------------------------------------------------------------
// StrategyEvaluator interface
// ---------------------------------------------------------------------------

// StrategyEvaluator compares a current strategy against a candidate using
// historical episode data and returns the winner plus a signed improvement
// fraction relative to the current strategy's score.
//
//   improvement > 0 → candidate is better
//   improvement < 0 → current is better
//   improvement = 0 → tie (current wins by default)
type StrategyEvaluator interface {
	Evaluate(
		current, candidate *DeterministicStrategy,
		episodes []Episode,
	) (winner *DeterministicStrategy, improvement float64, err error)
}

// ---------------------------------------------------------------------------
// SimpleEvaluator
// ---------------------------------------------------------------------------

// SimpleEvaluator implements StrategyEvaluator using Nash welfare aggregation
// of two objectives: mean signal confidence and signal activity rate.
type SimpleEvaluator struct {
	// objectives passed to NashWelfareAggregator.
	objectives []string
	// disagreement points (floor values) for the Nash product.
	disagreement map[string]float64
}

// NewSimpleEvaluator returns a SimpleEvaluator with default objectives.
func NewSimpleEvaluator() *SimpleEvaluator {
	objectives := []string{"confidence", "activity"}
	disagreement := map[string]float64{"confidence": 0.0, "activity": 0.0}
	return &SimpleEvaluator{objectives: objectives, disagreement: disagreement}
}

// Evaluate runs both strategies against every episode's content and computes
// aggregate metrics.  On empty episodes it returns current unchanged with
// improvement=0.
func (e *SimpleEvaluator) Evaluate(
	current, candidate *DeterministicStrategy,
	episodes []Episode,
) (*DeterministicStrategy, float64, error) {
	if len(episodes) == 0 {
		return current, 0, nil
	}

	currentScore := e.score(current, episodes)
	candidateScore := e.score(candidate, episodes)

	improvement := 0.0
	denominator := currentScore
	if denominator < 1e-9 {
		denominator = 1e-9
	}
	improvement = (candidateScore - currentScore) / denominator

	if candidateScore > currentScore {
		return candidate, improvement, nil
	}
	return current, improvement, nil
}

// score evaluates a strategy against all episodes and returns a scalar welfare
// score computed via NashWelfareAggregator.
func (e *SimpleEvaluator) score(s *DeterministicStrategy, episodes []Episode) float64 {
	if s == nil || len(episodes) == 0 {
		return 0
	}

	var totalConfidence float64
	activeCount := 0

	for _, ep := range episodes {
		if ep.Content == nil {
			continue
		}
		sig := s.Execute(ep.Content)
		if sig.Direction != DirectionFlat {
			totalConfidence += sig.Confidence
			activeCount++
		}
	}

	n := float64(len(episodes))
	meanConfidence := totalConfidence / n
	activityRate := float64(activeCount) / n

	agg := NewNashWelfareAggregator(e.objectives, e.disagreement)
	return agg.Aggregate(map[string]float64{
		"confidence": meanConfidence,
		"activity":   activityRate,
	})
}
