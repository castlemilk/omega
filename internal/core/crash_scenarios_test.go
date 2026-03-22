package core

import (
	"math"
	"testing"
)

// ---------------------------------------------------------------------------
// CrashScenarioProvider
// ---------------------------------------------------------------------------

func TestCrashScenarioProvider_Loads4Profiles(t *testing.T) {
	p := NewCrashScenarioProvider()
	if p.Len() != 4 {
		t.Errorf("expected 4 crash profiles, got %d", p.Len())
	}
}

func TestCrashScenarioProvider_AllSortedBySeverity(t *testing.T) {
	p := NewCrashScenarioProvider()
	all := p.All()
	for i := 1; i < len(all); i++ {
		if all[i].Severity > all[i-1].Severity {
			t.Errorf("profiles not sorted by severity: index %d (%.2f) > index %d (%.2f)",
				i, all[i].Severity, i-1, all[i-1].Severity)
		}
	}
}

func TestCrashScenarioProvider_Get(t *testing.T) {
	p := NewCrashScenarioProvider()
	ids := []string{"crash_2020_covid", "crash_2022_luna", "crash_2022_ftx", "crash_2021_may"}
	for _, id := range ids {
		cp, ok := p.Get(id)
		if !ok {
			t.Errorf("expected to find profile %q", id)
			continue
		}
		if cp.ID != id {
			t.Errorf("profile ID mismatch: got %q, want %q", cp.ID, id)
		}
	}
}

