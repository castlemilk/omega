"""tests.test_crash_replay — CrashReplayRunner and scenario tests."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _minimal_scenario(
    name: str = "test_crash",
    price_mults: list[float] | None = None,
    vol_mults: list[float] | None = None,
):
    from omega.eval.crash_replay import CrashScenario

    price_mults = price_mults or [1.0, 0.9, 0.8, 0.85, 0.90]
    vol_mults = vol_mults or [1.0] * len(price_mults)
    return CrashScenario(
        name=name,
        symbol="BTCUSDT",
        date_range=("2024-01-01", "2024-01-05"),
        description="Test scenario",
        price_multipliers=price_mults,
        volume_multipliers=vol_mults,
    )


# ---------------------------------------------------------------------------
# CrashScenario shape validation
# ---------------------------------------------------------------------------


class TestCrashScenarios:
    def test_all_scenarios_importable(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS

        assert len(CRASH_SCENARIOS) >= 5

    def test_scenario_price_and_volume_lengths_match(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS

        for s in CRASH_SCENARIOS:
            assert len(s.price_multipliers) == len(s.volume_multipliers), (
                f"{s.name}: price and volume multiplier lengths differ"
            )

    def test_scenario_price_multipliers_start_at_one(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS

        for s in CRASH_SCENARIOS:
            assert s.price_multipliers[0] == pytest.approx(1.0), (
                f"{s.name}: first price multiplier should be 1.0"
            )

    def test_covid_crash_has_large_drop(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS

        covid = next(s for s in CRASH_SCENARIOS if "COVID" in s.name)
        min_mult = min(covid.price_multipliers)
        assert min_mult <= 0.55, "COVID crash should drop at least 45%"

    def test_luna_collapse_near_zero(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS

        luna = next(s for s in CRASH_SCENARIOS if "LUNA" in s.name)
        min_mult = min(luna.price_multipliers)
        assert min_mult <= 0.01, "LUNA should collapse to near-zero"

    def test_ftx_collapse_has_25pct_drop(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS

        ftx = next(s for s in CRASH_SCENARIOS if "FTX" in s.name)
        min_mult = min(ftx.price_multipliers)
        assert min_mult <= 0.76, "FTX collapse should drop at least 24%"

    def test_flash_crash_has_high_volume_bar(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS

        flash = next(s for s in CRASH_SCENARIOS if "Flash" in s.name)
        assert max(flash.volume_multipliers) >= 5.0, "Flash crash should have high-volume spike"


# ---------------------------------------------------------------------------
# CrashReplayRunner — core mechanics
# ---------------------------------------------------------------------------


class TestCrashReplayRunner:
    def test_run_returns_report(self):
        from omega.eval.crash_replay import CrashReplayRunner

        runner = CrashReplayRunner()
        scenario = _minimal_scenario()
        report = runner.run(scenario, start_price=10_000.0)
        assert report is not None
        assert report.scenario_name == "test_crash"

    def test_report_has_expected_fields(self):
        from omega.eval.crash_replay import CrashReplayRunner

        runner = CrashReplayRunner()
        report = runner.run(_minimal_scenario(), start_price=1_000.0)
        assert isinstance(report.max_drawdown_pct, float)
        assert isinstance(report.stop_losses_fired, int)
        assert isinstance(report.total_pnl_pct, float)
        assert isinstance(report.passed, bool)
        assert isinstance(report.bar_pnls, list)

    def test_max_drawdown_computed_correctly(self):
        from omega.eval.crash_replay import CrashReplayRunner

        # Prices go 1.0 → 0.5 → 0.8 — peak-to-trough is 50%
        scenario = _minimal_scenario(price_mults=[1.0, 0.5, 0.8])
        runner = CrashReplayRunner(max_dd_fail_threshold=0.60)  # won't fail
        report = runner.run(scenario, start_price=1_000.0)
        assert report.max_drawdown_pct == pytest.approx(0.50, abs=0.01)

    def test_fail_when_drawdown_exceeds_threshold(self):
        from omega.eval.crash_replay import CrashReplayRunner

        # -60% drop, threshold=0.30 → should FAIL
        scenario = _minimal_scenario(price_mults=[1.0, 0.4, 0.5])
        runner = CrashReplayRunner(max_dd_fail_threshold=0.30)
        report = runner.run(scenario)
        assert report.passed is False
        assert len(report.failure_reasons) > 0

    def test_pass_when_drawdown_within_threshold(self):
        from omega.eval.crash_replay import CrashReplayRunner

        # -10% drop, threshold=0.30 → should PASS
        scenario = _minimal_scenario(price_mults=[1.0, 0.90, 0.92, 0.95])
        runner = CrashReplayRunner(max_dd_fail_threshold=0.30)
        report = runner.run(scenario)
        assert report.passed is True
        assert report.failure_reasons == []

    def test_stop_loss_fires_on_large_drop(self):
        from omega.eval.crash_replay import CrashReplayRunner

        # Enter at bar 1 (0.95), then price drops to 0.75 at bar 2 — 21% below entry → fires
        scenario = _minimal_scenario(price_mults=[1.0, 0.95, 0.75])
        runner = CrashReplayRunner(stop_loss_pct=0.15)
        report = runner.run(scenario)
        assert report.stop_losses_fired >= 1

    def test_stop_loss_does_not_fire_on_small_drop(self):
        from omega.eval.crash_replay import CrashReplayRunner

        # Drop of 5% total; stop_loss_pct=0.15 → should not fire
        scenario = _minimal_scenario(price_mults=[1.0, 0.97, 0.95, 0.96])
        runner = CrashReplayRunner(stop_loss_pct=0.15)
        report = runner.run(scenario)
        assert report.stop_losses_fired == 0

    def test_recovery_time_computed_when_price_recovers(self):
        from omega.eval.crash_replay import CrashReplayRunner

        # Drops then fully recovers
        scenario = _minimal_scenario(price_mults=[1.0, 0.80, 0.90, 1.00, 1.05])
        runner = CrashReplayRunner(max_dd_fail_threshold=0.99)
        report = runner.run(scenario)
        assert report.recovery_time_bars is not None
        assert report.recovery_time_bars > 0

    def test_recovery_time_none_when_no_recovery(self):
        from omega.eval.crash_replay import CrashReplayRunner

        # Steady decline, never recovers
        scenario = _minimal_scenario(price_mults=[1.0, 0.9, 0.8, 0.7, 0.6])
        runner = CrashReplayRunner(max_dd_fail_threshold=0.99)
        report = runner.run(scenario)
        assert report.recovery_time_bars is None

    def test_bar_pnls_length_matches_bars(self):
        from omega.eval.crash_replay import CrashReplayRunner

        mults = [1.0, 0.9, 0.85, 0.88, 0.92]
        scenario = _minimal_scenario(price_mults=mults)
        runner = CrashReplayRunner()
        report = runner.run(scenario)
        assert len(report.bar_pnls) == len(mults)

    def test_custom_strategy_fn_called(self):
        from omega.eval.crash_replay import CrashReplayRunner

        calls = []

        def flat_strategy(bar_idx, price, volume, position):
            calls.append(bar_idx)
            return 0.0  # always flat (never hold)

        scenario = _minimal_scenario(price_mults=[1.0, 0.9, 0.8, 0.85])
        runner = CrashReplayRunner(strategy_fn=flat_strategy)
        report = runner.run(scenario)
        assert len(calls) > 0
        # With flat strategy (no position), PnL should be ~0
        assert report.total_pnl_pct == pytest.approx(0.0, abs=1e-9)

    def test_start_price_scales_prices(self):
        from omega.eval.crash_replay import CrashReplayRunner

        scenario = _minimal_scenario(price_mults=[1.0, 0.9])
        runner = CrashReplayRunner(max_dd_fail_threshold=0.99)

        r1 = runner.run(scenario, start_price=1_000.0)
        r2 = runner.run(scenario, start_price=50_000.0)

        assert r1.start_price == pytest.approx(1_000.0)
        assert r2.start_price == pytest.approx(50_000.0)
        # Drawdown should be same regardless of start price
        assert r1.max_drawdown_pct == pytest.approx(r2.max_drawdown_pct, abs=1e-6)


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_run_all_returns_one_report_per_scenario(self):
        from omega.eval.crash_replay import CrashReplayRunner

        scenarios = [
            _minimal_scenario("s1", [1.0, 0.95, 0.90]),
            _minimal_scenario("s2", [1.0, 0.80, 0.85]),
            _minimal_scenario("s3", [1.0, 0.70, 0.75]),
        ]
        runner = CrashReplayRunner()
        reports = runner.run_all(scenarios)
        assert len(reports) == 3

    def test_run_all_on_canonical_scenarios(self):
        from omega.eval.crash_replay import CRASH_SCENARIOS, CrashReplayRunner

        runner = CrashReplayRunner(stop_loss_pct=0.20, max_dd_fail_threshold=0.50)
        reports = runner.run_all(CRASH_SCENARIOS, start_price=10_000.0)

        assert len(reports) == len(CRASH_SCENARIOS)
        # All reports should have valid numeric metrics
        for r in reports:
            assert r.max_drawdown_pct >= 0.0
            assert isinstance(r.passed, bool)

    def test_luna_scenario_fails_default_threshold(self):
        """LUNA collapse (-99%) must exceed the default 30% drawdown threshold."""
        from omega.eval.crash_replay import CRASH_SCENARIOS, CrashReplayRunner

        luna = next(s for s in CRASH_SCENARIOS if "LUNA" in s.name)
        runner = CrashReplayRunner(max_dd_fail_threshold=0.30)
        report = runner.run(luna)
        assert report.passed is False, "LUNA collapse should fail the 30% max drawdown gate"

    def test_flash_crash_may_recover(self):
        """Aug 2023 flash crash has partial recovery in the scenario — check recovery tracked."""
        from omega.eval.crash_replay import CRASH_SCENARIOS, CrashReplayRunner

        flash = next(s for s in CRASH_SCENARIOS if "Flash" in s.name)
        runner = CrashReplayRunner(max_dd_fail_threshold=0.99)  # won't fail on drawdown
        report = runner.run(flash, start_price=29_700.0)
        # The flash crash scenario doesn't fully recover — recovery_time could be None or >0
        assert report.max_drawdown_pct > 0.0
