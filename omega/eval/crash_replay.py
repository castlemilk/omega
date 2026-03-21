"""
omega.eval.crash_replay
~~~~~~~~~~~~~~~~~~~~~~~
Historical crypto crash replay evaluator.

Feeds hardcoded historical crash price series through a strategy and measures
resilience: max drawdown, recovery time, stop-loss firing, and PnL.

Scenarios
---------
* March 2020 COVID crash  — BTC -50% in 2 days
* May 2021 China ban      — BTC -35% over a week
* LUNA/UST May 2022       — Complete death spiral (-99%+)
* FTX collapse Nov 2022   — BTC -25%, extreme vol
* Aug 2023 flash crash    — -10% in minutes (single-session)

Usage::

    runner = CrashReplayRunner(stop_loss_pct=0.15, max_dd_fail_threshold=0.30)
    reports = runner.run_all(CRASH_SCENARIOS)
    for r in reports:
        status = "PASS" if r.passed else "FAIL"
        print(f"{status}  {r.scenario_name}  max_dd={r.max_drawdown_pct:.1%}")
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger("omega.eval.crash_replay")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CrashScenario:
    """
    A historical crash represented as a sequence of price multipliers.

    ``price_multipliers[i]`` is the price at step *i* relative to
    the starting price (1.0 = no change, 0.5 = -50%).
    ``volume_multipliers[i]`` is the relative volume at step *i*
    (1.0 = normal volume).
    """

    name: str
    symbol: str
    date_range: tuple[str, str]  # (start_iso, end_iso)
    description: str
    # Relative to starting price (1.0 = start)
    price_multipliers: list[float]
    # Relative to baseline volume (1.0 = normal)
    volume_multipliers: list[float]


@dataclass
class CrashReplayReport:
    """Results from replaying one crash scenario through a strategy."""

    scenario_name: str
    symbol: str
    start_price: float
    end_price: float
    max_drawdown_pct: float  # e.g. 0.35 means 35% drawdown
    recovery_time_bars: int | None  # bars to recover peak; None = never recovered
    stop_losses_fired: int
    total_pnl_pct: float  # (end_price - start_price) / start_price
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)
    bar_pnls: list[float] = field(default_factory=list)  # per-bar PnL series


# ---------------------------------------------------------------------------
# Hardcoded historical crash scenarios
# ---------------------------------------------------------------------------

CRASH_SCENARIOS: list[CrashScenario] = [
    # -----------------------------------------------------------------------
    # 1. March 2020 COVID crash - BTC lost ~50% in 2 days (12-13 Mar 2020)
    # -----------------------------------------------------------------------
    CrashScenario(
        name="March 2020 COVID Crash",
        symbol="BTCUSDT",
        date_range=("2020-03-08", "2020-04-07"),
        description=(
            "COVID-19 pandemic declared; BTC fell from ~$9k to ~$4k (-50%) in 48 hours "
            "on 12-13 March 2020. Correlated with global equity sell-off. "
            "High-severity liquidity crunch."
        ),
        price_multipliers=[
            # Pre-crash: mild drift down (days 0-3)
            1.000,
            0.980,
            0.960,
            0.940,
            # Crash day 1: -30% (day 4)
            0.660,
            # Crash day 2: further -28% (day 5)
            0.475,
            # Dead-cat bounce then slow recovery (days 6-30)
            0.520,
            0.540,
            0.510,
            0.525,
            0.550,
            0.565,
            0.580,
            0.600,
            0.615,
            0.630,
            0.645,
            0.660,
            0.675,
            0.690,
            0.700,
            0.715,
            0.725,
            0.730,
            0.735,
            0.740,
            0.750,
            0.760,
            0.770,
            0.780,
            0.790,
        ],
        volume_multipliers=[
            1.0,
            1.2,
            1.5,
            1.8,
            6.0,  # panic volume on crash day 1
            8.0,  # peak panic day 2
            4.0,
            3.5,
            3.0,
            2.5,
            2.0,
            1.8,
            1.6,
            1.5,
            1.4,
            1.3,
            1.2,
            1.2,
            1.1,
            1.1,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        ],
    ),
    # -----------------------------------------------------------------------
    # 2. May 2021 China ban — BTC -35% over a week, mass liquidation cascade
    # -----------------------------------------------------------------------
    CrashScenario(
        name="May 2021 China Ban",
        symbol="BTCUSDT",
        date_range=("2021-05-13", "2021-06-12"),
        description=(
            "China announced crypto mining ban; Elon Musk tweets Bitcoin energy FUD. "
            "BTC dropped from ~$58k to ~$30k (-35%) over 7 days in May 2021. "
            "Massive long liquidation cascade. Slow partial recovery."
        ),
        price_multipliers=[
            # Initial drop over 7 days
            1.000,
            0.930,
            0.870,
            0.810,
            0.760,
            0.710,
            0.660,
            # Stabilisation with volatility
            0.680,
            0.650,
            0.670,
            0.640,
            0.620,
            0.610,
            0.630,
            # Slow grind recovery attempt
            0.650,
            0.660,
            0.670,
            0.665,
            0.655,
            0.645,
            0.640,
            0.650,
            0.660,
            0.670,
            0.680,
            0.685,
            0.690,
            0.695,
            0.700,
            0.705,
        ],
        volume_multipliers=[
            1.0,
            2.0,
            3.5,
            4.0,
            5.0,
            4.5,
            4.0,
            3.5,
            3.0,
            2.8,
            2.5,
            2.3,
            2.0,
            1.8,
            1.6,
            1.5,
            1.4,
            1.3,
            1.3,
            1.2,
            1.2,
            1.1,
            1.1,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        ],
    ),
    # -----------------------------------------------------------------------
    # 3. LUNA/UST collapse May 2022 — complete death spiral, -99%+
    # -----------------------------------------------------------------------
    CrashScenario(
        name="LUNA/UST Collapse May 2022",
        symbol="LUNAUSDT",
        date_range=("2022-05-07", "2022-05-20"),
        description=(
            "Terra/LUNA death spiral: UST de-pegged, LUNA hyperinflated to absorb sell pressure. "
            "Price went from ~$80 to near-zero in 72 hours. BTC dropped 30% in contagion. "
            "Most extreme crypto collapse on record — no recovery."
        ),
        price_multipliers=[
            # Pre-spiral: LUNA at ~$80, first wobble
            1.000,
            0.950,
            0.800,
            # Spiral begins: UST de-peg triggers algorithmic collapse
            0.500,
            0.200,
            0.050,
            # Death zone: hyperinflation of supply
            0.010,
            0.002,
            0.001,
            0.0005,
            0.0002,
            # Effectively zero
            0.0001,
            0.0001,
            0.0001,
        ],
        volume_multipliers=[
            1.0,
            3.0,
            8.0,
            15.0,
            20.0,
            25.0,
            30.0,
            25.0,
            20.0,
            15.0,
            10.0,
            5.0,
            3.0,
            2.0,
        ],
    ),
    # -----------------------------------------------------------------------
    # 4. FTX collapse November 2022 — BTC -25%, extreme vol
    # -----------------------------------------------------------------------
    CrashScenario(
        name="FTX Collapse Nov 2022",
        symbol="BTCUSDT",
        date_range=("2022-11-06", "2022-12-06"),
        description=(
            "FTX exchange declared bankruptcy (Nov 11 2022). CoinDesk exposé on Alameda balance "
            "sheet triggered bank run. BTC dropped 25% in 48 hours with extreme volatility. "
            "Contagion hit SOL (-60%), FTT near-zero."
        ),
        price_multipliers=[
            # Day 0-1: CoinDesk article, minor drop
            1.000,
            0.970,
            # Day 2-3: Binance announces FTT sale, panic begins
            0.920,
            0.870,
            # Day 4-5: FTX halts withdrawals, BK filing
            0.800,
            0.760,
            # Day 6-7: full panic, BTC bottom
            0.740,
            0.750,
            # Stabilisation with high vol
            0.770,
            0.760,
            0.750,
            0.760,
            0.770,
            0.780,
            0.785,
            0.790,
            0.785,
            0.780,
            0.775,
            0.780,
            # Slow grind
            0.790,
            0.795,
            0.800,
            0.805,
            0.810,
            0.815,
            0.820,
            0.825,
            0.830,
            0.835,
        ],
        volume_multipliers=[
            1.0,
            2.0,
            3.5,
            4.0,
            5.5,
            6.0,
            5.0,
            4.0,
            3.5,
            3.0,
            2.8,
            2.5,
            2.3,
            2.1,
            2.0,
            1.9,
            1.8,
            1.7,
            1.6,
            1.5,
            1.4,
            1.3,
            1.2,
            1.2,
            1.1,
            1.1,
            1.0,
            1.0,
            1.0,
            1.0,
        ],
    ),
    # -----------------------------------------------------------------------
    # 5. August 2023 flash crash — -10% in minutes on thin liquidity
    # -----------------------------------------------------------------------
    CrashScenario(
        name="Aug 2023 Flash Crash",
        symbol="BTCUSDT",
        date_range=("2023-08-17", "2023-09-01"),
        description=(
            "17 August 2023: BTC flash crashed from ~$29.7k to ~$25.1k (-15%) in under "
            "an hour on extremely thin liquidity. Likely triggered by large leveraged "
            "liquidation cascade. Near-full recovery within hours."
        ),
        price_multipliers=[
            # Normal lead-up (bars 0-1)
            1.000,
            0.995,
            # Flash crash bar: -15% (bar 2 = the crash candle)
            0.850,
            # Immediate partial bounce
            0.890,
            0.905,
            # Recovery over following days
            0.920,
            0.930,
            0.935,
            0.940,
            0.945,
            0.950,
            0.952,
            0.955,
            0.958,
            0.960,
            0.962,
            0.963,
        ],
        volume_multipliers=[
            1.0,
            1.1,
            12.0,  # massive volume on crash candle
            4.0,
            2.5,
            1.8,
            1.5,
            1.3,
            1.2,
            1.1,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        ],
    ),
]


# ---------------------------------------------------------------------------
# CrashReplayRunner
# ---------------------------------------------------------------------------


class CrashReplayRunner:
    """
    Feeds historical crash price series through a strategy and measures resilience.

    Parameters
    ----------
    stop_loss_pct:
        If the unrealised drawdown from entry exceeds this, count it as a
        stop-loss firing.  Default 0.15 (15%).
    max_dd_fail_threshold:
        Max drawdown above this value causes the report to FAIL.
        Default 0.30 (30%).
    strategy_fn:
        Optional callable with signature
        ``strategy_fn(bar_idx, price, volume, position) -> float``
        where the return value is the desired position size in [-1, 1].
        If *None*, a simple buy-and-hold is simulated (position=1 always).
    """

    def __init__(
        self,
        stop_loss_pct: float = 0.15,
        max_dd_fail_threshold: float = 0.30,
        strategy_fn: Callable[[int, float, float, float], float] | None = None,
    ) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.max_dd_fail_threshold = max_dd_fail_threshold
        self._strategy_fn = strategy_fn or self._buy_and_hold

    @staticmethod
    def _buy_and_hold(bar_idx: int, price: float, volume: float, position: float) -> float:
        """Default: always hold a long position."""
        return 1.0

    def run(
        self,
        scenario: CrashScenario,
        start_price: float = 10_000.0,
    ) -> CrashReplayReport:
        """
        Replay *scenario* and return a ``CrashReplayReport``.

        Parameters
        ----------
        scenario:
            The crash scenario to replay.
        start_price:
            Starting price in USD.  Multiplied by ``price_multipliers``
            to produce the actual price series.
        """
        multipliers = scenario.price_multipliers
        vol_mults = scenario.volume_multipliers
        n = len(multipliers)
        assert len(vol_mults) == n, "price and volume multiplier lengths must match"

        prices = [start_price * m for m in multipliers]

        position: float = 0.0
        entry_price: float = 0.0
        stop_losses_fired: int = 0

        peak_price = prices[0]
        max_drawdown = 0.0
        bar_pnls: list[float] = [0.0]  # bar 0 has no prior bar

        for i in range(1, n):
            prev_price = prices[i - 1]
            cur_price = prices[i]
            volume = start_price * vol_mults[i]

            # Ask strategy for desired position
            desired = self._strategy_fn(i, cur_price, volume, position)
            desired = max(-1.0, min(1.0, desired))

            # Check stop-loss on existing long position
            if position > 0 and entry_price > 0:
                unrealised_dd = (entry_price - cur_price) / entry_price
                if unrealised_dd >= self.stop_loss_pct:
                    stop_losses_fired += 1
                    position = 0.0
                    entry_price = 0.0

            # Apply position change
            if position == 0.0 and desired > 0.0:
                position = desired
                entry_price = cur_price
            elif position > 0.0 and desired <= 0.0:
                position = 0.0
                entry_price = 0.0

            # Bar PnL (long only for now)
            bar_pnl = position * (cur_price - prev_price) / prev_price
            bar_pnls.append(bar_pnl)

            # Track drawdown from running peak
            if cur_price > peak_price:
                peak_price = cur_price
            dd = (peak_price - cur_price) / peak_price
            if dd > max_drawdown:
                max_drawdown = dd

        # Recovery time: how many bars after the trough does price regain the peak?
        trough_idx = prices.index(min(prices))
        recovery_time: int | None = None
        if trough_idx < n - 1:
            peak_before_trough = max(prices[: trough_idx + 1])
            for j in range(trough_idx + 1, n):
                if prices[j] >= peak_before_trough:
                    recovery_time = j - trough_idx
                    break

        total_pnl = sum(bar_pnls)
        failure_reasons: list[str] = []
        if max_drawdown > self.max_dd_fail_threshold:
            failure_reasons.append(
                f"max_drawdown={max_drawdown:.1%} > threshold={self.max_dd_fail_threshold:.1%}"
            )

        passed = len(failure_reasons) == 0

        logger.info(
            "CrashReplay [%s]: max_dd=%.1f%%  recovery=%s  stop_losses=%d  pnl=%.2f%%  %s",
            scenario.name,
            max_drawdown * 100,
            f"{recovery_time}b" if recovery_time else "never",
            stop_losses_fired,
            total_pnl * 100,
            "PASS" if passed else "FAIL",
        )

        return CrashReplayReport(
            scenario_name=scenario.name,
            symbol=scenario.symbol,
            start_price=prices[0],
            end_price=prices[-1],
            max_drawdown_pct=max_drawdown,
            recovery_time_bars=recovery_time,
            stop_losses_fired=stop_losses_fired,
            total_pnl_pct=total_pnl,
            passed=passed,
            failure_reasons=failure_reasons,
            bar_pnls=bar_pnls,
        )

    def run_all(
        self,
        scenarios: list[CrashScenario],
        start_price: float = 10_000.0,
    ) -> list[CrashReplayReport]:
        """Run all scenarios and return a report per scenario."""
        reports = []
        for scenario in scenarios:
            report = self.run(scenario, start_price=start_price)
            reports.append(report)

        passed = sum(1 for r in reports if r.passed)
        logger.info("CrashReplay complete: %d/%d scenarios passed", passed, len(reports))
        return reports
