"""
omega/nodes/victoria/exit_controller.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ATR-based tiered exit controller — fixes the structural disposition effect.

The system-wide disposition coefficient was −0.44 to −0.62 across all backtest
configs (Phase A, April 2026). This module replaces the fixed-percentage /
time-based exit logic with ATR-anchored stops and trailing take-profits.

Design
------
Two exit mechanisms, both ATR-denominated:

  1. Hard MAE stop  — close immediately if running loss ≥ K_stop × ATR.
     Prevents "hold-and-pray" losers that drag MAE well past MFE.

  2. MFE trailing stop — once peak gain ≥ K_trail × ATR, lock 75% of that
     peak by trailing at MFE × (1 − retracement_cap).  Fires when we give
     back more than retracement_cap fraction of the best gain seen.

Both coexist with the existing time-exit and stop-loss fallbacks in
mark_to_market(); this module fires first when enabled.

Exit telemetry (per-trade, appended to trades CSV):
  win_capture   = pnl / mfe        (winners: fraction of peak captured)
  loss_capture  = |pnl| / |mae|    (losers:  fraction of worst seen realised)
  exit_score    = win_capture − loss_capture  (positive = good discipline)

Feature flags (in VictoriaFeatures):
  disposition_exit_controller  — master switch (bool)
  mfe_trail_k                  — MFE trailing ATR multiplier (float, default 1.0)
  mfe_retracement_cap          — fraction of MFE to give back before trailing (float, 0.25)
  mae_stop_k                   — hard stop ATR multiplier (float, default 0.8)

Usage (in PaperTradingEngine.mark_to_market):
    from omega.nodes.victoria.exit_controller import ExitController, ExitConfig
    ec = ExitController(ExitConfig(mfe_trail_k=1.0, mfe_retracement_cap=0.25, mae_stop_k=0.8))
    close, reason = ec.should_close(pos, current_price, sym_market, size, unrealized)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ExitConfig:
    """Runtime parameters for the exit controller."""

    enabled: bool = True

    # MFE trailing: activate once MFE >= mfe_trail_k * ATR ($ units)
    mfe_trail_k: float = 1.0

    # Retracement cap: fire trailing stop when we give back this fraction of MFE.
    # 0.25 → lock 75% of peak gain.
    mfe_retracement_cap: float = 0.25

    # Hard stop: close if running loss >= mae_stop_k * ATR ($ units)
    mae_stop_k: float = 0.8

    # Early loss time-stop (V131): close losers that haven't recovered after N cycles.
    # Fires when: age >= early_loss_cycles AND unrealized <= -(early_loss_k_atr * ATR).
    # Goal: break the loss_capture=1.0 invariant by exiting underwater positions
    # before they drift to their MAE point on the random time-exit.
    early_loss_time_stop: bool = False
    early_loss_cycles: int = 3  # minimum age before the stop can fire
    early_loss_k_atr: float = 0.3  # loss threshold (fraction of ATR in $ terms)

    # Legacy trailing-stop minimum age guard (V132): suppress the 50%-MFE
    # trailing stop until a position has been open for at least this many cycles.
    # 0 = disabled (original behaviour). 3 or 4 = gives losers time to recover
    # before the stop fires at a new-low tick (loss_capture=1.0 structurally).
    trailing_stop_min_age: int = 0

    # Legacy stop-loss minimum age guard (V133): suppress the -2% ROI stop-loss
    # until position age >= this value.  0 = original behaviour (fires immediately).
    # Set to 3 so the stop-loss cannot fire at age 1-2 before early_loss_time_stop
    # (age >= early_loss_cycles) can act — the third unguarded loss_capture=1.0 path.
    stop_loss_min_age: int = 0

    # V135: skip the legacy fixed-% stop-loss entirely.  When True, the -2% ROI
    # stop in paper_trading.py is bypassed; the ExitController's mae_stop_k ATR
    # stop becomes the sole downside guard (set mae_stop_k to desired ATR multiple).
    # This allows loss_capture < 1.0 because the ATR stop fires at a threshold that
    # is independent of the MAE tick — unlike the -2% stop which fires exactly at
    # the first new-low, structurally guaranteeing loss_capture = 1.0.
    skip_legacy_stop_loss: bool = False

    # V141: side-specific trail multipliers (applied to mfe_trail_k per position side).
    # long_trail_multiplier=0.5: trail activates at 0.5× ATR MFE (tighter, exits losing longs sooner).
    # short_trail_multiplier=1.5: trail activates at 1.5× ATR MFE (wider, lets shorts run further).
    long_trail_multiplier: float = 1.0
    short_trail_multiplier: float = 1.0

    # V141: close positions with zero MFE after N cycles (disabled when 0).
    # Forensics: positions with mfe=0 after 2-4 cycles went immediately against entry.
    # The fix is not entering them; but given we did, exit early rather than hold to full ATR stop.
    zero_mfe_early_exit_cycles: int = 0

    # V184 soft profit-lock. Independent of mfe_trail_k/mfe_retracement_cap, this
    # is a "any-positive-MFE" trail intended to catch the V177 forensic pattern:
    # 40% of losers (19/47) touched positive MFE before reversing. The existing
    # MFE trail requires MFE >= mfe_trail_k × ATR before activating, which most
    # of those losers never crossed. When > 0, this trail activates as soon as
    # MFE > 0 and exits when unrealized < mfe * mfe_trailing_retracement.
    # 0.0 = disabled. 0.50 = lock 50% of MFE (tight). 0.70 = lock 70%.
    mfe_trailing_retracement: float = 0.0

    # V189 minimum hold cycles. Gap analysis on 2805 aggregated trades shows
    # 1-2 cycle exits had 3% WR and -$167/trade (-$170K aggregated). When set,
    # the ExitController will NOT close positions younger than this except via
    # hard stops (early_loss_time_stop, mae_stop_k, skip_legacy_stop_loss). The
    # soft trails and zero_mfe_early_exit are suppressed below this age.
    min_hold_cycles: int = 0

    # ATR lookback period (bars)
    atr_period: int = 14


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------


def compute_atr(market_data: dict[str, Any], period: int = 14) -> float:
    """
    Compute Average True Range from OHLCV market data.

    Returns ATR in the asset's price units (not dollars).
    Returns 0.0 if insufficient data.
    """
    highs = market_data.get("high") or []
    lows = market_data.get("low") or []
    closes = market_data.get("close") or []

    # Need at least 2 bars for true range
    n_avail = min(len(highs), len(lows), len(closes))
    if n_avail < 2:
        return 0.0

    n = min(n_avail, period + 1)
    trs: list[float] = []
    for i in range(max(n_avail - n, 0) + 1, n_avail):
        h = float(highs[i])
        lo = float(lows[i])
        prev_c = float(closes[i - 1])
        tr = max(h - lo, abs(h - prev_c), abs(lo - prev_c))
        trs.append(tr)

    return sum(trs) / len(trs) if trs else 0.0


# ---------------------------------------------------------------------------
# ExitController
# ---------------------------------------------------------------------------


class ExitController:
    """
    ATR-anchored exit controller.

    Designed as a stateless callable: all position state lives in the
    ``pos`` dict from PaperTradingEngine; this class only evaluates conditions.
    """

    def __init__(self, config: ExitConfig | None = None) -> None:
        self.config = config or ExitConfig()

    def should_close(
        self,
        pos: dict[str, Any],
        current_price: float,
        sym_market: dict[str, Any],
        size: float,
        unrealized: float,
        age: int = 0,
    ) -> tuple[bool, str]:
        """
        Evaluate whether an open position should be closed.

        Parameters
        ----------
        pos           : Position record from PaperTradingEngine._positions.
        current_price : Current mark price for this symbol.
        sym_market    : Full market-data dict for this symbol (needs high/low/close).
        size          : Notional size of the position in USD.
        unrealized    : Current unrealised PnL in USD.
        age           : Cycles elapsed since position was opened (for time-stop).

        Returns
        -------
        (should_close: bool, reason: str)
        """
        cfg = self.config
        if not cfg.enabled:
            return False, ""

        atr_price = compute_atr(sym_market, cfg.atr_period)
        if atr_price <= 0:
            return False, ""

        entry = float(pos.get("entry", current_price))
        if entry <= 0:
            return False, ""

        # Convert ATR from price units → dollar units
        quantity = size / entry
        atr_dollars = atr_price * quantity
        if atr_dollars <= 0:
            return False, ""

        mfe = float(pos.get("mfe", 0.0))  # most positive unrealised during lifetime
        position_side = str(pos.get("side", "")).lower()

        # V189 minimum hold cycles. Gap analysis on 2805 aggregated trades:
        # 1-2 cycle exits had 3% WR and -$167/trade. Suppress soft exits below
        # this age. Hard MAE stops still fire — only the soft trails are gated.
        _min_hold = int(getattr(cfg, "min_hold_cycles", 0) or 0)
        _below_min_hold = _min_hold > 0 and age < _min_hold

        # ── 0. Zero-MFE early exit (V141) ───────────────────────────────
        # Close positions that never showed profit after N cycles. Forensics:
        # all top losers had mfe=/bin/zsh after 2-4 cycles — wrong from the first tick.
        if (
            cfg.zero_mfe_early_exit_cycles > 0
            and age >= cfg.zero_mfe_early_exit_cycles
            and not _below_min_hold
        ):
            if mfe <= 0.0 and unrealized < 0.0:
                return True, (
                    f"zero_mfe_exit("
                    f"age={age},"
                    f"mfe={mfe:.2f},"
                    f"unreal={unrealized:.2f})"
                )

        # ── 1. Early loss time-stop (V131) ──────────────────────────────
        # Close losers that haven't recovered after N cycles. This fires BEFORE
        # the hard MAE stop to ensure loss_capture < 1.0: the position exits
        # while unrealized > mae (i.e., before it drifts to its absolute worst).
        if cfg.early_loss_time_stop and age >= cfg.early_loss_cycles:
            early_threshold = -(cfg.early_loss_k_atr * atr_dollars)
            if unrealized <= early_threshold:
                return True, (
                    f"early_loss_time_stop("
                    f"age={age},"
                    f"loss={unrealized:.2f},"
                    f"threshold={early_threshold:.2f},"
                    f"k={cfg.early_loss_k_atr}x_atr)"
                )

        # ── 2. Hard MAE stop ────────────────────────────────────────────
        stop_threshold = -(cfg.mae_stop_k * atr_dollars)
        if unrealized <= stop_threshold:
            return True, (
                f"hard_stop_mae("
                f"loss={unrealized:.2f},"
                f"threshold={stop_threshold:.2f},"
                f"k={cfg.mae_stop_k}x_atr)"
            )

        # ── 3. MFE trailing stop ────────────────────────────────────────
        # V132: respect trailing_stop_min_age — same guard as the legacy
        # trailing stop in paper_trading.py.  Without this, the MFE trail
        # fires at age 1-2 on whipsaw candles (price shoots up then crashes
        # below entry in one cycle), causing structural loss_capture=1.0
        # identical to the bug the age guard was meant to fix.
        # V141: side-specific trail multipliers — longs get tighter activation
        # (0.5× ATR), shorts get wider activation (1.5× ATR) to let them run.
        if age >= cfg.trailing_stop_min_age and not _below_min_hold:
            if position_side == "short":
                _trail_mult = cfg.short_trail_multiplier
            else:
                _trail_mult = cfg.long_trail_multiplier
            trail_activation = cfg.mfe_trail_k * _trail_mult * atr_dollars
            if mfe >= trail_activation:
                trail_level = mfe * (1.0 - cfg.mfe_retracement_cap)
                if unrealized < trail_level:
                    return True, (
                        f"mfe_trail("
                        f"mfe={mfe:.2f},"
                        f"trail={trail_level:.2f},"
                        f"unreal={unrealized:.2f},"
                        f"side={position_side},"
                        f"trail_mult={_trail_mult},"
                        f"cap={cfg.mfe_retracement_cap})"
                    )

            # V184 soft profit-lock: trail activates as soon as MFE > 0, no ATR
            # threshold required. Catches the V177 pattern where losers touched
            # positive MFE but reversed before the hard trail's K×ATR activation.
            if cfg.mfe_trailing_retracement > 0.0 and mfe > 0.0:
                soft_trail_level = mfe * cfg.mfe_trailing_retracement
                if unrealized < soft_trail_level:
                    return True, (
                        f"mfe_soft_trail("
                        f"mfe={mfe:.2f},"
                        f"lock={soft_trail_level:.2f},"
                        f"unreal={unrealized:.2f},"
                        f"retain={cfg.mfe_trailing_retracement})"
                    )

        return False, ""

    # ------------------------------------------------------------------
    # Exit telemetry
    # ------------------------------------------------------------------

    @staticmethod
    def compute_exit_telemetry(
        pnl: float,
        mfe: float,
        mae: float,
    ) -> dict[str, float | None]:
        """
        Compute per-trade exit quality metrics.

        win_capture   = pnl / mfe          (winners: 1.0 = captured 100% of peak)
        loss_capture  = |pnl| / |mae|      (losers:  1.0 = closed at worst point)
        exit_score    = win_capture − loss_capture

        A positive exit_score means we let winners run further than losers —
        the opposite of the disposition effect.
        """
        win_capture: float | None = None
        loss_capture: float | None = None

        if pnl > 0 and mfe > 0:
            win_capture = round(pnl / mfe, 4)

        if pnl < 0 and mae < 0:
            loss_capture = round(abs(pnl) / abs(mae), 4)

        if win_capture is not None and loss_capture is not None:
            exit_score: float | None = round(win_capture - loss_capture, 4)
        elif win_capture is not None:
            exit_score = win_capture  # only winners so far
        elif loss_capture is not None:
            exit_score = -loss_capture  # only losers so far
        else:
            exit_score = None

        return {
            "win_capture": win_capture,
            "loss_capture": loss_capture,
            "exit_score": exit_score,
        }


# ---------------------------------------------------------------------------
# Aggregate disposition coefficient
# ---------------------------------------------------------------------------


def aggregate_disposition(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute aggregate disposition coefficient from a list of closed trades.

    Uses exit_score column if present (V128+), otherwise falls back to
    win_capture/loss_capture computed from pnl/mfe/mae columns.

    Returns dict with:
        disposition_coefficient : median(win_capture) - median(loss_capture)
        mean_exit_score         : mean(exit_score) across all trades with data
        n_with_telemetry        : trades with exit_score available
    """
    win_caps: list[float] = []
    loss_caps: list[float] = []
    exit_scores: list[float] = []

    for t in trades:
        # Prefer pre-computed exit_score if present
        es = t.get("exit_score")
        if es is not None and es != "":
            with contextlib.suppress(TypeError, ValueError):
                exit_scores.append(float(es))

        # Always compute win/loss capture from pnl/mfe/mae for percentile stats
        pnl = float(t.get("pnl", 0) or 0)
        mfe = float(t.get("mfe", 0) or 0)
        mae = float(t.get("mae", 0) or 0)
        tel = ExitController.compute_exit_telemetry(pnl, mfe, mae)
        if tel["win_capture"] is not None:
            win_caps.append(tel["win_capture"])
        if tel["loss_capture"] is not None:
            loss_caps.append(tel["loss_capture"])

    def _median(vals: list[float]) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    med_win = _median(win_caps)
    med_loss = _median(loss_caps)

    if med_win is not None and med_loss is not None:
        disp_coef: float | None = round(med_win - med_loss, 4)
    elif med_win is not None:
        disp_coef = round(med_win, 4)
    elif med_loss is not None:
        disp_coef = round(-med_loss, 4)
    else:
        disp_coef = None

    mean_es: float | None = round(sum(exit_scores) / len(exit_scores), 4) if exit_scores else None

    return {
        "disposition_coefficient": disp_coef,
        "mean_exit_score": mean_es,
        "n_with_telemetry": len(exit_scores),
        "_n_win_captures": len(win_caps),
        "_n_loss_captures": len(loss_caps),
    }
