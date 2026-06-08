"""
omega.core.risk_manager
~~~~~~~~~~~~~~~~~~~~~~~~
PositionRiskManager — portfolio-level risk controls for Victoria.

Five layers of protection applied in order during portfolio construction:

1. Max drawdown protection
   If cumulative PnL drops below -MAX_DRAWDOWN_PCT of starting capital,
   all new trades are halted until the portfolio recovers above the threshold.

2. Correlation-based position limits
   Uses the RMT-denoised correlation matrix to prevent opening positions in
   highly correlated tickers simultaneously.  When two candidates exceed
   CORR_THRESHOLD, the lower-conviction one is dropped.

3. Volatility-scaled sizing
   Scales each position's weight inversely with its recent realised volatility.
   High-vol tickers receive smaller allocations; low-vol tickers receive larger.

4. Time-based risk reduction
   Reduces position sizes during historically volatile UTC windows:
     - US market open:  14:30–15:30 UTC  (50% reduction)
     - Asia pre-session: 00:00–01:00 UTC  (25% reduction, gentler)

5. Portfolio heat caps
   - Maximum 6 concurrent open positions
   - Maximum 30% of capital deployed at any time (sum of |weights|)
   - Any candidate that would breach these caps is trimmed / excluded

Usage (inside StrategyNode._construct_portfolio)::

    risk = PositionRiskManager(starting_capital=100_000)
    risk.update_pnl(realised_pnl=cumulative_pnl)

    weights = risk.apply_all(
        weights=raw_weights,
        price_histories=price_histories,    # {ticker: [float]}
        corr_matrix=rmt_denoiser.get_denoised_correlation(),
        tickers=sorted_tickers,             # order matching corr_matrix rows
        convictions=convictions,            # {ticker: ConvictionLevel int}
    )
    if risk.is_halted():
        weights = {}
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

import numpy as np

logger = logging.getLogger("omega.core.risk_manager")

# ── tuneable constants ────────────────────────────────────────────────────────
MAX_DRAWDOWN_PCT: float = 0.08  # halt trading if PnL drops 8% below peak
MAX_POSITIONS: int = 6  # hard cap on concurrent positions
MAX_CAPITAL_DEPLOYED: float = 0.30  # max sum(|weights|) ≤ 30%
CORR_THRESHOLD: float = 0.75  # RMT correlation above which tickers conflict
VOL_WINDOW: int = 20  # bars used to compute recent realised vol
VOL_HISTORY_LEN: int = 60  # price history length for vol estimation
TARGET_VOL: float = 0.15  # annualised target vol for vol-scaling (≈ risk-parity)
# Time-of-day windows (UTC hour, minute) → size multiplier
_TIME_RISK_WINDOWS: list[tuple[int, int, int, int, float]] = [
    # (start_hour, start_min, end_hour, end_min, multiplier)
    (14, 30, 15, 30, 0.50),  # US market open — most volatile 60-min window
    (0, 0, 1, 0, 0.75),  # Asia pre-session — moderate reduction
]


class PositionRiskManager:
    """
    Portfolio-level risk manager for Victoria.

    Designed to be instantiated once inside StrategyNode and called every cycle.
    All state is kept internally; no external DB required.

    Parameters
    ----------
    starting_capital : float
        Reference capital for drawdown calculation.  Update via update_pnl().
    max_drawdown_pct : float
        Fraction of starting capital that triggers a halt (default 8%).
    max_positions : int
        Maximum concurrent positions allowed (default 6).
    max_capital_deployed : float
        Maximum fraction of capital sum(|weights|) may represent (default 0.30).
    corr_threshold : float
        RMT-denoised correlation above which two positions conflict (default 0.75).
    """

    def __init__(
        self,
        starting_capital: float = 100_000.0,
        max_drawdown_pct: float = MAX_DRAWDOWN_PCT,
        max_positions: int = MAX_POSITIONS,
        max_capital_deployed: float = MAX_CAPITAL_DEPLOYED,
        corr_threshold: float = CORR_THRESHOLD,
    ) -> None:
        self.starting_capital = starting_capital
        self.max_drawdown_pct = max_drawdown_pct
        self.max_positions = max_positions
        self.max_capital_deployed = max_capital_deployed
        self.corr_threshold = corr_threshold

        # PnL / drawdown tracking
        self._cumulative_pnl: float = 0.0
        self._peak_capital: float = starting_capital
        self._halted: bool = False

        # Metrics for observability
        self.halt_count: int = 0
        self.corr_blocks: int = 0
        self.heat_trims: int = 0
        self.vol_scale_applications: int = 0

    # ──────────────────────────────────────── public: state updates ──────────

    def update_pnl(self, realized_pnl: float, unrealized_pnl: float = 0.0) -> None:
        """
        Record current PnL against starting capital.

        Parameters
        ----------
        realized_pnl    : cumulative realised P&L since inception (signed, in capital units).
        unrealized_pnl  : current mark-to-market unrealised P&L (default 0).
        """
        self._cumulative_pnl = float(realized_pnl) + float(unrealized_pnl)
        current_capital = self.starting_capital + self._cumulative_pnl

        # Update high-water mark
        if current_capital > self._peak_capital:
            self._peak_capital = current_capital

        # Drawdown from peak
        drawdown = (self._peak_capital - current_capital) / max(self._peak_capital, 1e-9)

        if drawdown >= self.max_drawdown_pct:
            if not self._halted:
                self.halt_count += 1
                logger.warning(
                    "RiskManager: HALT triggered — drawdown %.2f%% ≥ threshold %.2f%% "
                    "(peak=%.2f current=%.2f)",
                    drawdown * 100,
                    self.max_drawdown_pct * 100,
                    self._peak_capital,
                    current_capital,
                )
            self._halted = True
        else:
            if self._halted:
                logger.info(
                    "RiskManager: trading RESUMED — drawdown %.2f%% < threshold %.2f%%",
                    drawdown * 100,
                    self.max_drawdown_pct * 100,
                )
            self._halted = False

    def is_halted(self) -> bool:
        """Return True if max-drawdown protection is active (no new trades)."""
        return self._halted

    def current_drawdown(self) -> float:
        """Return current drawdown as a fraction [0, 1]."""
        current_capital = self.starting_capital + self._cumulative_pnl
        return (self._peak_capital - current_capital) / max(self._peak_capital, 1e-9)

    # ──────────────────────────────────────── layer 2: correlation filter ─────

    def filter_correlated_positions(
        self,
        weights: dict[str, float],
        corr_matrix: np.ndarray | None,
        tickers: list[str],
        convictions: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """
        Remove correlated positions using the RMT-denoised correlation matrix.

        When two tickers in `weights` have |correlation| ≥ corr_threshold,
        the one with lower |conviction| (or lower |weight|) is dropped.

        Parameters
        ----------
        weights     : {ticker: weight} dict from portfolio construction.
        corr_matrix : N×N RMT-denoised correlation matrix (or None if unavailable).
        tickers     : ordered list of tickers whose index maps to corr_matrix rows.
        convictions : optional {ticker: float} conviction scores for tie-breaking.

        Returns
        -------
        Filtered weights dict with highly correlated duplicates removed.
        """
        if corr_matrix is None or len(weights) <= 1:
            return weights

        # Only care about tickers we actually have weights for
        active = {t: w for t, w in weights.items() if abs(w) > 1e-6}
        if len(active) <= 1:
            return weights

        # Build index lookup for correlation matrix
        ticker_idx: dict[str, int] = {t: i for i, t in enumerate(tickers)}

        # Sort by descending conviction (or |weight|) — keep the stronger one
        def sort_key(t: str) -> float:
            if convictions and t in convictions:
                return abs(float(convictions[t]))
            return abs(active.get(t, 0.0))

        ranked = sorted(active.keys(), key=sort_key, reverse=True)

        kept: set[str] = set()
        dropped: set[str] = set()

        for candidate in ranked:
            if candidate in dropped:
                continue
            idx_c = ticker_idx.get(candidate)
            if idx_c is None or idx_c >= corr_matrix.shape[0]:
                kept.add(candidate)
                continue

            # Check against all already-kept positions
            conflict = False
            for kept_t in kept:
                idx_k = ticker_idx.get(kept_t)
                if idx_k is None or idx_k >= corr_matrix.shape[0]:
                    continue
                corr = float(corr_matrix[idx_c, idx_k])
                if abs(corr) >= self.corr_threshold:
                    dropped.add(candidate)
                    self.corr_blocks += 1
                    logger.info(
                        "RiskManager: dropped %s (corr=%.3f with %s ≥ %.2f threshold)",
                        candidate,
                        corr,
                        kept_t,
                        self.corr_threshold,
                    )
                    conflict = True
                    break

            if not conflict:
                kept.add(candidate)

        return {t: w for t, w in weights.items() if t in kept}

    # ──────────────────────────────────────── layer 3: volatility scaling ─────

    def vol_scale_weights(
        self,
        weights: dict[str, float],
        price_histories: dict[str, list[float]],
        window: int = VOL_WINDOW,
    ) -> dict[str, float]:
        """
        Scale position weights inversely with recent realised volatility.

        Tickers with higher realised vol get smaller weights; tickers with lower
        vol get larger weights — normalised so the total |weight| is preserved.

        Parameters
        ----------
        weights         : {ticker: weight} dict.
        price_histories : {ticker: [price, ...]} recent close prices.
        window          : number of bars for vol estimation (default 20).

        Returns
        -------
        Vol-scaled weights (same total |weight| as input).
        """
        if not weights or not price_histories:
            return weights

        total_abs_before = sum(abs(w) for w in weights.values())
        if total_abs_before < 1e-9:
            return weights

        vols: dict[str, float] = {}
        for ticker in weights:
            prices = price_histories.get(ticker, [])
            vols[ticker] = self._realised_vol(prices, window)

        # Inverse-vol weights: TARGET_VOL / vol  (risk-parity style)
        inv_vol_weights: dict[str, float] = {}
        for ticker, w in weights.items():
            direction = math.copysign(1.0, w)
            vol = vols[ticker]
            scale = TARGET_VOL / max(vol, 0.01)
            # Cap individual scale to [0.25, 2.0] to avoid extreme moves
            scale = max(0.25, min(2.0, scale))
            inv_vol_weights[ticker] = direction * abs(w) * scale

        # Re-normalise so total |weight| matches input
        total_abs_after = sum(abs(w) for w in inv_vol_weights.values())
        if total_abs_after < 1e-9:
            return weights

        ratio = total_abs_before / total_abs_after
        scaled = {t: w * ratio for t, w in inv_vol_weights.items()}

        self.vol_scale_applications += 1
        logger.debug(
            "RiskManager: vol-scaled %d positions (vols: %s)",
            len(scaled),
            {t: round(v, 4) for t, v in vols.items()},
        )
        return scaled

    # ──────────────────────────────────────── layer 4: time-based risk ───────

    def time_risk_multiplier(self, now: datetime | None = None) -> float:
        """
        Return a size multiplier [0.5, 1.0] based on the current UTC time.

        Applies reductions during historically volatile windows:
          - 14:30–15:30 UTC : 0.50  (US market open)
          - 00:00–01:00 UTC : 0.75  (Asia pre-session)
        Outside these windows: 1.0

        Parameters
        ----------
        now : datetime to evaluate (defaults to current UTC time).
        """
        if now is None:
            now = datetime.now(UTC)  # wallclock-ok: live fallback; backtest threads bar-time via caller (V216)

        current_minutes = now.hour * 60 + now.minute

        for start_h, start_m, end_h, end_m, multiplier in _TIME_RISK_WINDOWS:
            window_start = start_h * 60 + start_m
            window_end = end_h * 60 + end_m
            if window_start <= current_minutes < window_end:
                logger.debug(
                    "RiskManager: time window %02d:%02d–%02d:%02d UTC → size multiplier %.2f",
                    start_h,
                    start_m,
                    end_h,
                    end_m,
                    multiplier,
                )
                return multiplier

        return 1.0

    # ──────────────────────────────────────── layer 5: portfolio heat ────────

    def apply_portfolio_heat(self, weights: dict[str, float]) -> dict[str, float]:
        """
        Enforce portfolio heat caps:
          - Maximum self.max_positions concurrent positions
          - Maximum self.max_capital_deployed total |weight|

        When position count exceeds the cap, the lowest-|weight| positions are
        trimmed first.  When total exposure exceeds the cap, all weights are
        scaled down proportionally.

        Returns
        -------
        Trimmed and/or scaled weights dict.
        """
        if not weights:
            return weights

        result = dict(weights)

        # --- Cap 1: position count ---
        if len(result) > self.max_positions:
            # Keep the self.max_positions largest by |weight|
            sorted_by_size = sorted(result.items(), key=lambda kv: abs(kv[1]), reverse=True)
            trimmed = sorted_by_size[self.max_positions :]
            for ticker, _ in trimmed:
                del result[ticker]
                self.heat_trims += 1
                logger.info(
                    "RiskManager: trimmed %s (position cap %d reached)",
                    ticker,
                    self.max_positions,
                )

        # --- Cap 2: total capital deployed ---
        total_exposure = sum(abs(w) for w in result.values())
        if total_exposure > self.max_capital_deployed:
            scale = self.max_capital_deployed / total_exposure
            result = {t: w * scale for t, w in result.items()}
            logger.info(
                "RiskManager: exposure %.1f%% > cap %.1f%% — scaled down by %.3f",
                total_exposure * 100,
                self.max_capital_deployed * 100,
                scale,
            )

        return result

    # ──────────────────────────────────────── convenience: apply all ─────────

    def apply_all(
        self,
        weights: dict[str, float],
        price_histories: dict[str, list[float]] | None = None,
        corr_matrix: np.ndarray | None = None,
        tickers: list[str] | None = None,
        convictions: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> dict[str, float]:
        """
        Run all five risk layers in sequence and return adjusted weights.

        If is_halted() is True, returns an empty dict immediately.

        Layers applied:
          1. Drawdown halt check (returns {} if halted)
          2. Correlation filter (removes conflicting positions)
          3. Volatility scaling (inverse-vol position sizing)
          4. Time-of-day multiplier (reduces size in volatile windows)
          5. Portfolio heat caps (position count + capital deployed limits)

        Parameters
        ----------
        weights         : {ticker: weight} from portfolio construction.
        price_histories : {ticker: [float]} for vol estimation (layer 3).
        corr_matrix     : RMT-denoised N×N correlation matrix (layer 2).
        tickers         : ordered ticker list matching corr_matrix rows (layer 2).
        convictions     : {ticker: float} for corr tie-breaking (layer 2).
        now             : override current time for testing (layer 4).

        Returns
        -------
        Risk-adjusted weights dict.
        """
        # Layer 1: drawdown halt
        if self._halted:
            logger.info(
                "RiskManager: all trades halted (drawdown %.2f%% ≥ threshold %.2f%%)",
                self.current_drawdown() * 100,
                self.max_drawdown_pct * 100,
            )
            return {}

        result = dict(weights)

        # Layer 2: correlation filter
        if corr_matrix is not None and tickers is not None:
            result = self.filter_correlated_positions(result, corr_matrix, tickers, convictions)

        # Layer 3: volatility scaling
        if price_histories:
            result = self.vol_scale_weights(result, price_histories)

        # Layer 4: time-based risk multiplier
        time_mult = self.time_risk_multiplier(now)
        if time_mult < 1.0 and result:
            result = {t: w * time_mult for t, w in result.items()}

        # Layer 5: portfolio heat caps
        result = self.apply_portfolio_heat(result)

        return result

    # ──────────────────────────────────────── metrics / observability ────────

    def get_metrics(self) -> dict[str, Any]:
        """Return current risk metrics for dashboard / telemetry."""
        return {
            "halted": self._halted,
            "current_drawdown_pct": round(self.current_drawdown() * 100, 3),
            "peak_capital": round(self._peak_capital, 2),
            "cumulative_pnl": round(self._cumulative_pnl, 2),
            "halt_count": self.halt_count,
            "corr_blocks": self.corr_blocks,
            "heat_trims": self.heat_trims,
            "vol_scale_applications": self.vol_scale_applications,
            "max_drawdown_threshold_pct": round(self.max_drawdown_pct * 100, 1),
            "max_positions": self.max_positions,
            "max_capital_deployed_pct": round(self.max_capital_deployed * 100, 1),
            "corr_threshold": round(self.corr_threshold, 2),
        }

    # ──────────────────────────────────────── private helpers ────────────────

    @staticmethod
    def _realised_vol(prices: list[float], window: int = VOL_WINDOW) -> float:
        """
        Compute annualised realised volatility from price history.

        Uses log-returns over `window` bars.  Assumes hourly bars → annualises
        by sqrt(24 * 365).  Returns TARGET_VOL as a neutral default when
        insufficient data is available.
        """
        clean = [p for p in prices if p and not math.isnan(p) and p > 0]
        if len(clean) < window + 1:
            return TARGET_VOL

        recent = clean[-(window + 1) :]
        log_rets = [
            math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent)) if recent[i - 1] > 0
        ]
        if len(log_rets) < 2:
            return TARGET_VOL

        mean = sum(log_rets) / len(log_rets)
        variance = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
        daily_vol = math.sqrt(variance)
        # Annualise: hourly bars → 24 * 365 periods per year
        ann_vol = daily_vol * math.sqrt(24 * 365)
        return max(0.01, ann_vol)