func TestCrashScenarioProvider_GetByTag(t *testing.T) {
	p := NewCrashScenarioProvider()
	crashes := p.GetByTag("crash")
	if len(crashes) == 0 {
		t.Error("expected at least one profile with tag 'crash'")
	}
	for _, cp := range crashes {
		found := false
		for _, tag := range cp.Tags {
			if tag == "crash" {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("profile %s returned by GetByTag('crash') but doesn't have tag 'crash'", cp.ID)
		}
	}
}

func TestCrashScenarioProvider_PriceSeriesLength(t *testing.T) {
	p := NewCrashScenarioProvider()
	for _, cp := range p.All() {
		for asset, series := range cp.PriceSeries {
			if len(series) != cp.DurationBars {
				t.Errorf("%s/%s: expected %d bars, got %d",
					cp.ID, asset, cp.DurationBars, len(series))
			}
		}
	}
}

func TestCrashScenarioProvider_AllPricesPositive(t *testing.T) {
	p := NewCrashScenarioProvider()
	for _, cp := range p.All() {
		for asset, series := range cp.PriceSeries {
			for i, bar := range series {
				if bar.Open <= 0 || bar.High <= 0 || bar.Low <= 0 || bar.Close <= 0 {
					t.Errorf("%s/%s bar %d: non-positive OHLC (O=%.8f H=%.8f L=%.8f C=%.8f)",
						cp.ID, asset, i, bar.Open, bar.High, bar.Low, bar.Close)
				}
				if bar.High < bar.Low {
					t.Errorf("%s/%s bar %d: High %.8f < Low %.8f",
						cp.ID, asset, i, bar.High, bar.Low)
				}
				if bar.Volume <= 0 {
					t.Errorf("%s/%s bar %d: non-positive volume %.6f",
						cp.ID, asset, i, bar.Volume)
				}
			}
		}
	}
}

func TestCrashScenarioProvider_SpreadMultiplier10x(t *testing.T) {
	p := NewCrashScenarioProvider()
	for _, cp := range p.All() {
		if cp.Liquidity.SpreadMultiplier < 10 {
			t.Errorf("%s: spread multiplier %.1fx < required 10x minimum",
				cp.ID, cp.Liquidity.SpreadMultiplier)
		}
	}
}

func TestCrashScenarioProvider_CrashCorrHigherThanNormal(t *testing.T) {
	p := NewCrashScenarioProvider()
	for _, cp := range p.All() {
		for a, peerMap := range cp.NormalCorr {
			for b, normalCorr := range peerMap {
				crashCorr, ok := cp.CrashCorr[a][b]
				if !ok {
					t.Errorf("%s: crash corr missing for %s→%s", cp.ID, a, b)
					continue
				}
				if crashCorr < normalCorr {
					t.Errorf("%s: crash corr %s→%s (%.2f) < normal (%.2f)",
						cp.ID, a, b, crashCorr, normalCorr)
				}
			}
		}
	}
}

func TestCrashScenarioProvider_PeakDrawdownNegative(t *testing.T) {
	p := NewCrashScenarioProvider()
	for _, cp := range p.All() {
		for asset, dd := range cp.PeakDrawdown {
			if dd >= 0 {
				t.Errorf("%s/%s: peak drawdown %.4f should be negative", cp.ID, asset, dd)
			}
		}
	}
}

func TestCrashScenarioProvider_LUNACrashExtreme(t *testing.T) {
	p := NewCrashScenarioProvider()
	luna, ok := p.Get("crash_2022_luna")
	if !ok {
		t.Fatal("expected crash_2022_luna profile")
	}
	// LUNA should lose >99% of its value.
	dd := luna.PeakDrawdown["LUNAUSDT"]
	if dd > -0.99 {
		t.Errorf("LUNA drawdown %.4f should be worse than -0.99 (actual was -99.9%%)", dd)
	}
	// Duration should be 144 bars (6 days × 24h).
	if luna.DurationBars != 144 {
		t.Errorf("LUNA crash: expected 144 bars, got %d", luna.DurationBars)
	}
}

func TestCrashScenarioProvider_COVIDCrashFast(t *testing.T) {
	p := NewCrashScenarioProvider()
	covid, ok := p.Get("crash_2020_covid")
	if !ok {
		t.Fatal("expected crash_2020_covid profile")
	}
	// COVID crash was 48 bars (2 days).
	if covid.DurationBars != 48 {
		t.Errorf("COVID crash: expected 48 bars, got %d", covid.DurationBars)
	}
	// COVID crash should be the highest severity after LUNA.
	if covid.Severity < 0.90 {
		t.Errorf("COVID crash severity %.2f should be >= 0.90", covid.Severity)
	}
}

func TestCrashScenarioProvider_May2021Sustained(t *testing.T) {
	p := NewCrashScenarioProvider()
	may, ok := p.Get("crash_2021_may")
	if !ok {
		t.Fatal("expected crash_2021_may profile")
	}
	// 14-day crash = 336 bars.
	if may.DurationBars != 336 {
		t.Errorf("May 2021 crash: expected 336 bars, got %d", may.DurationBars)
	}
}

func TestCrashScenarioProvider_ToScenarios(t *testing.T) {
	p := NewCrashScenarioProvider()
	scenarios := p.ToScenarios()
	if len(scenarios) != p.Len() {
		t.Errorf("ToScenarios: expected %d, got %d", p.Len(), len(scenarios))
	}
	for _, s := range scenarios {
		if s.ScenarioID == "" {
			t.Error("ToScenarios: empty scenario ID")
		}
		if s.Severity < 0 || s.Severity > 1 {
			t.Errorf("ToScenarios: severity %.3f out of [0,1] for %s", s.Severity, s.ScenarioID)
		}
		if !s.CorrelationBreakdown {
			t.Errorf("ToScenarios: %s should have CorrelationBreakdown=true", s.ScenarioID)
		}
	}
}

// ---------------------------------------------------------------------------
// Price series determinism
// ---------------------------------------------------------------------------

func TestCrashScenarioProvider_Deterministic(t *testing.T) {
	// Two providers built independently must produce identical price series.
	p1 := NewCrashScenarioProvider()
	p2 := NewCrashScenarioProvider()
	covid1, _ := p1.Get("crash_2020_covid")
	covid2, _ := p2.Get("crash_2020_covid")
	s1 := covid1.PriceSeries["BTCUSDT"]
	s2 := covid2.PriceSeries["BTCUSDT"]
	if len(s1) != len(s2) {
		t.Fatalf("determinism: different series lengths %d vs %d", len(s1), len(s2))
	}
	for i, bar := range s1 {
		if math.Abs(bar.Close-s2[i].Close) > 1e-9 {
			t.Errorf("determinism: bar %d close differs: %.10f vs %.10f", i, bar.Close, s2[i].Close)
		}
	}
}

// ---------------------------------------------------------------------------
// StressTestRunner
// ---------------------------------------------------------------------------

func TestStressTestRunner_RunBuyAndHold(t *testing.T) {
	p := NewCrashScenarioProvider()
	r := NewStressTestRunner(p)
	report := r.Run(nil) // nil = equal-weight long (buy-and-hold)

	if len(report.Metrics) != p.Len() {
		t.Errorf("expected %d metric records, got %d", p.Len(), len(report.Metrics))
	}
	for _, m := range report.Metrics {
		if math.IsNaN(m.Sharpe) || math.IsInf(m.Sharpe, 0) {
			t.Errorf("%s: Sharpe is NaN or Inf", m.ScenarioID)
		}
		if m.MaxDrawdown > 0 {
			t.Errorf("%s: max drawdown %.4f should be negative in a crash", m.ScenarioID, m.MaxDrawdown)
		}
		if m.CVaR99 > 0 {
			t.Errorf("%s: CVaR99 %.6f should be negative (tail losses)", m.ScenarioID, m.CVaR99)
		}
		if len(m.BarReturns) == 0 {
			t.Errorf("%s: expected non-empty BarReturns", m.ScenarioID)
		}
	}
}

func TestStressTestRunner_ByScenarioIndex(t *testing.T) {
	p := NewCrashScenarioProvider()
	r := NewStressTestRunner(p)
	report := r.Run(nil)

	ids := []string{"crash_2020_covid", "crash_2022_luna", "crash_2022_ftx", "crash_2021_may"}
	for _, id := range ids {
		if _, ok := report.ByScenario[id]; !ok {
			t.Errorf("expected ByScenario[%q] to exist", id)
		}
	}
}

func TestStressTestRunner_ByTagIndex(t *testing.T) {
	p := NewCrashScenarioProvider()
	r := NewStressTestRunner(p)
	report := r.Run(nil)

	// Every crash profile has the "crash" tag; ByTag["crash"] should be populated.
	crashTag, ok := report.ByTag["crash"]
	if !ok || len(crashTag) == 0 {
		t.Error("expected ByTag['crash'] to be populated")
	}
}

func TestStressTestRunner_WorstExtremes(t *testing.T) {
	p := NewCrashScenarioProvider()
	r := NewStressTestRunner(p)
	report := r.Run(nil)

	if report.WorstSharpe == nil {
		t.Error("expected WorstSharpe to be set")
	}
	if report.WorstDrawdown == nil {
		t.Error("expected WorstDrawdown to be set")
	}
	if report.WorstCVaR == nil {
		t.Error("expected WorstCVaR to be set")
	}
	// WorstSharpe should have the lowest Sharpe of all metrics.
	for _, m := range report.Metrics {
		if m.Sharpe < report.WorstSharpe.Sharpe-1e-9 {
			t.Errorf("WorstSharpe %.4f is not actually worst (%.4f is lower)",
				report.WorstSharpe.Sharpe, m.Sharpe)
		}
	}
}

func TestStressTestRunner_ShortStrategyBeatsLongInCrash(t *testing.T) {
	// A fully short strategy should have better (higher) Sharpe than buy-and-hold
	// across crash scenarios, since all crashes are predominantly downward.
	shortAll := func(_ int, closes map[string]float64) map[string]float64 {
		w := -1.0 / float64(len(closes))
		weights := make(map[string]float64, len(closes))
		for asset := range closes {
			weights[asset] = w
		}
		return weights
	}

	p := NewCrashScenarioProvider()
	r := NewStressTestRunner(p)

	longReport := r.Run(nil)
	shortReport := r.Run(shortAll)

	var longAvg, shortAvg float64
	for i := range longReport.Metrics {
		longAvg += longReport.Metrics[i].Sharpe
		shortAvg += shortReport.Metrics[i].Sharpe
	}
	n := float64(len(longReport.Metrics))
	longAvg /= n
	shortAvg /= n

	if shortAvg <= longAvg {
		t.Errorf("short avg Sharpe %.4f should beat long avg Sharpe %.4f in crash scenarios",
			shortAvg, longAvg)
	}
}

func TestStressTestRunner_FlatStrategyZeroDrawdown(t *testing.T) {
	// A strategy that takes no positions should have zero drawdown.
	flat := func(_ int, _ map[string]float64) map[string]float64 { return nil }

	p := NewCrashScenarioProvider()
	r := NewStressTestRunner(p)
	report := r.Run(flat)

	for _, m := range report.Metrics {
		if math.Abs(m.MaxDrawdown) > 1e-10 {
			t.Errorf("%s: flat strategy max drawdown should be 0, got %.8f",
				m.ScenarioID, m.MaxDrawdown)
		}
	}
}

// ---------------------------------------------------------------------------
// Individual metric helpers
// ---------------------------------------------------------------------------

func TestCrashSharpe_FlatReturns(t *testing.T) {
	flat := make([]float64, 100)
	if s := crashSharpe(flat); s != 0 {
		t.Errorf("crashSharpe of flat returns: expected 0, got %.6f", s)
	}
}

func TestCrashSharpe_Empty(t *testing.T) {
	if s := crashSharpe(nil); s != 0 {
		t.Errorf("crashSharpe of empty slice: expected 0, got %.6f", s)
	}
}

func TestCrashMaxDrawdown_FlatReturns(t *testing.T) {
	flat := make([]float64, 50)
	if dd := crashMaxDrawdown(flat); dd != 0 {
		t.Errorf("crashMaxDrawdown of flat returns: expected 0, got %.6f", dd)
	}
}

func TestCrashMaxDrawdown_Declining(t *testing.T) {
	// -5% per bar for 10 bars: equity = 0.95^10
	declining := make([]float64, 10)
	for i := range declining {
		declining[i] = -0.05
	}
	dd := crashMaxDrawdown(declining)
	expected := math.Pow(0.95, 10) - 1.0
	if math.Abs(dd-expected) > 1e-9 {
		t.Errorf("crashMaxDrawdown declining: expected %.8f, got %.8f", expected, dd)
	}
}

func TestCrashMaxDrawdown_Recovery(t *testing.T) {
	// Falls then recovers above start: drawdown should still reflect the trough.
	returns := []float64{-0.10, -0.10, 0.20, 0.20}
	dd := crashMaxDrawdown(returns)
	if dd >= 0 {
		t.Errorf("crashMaxDrawdown with recovery: expected negative, got %.6f", dd)
	}
}

func TestCrashTimeToRecovery_NeverRecovers(t *testing.T) {
	declining := make([]float64, 20)
	for i := range declining {
		declining[i] = -0.01
	}
	if ttr := crashTimeToRecovery(declining); ttr != -1 {
		t.Errorf("crashTimeToRecovery never recovers: expected -1, got %d", ttr)
	}
}

func TestCrashTimeToRecovery_Recovers(t *testing.T) {
	// Down then up: recovers at bar 2 (after the +11% return).
	returns := []float64{-0.10, 0.12}
	ttr := crashTimeToRecovery(returns)
	if ttr != 2 {
		t.Errorf("crashTimeToRecovery: expected 2, got %d", ttr)
	}
}

func TestCrashCVaR_NegativeForCrash(t *testing.T) {
	// Mix of mostly small positives with a few large negatives.
	returns := make([]float64, 100)
	for i := range returns {
		returns[i] = 0.001
	}
	returns[0] = -0.10
	returns[1] = -0.08
	cvar := crashCVaR(returns, 0.99)
	if cvar > 0 {
		t.Errorf("crashCVaR should be negative for series with tail losses, got %.6f", cvar)
	}
}

func TestCrashCVaR_Empty(t *testing.T) {
	if c := crashCVaR(nil, 0.99); c != 0 {
		t.Errorf("crashCVaR of empty slice: expected 0, got %.6f", c)
	}
}

func TestCrashCVaR_SingleElement(t *testing.T) {
	returns := []float64{-0.05}
	cvar := crashCVaR(returns, 0.99)
	if math.Abs(cvar - (-0.05)) > 1e-9 {
		t.Errorf("crashCVaR single element: expected -0.05, got %.8f", cvar)
	}
}

// ---------------------------------------------------------------------------
// Bootstrap resampling
// ---------------------------------------------------------------------------

func TestBootstrapCrashScenarios_Count(t *testing.T) {
	p := NewCrashScenarioProvider()
	covid, _ := p.Get("crash_2020_covid")
	bs := BootstrapCrashScenarios(covid, 5, 24, 42)
	if len(bs) != 5 {
		t.Errorf("expected 5 bootstrapped scenarios, got %d", len(bs))
	}
}

func TestBootstrapCrashScenarios_SeriesLength(t *testing.T) {
	p := NewCrashScenarioProvider()
	covid, _ := p.Get("crash_2020_covid")
	bs := BootstrapCrashScenarios(covid, 3, 24, 42)
	for i, b := range bs {
		for asset, series := range b.PriceSeries {
			if len(series) != covid.DurationBars {
				t.Errorf("bootstrap %d/%s: expected %d bars, got %d",
					i, asset, covid.DurationBars, len(series))
			}
		}
	}
}

func TestBootstrapCrashScenarios_PricesPositive(t *testing.T) {
	p := NewCrashScenarioProvider()
	luna, _ := p.Get("crash_2022_luna")
	bs := BootstrapCrashScenarios(luna, 2, 12, 99)
	for i, b := range bs {
		for asset, series := range b.PriceSeries {
			for j, bar := range series {
				if bar.Open <= 0 || bar.Close <= 0 || bar.High <= 0 || bar.Low <= 0 {
					t.Errorf("bootstrap %d/%s bar %d: non-positive price", i, asset, j)
				}
			}
		}
	}
}

func TestBootstrapCrashScenarios_UniqueIDs(t *testing.T) {
	p := NewCrashScenarioProvider()
	ftx, _ := p.Get("crash_2022_ftx")
	bs := BootstrapCrashScenarios(ftx, 4, 24, 7)
	seen := make(map[string]bool)
	for _, b := range bs {
		if seen[b.ID] {
			t.Errorf("duplicate bootstrap ID: %s", b.ID)
		}
		seen[b.ID] = true
	}
}

func TestBootstrapCrashScenarios_HasBootstrapTag(t *testing.T) {
	p := NewCrashScenarioProvider()
	may, _ := p.Get("crash_2021_may")
	bs := BootstrapCrashScenarios(may, 2, 24, 1)
	for _, b := range bs {
		found := false
		for _, tag := range b.Tags {
			if tag == "bootstrap" {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("bootstrap scenario %s missing 'bootstrap' tag", b.ID)
		}
	}
}

func TestBootstrapCrashScenarios_DefaultBlockSize(t *testing.T) {
	// blockSize=0 should default to 24.
	p := NewCrashScenarioProvider()
	covid, _ := p.Get("crash_2020_covid")
	bs := BootstrapCrashScenarios(covid, 2, 0, 42)
	for _, b := range bs {
		for asset, series := range b.PriceSeries {
			if len(series) != covid.DurationBars {
				t.Errorf("default blockSize/%s: expected %d bars, got %d",
					asset, covid.DurationBars, len(series))
			}
		}
	}
}

func TestBootstrapCrashScenarios_RunThroughStressRunner(t *testing.T) {
	// Bootstrap scenarios should be usable with StressTestRunner via ToScenarios.
	p := NewCrashScenarioProvider()
	covid, _ := p.Get("crash_2020_covid")
	bs := BootstrapCrashScenarios(covid, 3, 24, 123)

	// Build a mini provider with just the bootstrapped scenarios.
	mini := &CrashScenarioProvider{profiles: make(map[string]CrashProfile)}
	for _, b := range bs {
		mini.profiles[b.ID] = b
	}

	runner := NewStressTestRunner(mini)
	report := runner.Run(nil)

	if len(report.Metrics) != len(bs) {
		t.Errorf("expected %d stress metrics from bootstrapped scenarios, got %d",
			len(bs), len(report.Metrics))
	}
	for _, m := range report.Metrics {
		if math.IsNaN(m.Sharpe) || math.IsInf(m.Sharpe, 0) {
			t.Errorf("bootstrap StressMetrics %s: Sharpe is NaN/Inf", m.ScenarioID)
		}
	}
}

// ---------------------------------------------------------------------------
// Integration: crash profiles feed into existing ScenarioRunner
// ---------------------------------------------------------------------------

func TestCrashProfiles_CompatibleWithExistingScenarioRunner(t *testing.T) {
	p := NewCrashScenarioProvider()
	scenarios := p.ToScenarios()

	strategy := StrategyCallable(func(signals map[string]float64, _ Scenario) map[string]float64 {
		out := make(map[string]float64, len(signals))
		for k, v := range signals {
			out[k] = v * 0.5
		}
		return out
	})

	runner := NewScenarioRunner(strategy, nil, 0.20, 42, true)
	baseSignals := map[string]float64{
		"BTCUSDT": 0.6,
		"ETHUSDT": 0.5,
		"SOLUSDT": 0.4,
		"FTTUSDT": 0.3,
		"LUNAUSDT": 0.2,
		"BNBUSDT": 0.5,
		"ADAUSDT": 0.4,
		"USTUSDT": 0.1,
	}

	results := runner.Run(t.Context(), scenarios, baseSignals)
	if len(results) != len(scenarios) {
		t.Errorf("expected %d run results, got %d", len(scenarios), len(results))
	}
	for _, rr := range results {
		if rr.ResilienceScore < 0 || rr.ResilienceScore > 1 {
			t.Errorf("scenario %s: resilience %.4f out of [0,1]", rr.ScenarioID, rr.ResilienceScore)
		}
	}
}
