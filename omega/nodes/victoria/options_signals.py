"""
omega.nodes.victoria.options_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Options Microstructure Signal — exploiting mechanical market-maker hedging.

Jim Simons signal (alpha-edge research #1, score 17/20):
  Market makers must delta-hedge options, creating predictable flows.
  By mapping aggregate gamma exposure (GEX), we predict when markets
  will trend vs mean-revert.

Data source: Deribit public API (no auth required, 10 req/sec rate limit)
  GET https://www.deribit.com/api/v2/public/get_book_summary_by_currency
      ?currency=BTC&kind=option
  GET https://www.deribit.com/api/v2/public/get_index_price
      ?index_name=btc_usd

Sub-signals and composite weights:
  a) Gamma Exposure (GEX)    0.30 — market maker hedging direction
  b) Put/Call Ratio (PCR)    0.25 — sentiment extremes (contrarian)
  c) IV Skew                 0.20 — put vs call IV differential (fear premium)
  d) Max Pain                0.15 — price gravity toward max option writer profit
  e) Term Structure          0.10 — near vs far IV (backwardation = stress)

Composite ∈ [-1, +1]:
  +1 = strongly bullish (positive GEX + extreme put buying + high skew)
  -1 = strongly bearish (negative GEX + extreme call buying + backwardation)
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.options_signals")

# ── API endpoints ─────────────────────────────────────────────────────────────

_BOOK_URL = (
    "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
    "?currency={currency}&kind=option"
)
_INDEX_URL = "https://www.deribit.com/api/v2/public/get_index_price?index_name={index_name}"

# ── Constants ─────────────────────────────────────────────────────────────────

_CACHE_TTL = 60.0  # seconds — stay well within 10 req/sec limit
_REQUEST_TIMEOUT = 8.0  # seconds per request
_MIN_DTE = 1.0  # ignore options expiring in < 1 day (pin risk)
_NEAR_MONTH_MIN_DTE = 7.0  # near-month: > 7 DTE to avoid expiry pinning
_FAR_MONTH_MAX_DTE = 90.0  # far-month cap

# Sub-signal weights summing to 1.0
_COMPONENT_WEIGHTS: dict[str, float] = {
    "gex": 0.30,
    "pcr": 0.25,
    "skew": 0.20,
    "max_pain": 0.15,
    "term_structure": 0.10,
}

# PCR thresholds
_PCR_MID = 0.9  # neutral reference
_PCR_BEAR_THR = 1.2  # > 1.2 → extreme put buying → contrarian bullish
_PCR_BULL_THR = 0.6  # < 0.6 → extreme call buying → contrarian bearish

_SKEW_SCALE = 0.10  # 10 IV pp spread → max ±1 signal
_MAX_PAIN_SCALE = 0.05  # 5% spot distance → full signal
_RISK_FREE_RATE = 0.05  # annualised (~5% USD lending)


# ── Black-Scholes helpers ─────────────────────────────────────────────────────


def _normcdf(x: float) -> float:
    """Standard normal CDF via erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _normpdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_d1(
    spot: float,
    strike: float,
    sigma: float,
    t_years: float,
    r: float = _RISK_FREE_RATE,
) -> float:
    """Black-Scholes d1 parameter."""
    if spot <= 0 or strike <= 0 or sigma <= 0 or t_years <= 0:
        return 0.0
    return (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (
        sigma * math.sqrt(t_years)
    )


def _bs_gamma(spot: float, strike: float, sigma: float, t_years: float) -> float:
    """Black-Scholes gamma (identical for calls and puts)."""
    if spot <= 0 or sigma <= 0 or t_years <= 0:
        return 0.0
    d1 = _bs_d1(spot, strike, sigma, t_years)
    return _normpdf(d1) / (spot * sigma * math.sqrt(t_years))


def _bs_delta(
    spot: float,
    strike: float,
    sigma: float,
    t_years: float,
    is_call: bool,
) -> float:
    """Black-Scholes delta (absolute value returned for puts)."""
    if spot <= 0 or sigma <= 0 or t_years <= 0:
        return 0.5
    d1 = _bs_d1(spot, strike, sigma, t_years)
    call_delta = _normcdf(d1)
    raw = call_delta if is_call else call_delta - 1.0
    return abs(raw)


# ── Instrument model ──────────────────────────────────────────────────────────


@dataclass
class _OptionInstrument:
    """Parsed Deribit option instrument with pre-computed Greeks."""

    name: str
    strike: float
    is_call: bool
    dte: float  # days to expiry
    t_years: float  # dte / 365
    iv: float  # annualised IV (0.80 = 80%)
    oi: float  # open interest (in BTC)
    gamma: float  # Black-Scholes gamma
    delta: float  # abs(Black-Scholes delta)


def _parse_instrument_name(name: str) -> tuple[float, float, bool] | None:
    """
    Parse strike, DTE, and option type from a Deribit instrument name.

    Format: BTC-DDMMMYY-STRIKE-TYPE  e.g. BTC-25DEC26-100000-C
    Returns (strike, dte_days, is_call) or None on failure.
    """
    parts = name.split("-")
    if len(parts) < 4:
        return None
    try:
        # Parse expiry date from second part: e.g. "25DEC26"
        expiry_str = parts[1]  # "25DEC26"
        expiry_dt = datetime.strptime(expiry_str, "%d%b%y").replace(tzinfo=UTC)
        now_utc = datetime.now(tz=UTC)
        dte = (expiry_dt - now_utc).total_seconds() / 86400.0

        strike = float(parts[2])
        is_call = parts[3].upper() == "C"
        return strike, dte, is_call
    except (ValueError, IndexError):
        return None


def _parse_book_summary(
    items: list[dict[str, Any]],
    spot: float,
) -> list[_OptionInstrument]:
    """Convert raw Deribit book-summary entries to _OptionInstrument objects."""
    result: list[_OptionInstrument] = []

    for item in items:
        name = item.get("instrument_name", "")
        parsed = _parse_instrument_name(name)
        if parsed is None:
            continue
        strike, dte, is_call = parsed

        if dte < _MIN_DTE:
            continue  # skip expired / pinning options

        # Deribit mark_iv is a percentage (e.g. 80.0 → 0.80)
        mark_iv_raw = item.get("mark_iv")
        if not mark_iv_raw or mark_iv_raw <= 0:
            continue
        iv = mark_iv_raw / 100.0

        oi = float(item.get("open_interest") or 0.0)
        if oi <= 0:
            continue  # skip zero-OI instruments

        t_years = dte / 365.0
        gamma = _bs_gamma(spot, strike, iv, t_years)
        delta = _bs_delta(spot, strike, iv, t_years, is_call=is_call)

        result.append(
            _OptionInstrument(
                name=name,
                strike=strike,
                is_call=is_call,
                dte=dte,
                t_years=t_years,
                iv=iv,
                oi=oi,
                gamma=gamma,
                delta=delta,
            )
        )
    return result


# ── Sub-signal computations ───────────────────────────────────────────────────


def _gex_signal(
    instruments: list[_OptionInstrument],
    spot: float,
) -> tuple[float, dict[str, float]]:
    """
    Gamma Exposure (GEX).

    GEX_i = OI_i * gamma_i * spot^2 * 0.01
    Net GEX = sum(call GEX) - sum(put GEX)

    Above the gamma flip:
      - Market makers are net-long gamma → they buy dips / sell rips.
      - Price is range-bound; positive GEX → mild bullish signal.
    Below the gamma flip:
      - Market makers are net-short gamma → they sell into falls.
      - Trends amplified; negative GEX → bearish signal.
    """
    strike_gex: dict[float, float] = {}
    total_call_gex = 0.0
    total_put_gex = 0.0

    for inst in instruments:
        gex = inst.oi * inst.gamma * spot * spot * 0.01
        if inst.is_call:
            total_call_gex += gex
            strike_gex[inst.strike] = strike_gex.get(inst.strike, 0.0) + gex
        else:
            total_put_gex += gex
            strike_gex[inst.strike] = strike_gex.get(inst.strike, 0.0) - gex

    net_gex = total_call_gex - total_put_gex
    total_abs_gex = total_call_gex + total_put_gex

    # Gamma flip: lowest strike where cumulative GEX (sorted ascending) crosses 0
    gamma_flip = spot
    if strike_gex:
        sorted_strikes = sorted(strike_gex.keys())
        cumulative = 0.0
        for k in sorted_strikes:
            prev = cumulative
            cumulative += strike_gex[k]
            if prev != 0.0 and prev * cumulative <= 0.0:
                gamma_flip = k
                break

    above_flip = spot >= gamma_flip

    # Normalise net_gex to [-1, +1] using fraction of total absolute GEX
    if total_abs_gex > 0:
        gex_ratio = net_gex / total_abs_gex
    else:
        gex_ratio = 0.0

    # Signal direction follows net GEX: positive GEX = bullish (MM buys dips)
    value = float(max(-1.0, min(1.0, gex_ratio)))

    # Confidence: how far spot is from the flip (further = clearer regime)
    flip_dist_pct = abs(spot - gamma_flip) / max(spot, 1.0)
    confidence = float(min(1.0, flip_dist_pct / 0.05))

    raw: dict[str, float] = {
        "net_gex": net_gex,
        "call_gex": total_call_gex,
        "put_gex": total_put_gex,
        "gamma_flip": gamma_flip,
        "gex_ratio": gex_ratio,
        "above_flip": float(above_flip),
        "confidence": confidence,
    }
    return value, raw


def _pcr_signal(
    instruments: list[_OptionInstrument],
) -> tuple[float, dict[str, float]]:
    """
    Put/Call Ratio — contrarian sentiment signal.

    PCR = total_put_OI / total_call_OI
    > 1.2 → extreme fear / put buying → contrarian bullish
    < 0.6 → extreme greed / call buying → contrarian bearish
    """
    put_oi = sum(i.oi for i in instruments if not i.is_call)
    call_oi = sum(i.oi for i in instruments if i.is_call)

    if call_oi < 1.0:
        return 0.0, {"put_oi": put_oi, "call_oi": call_oi, "pcr": 0.0, "confidence": 0.0}

    pcr = put_oi / call_oi

    if pcr >= _PCR_BEAR_THR:
        # Extreme fear → contrarian bullish, scale up above threshold
        excess = (pcr - _PCR_BEAR_THR) / 0.3
        value = float(min(1.0, 0.6 + excess * 0.4))
    elif pcr <= _PCR_BULL_THR:
        # Extreme greed → contrarian bearish
        deficit = (_PCR_BULL_THR - pcr) / 0.2
        value = float(max(-1.0, -(0.6 + deficit * 0.4)))
    else:
        # Between thresholds: linear, positive PCR excess = mild bullish
        value = float((_PCR_MID - pcr) / (_PCR_MID - _PCR_BULL_THR) * 0.3)

    total_oi = put_oi + call_oi
    confidence = float(min(1.0, total_oi / 10_000.0))  # 10k BTC OI = max

    raw: dict[str, float] = {
        "put_oi": put_oi,
        "call_oi": call_oi,
        "pcr": pcr,
        "confidence": confidence,
    }
    return float(max(-1.0, min(1.0, value))), raw


def _skew_signal(
    instruments: list[_OptionInstrument],
) -> tuple[float, dict[str, float]]:
    """
    IV Skew — 25-delta put IV minus 25-delta call IV.

    Positive skew = puts expensive = fear premium.
    High positive skew is contrarian bullish; negative (calls expensive) = greed.
    Uses nearest-month options (7-45 DTE).
    """
    # Near-month filter
    near = [i for i in instruments if _NEAR_MONTH_MIN_DTE <= i.dte <= 45.0]
    if not near:
        near = [i for i in instruments if i.dte >= _NEAR_MONTH_MIN_DTE]
    if not near:
        empty: dict[str, float] = {
            "skew": 0.0,
            "put_25d_iv": 0.0,
            "call_25d_iv": 0.0,
            "near_dte": 0.0,
            "confidence": 0.0,
        }
        return 0.0, empty

    # Group by nearest expiry (allow ±3 DTE)
    min_dte = min(i.dte for i in near)
    expiry_group = [i for i in near if abs(i.dte - min_dte) < 3.0]

    # Closest to 0.25 delta
    puts_25d = sorted(
        [i for i in expiry_group if not i.is_call], key=lambda i: abs(i.delta - 0.25)
    )
    calls_25d = sorted([i for i in expiry_group if i.is_call], key=lambda i: abs(i.delta - 0.25))

    if not puts_25d or not calls_25d:
        empty = {
            "skew": 0.0,
            "put_25d_iv": 0.0,
            "call_25d_iv": 0.0,
            "near_dte": min_dte,
            "confidence": 0.0,
        }
        return 0.0, empty

    put_iv = puts_25d[0].iv
    call_iv = calls_25d[0].iv
    skew = put_iv - call_iv  # positive = fear

    # Contrarian interpretation: high fear (positive skew) → bullish
    # Scale: _SKEW_SCALE IV pp → ±1
    normalized = skew / _SKEW_SCALE
    value = float(max(-1.0, min(1.0, -normalized)))  # flip sign for contrarian

    # Confidence: penalise if chosen option is far from 0.25 delta
    put_err = abs(puts_25d[0].delta - 0.25)
    call_err = abs(calls_25d[0].delta - 0.25)
    avg_err = (put_err + call_err) / 2.0
    confidence = float(max(0.0, 1.0 - avg_err / 0.10))

    raw: dict[str, float] = {
        "skew": skew,
        "put_25d_iv": put_iv,
        "call_25d_iv": call_iv,
        "near_dte": min_dte,
        "put_delta": puts_25d[0].delta,
        "call_delta": calls_25d[0].delta,
        "confidence": confidence,
    }
    return value, raw


def _max_pain_signal(
    instruments: list[_OptionInstrument],
    spot: float,
) -> tuple[float, dict[str, float]]:
    """
    Max Pain — strike where option holders' aggregate losses are maximised.

    Price gravitates toward max pain near expiry as market makers minimise payouts.
    Distance-to-max-pain predicts mean reversion direction.

    For each candidate expiry price P:
      MM payout = Σ max(0, P - K_call) * OI_call
                + Σ max(0, K_put  - P) * OI_put
    Max pain = P that minimises total MM payout.
    """
    # Use nearest expiry with > 7 DTE
    near_dtes = sorted({i.dte for i in instruments if i.dte >= _NEAR_MONTH_MIN_DTE})
    if not near_dtes:
        return 0.0, {"max_pain_strike": spot, "distance_pct": 0.0, "confidence": 0.0}

    target_dte = near_dtes[0]
    near = [i for i in instruments if abs(i.dte - target_dte) < 3.0]
    if not near:
        return 0.0, {"max_pain_strike": spot, "distance_pct": 0.0, "confidence": 0.0}

    # Build per-strike OI maps
    call_oi: dict[float, float] = {}
    put_oi: dict[float, float] = {}
    for inst in near:
        if inst.is_call:
            call_oi[inst.strike] = call_oi.get(inst.strike, 0.0) + inst.oi
        else:
            put_oi[inst.strike] = put_oi.get(inst.strike, 0.0) + inst.oi

    strikes = sorted(set(call_oi) | set(put_oi))
    if not strikes:
        return 0.0, {"max_pain_strike": spot, "distance_pct": 0.0, "confidence": 0.0}

    # Find max pain strike (minimise total MM payout)
    min_payout = float("inf")
    max_pain_strk = strikes[0]
    for p in strikes:
        call_payout = sum(max(0.0, p - k) * oi for k, oi in call_oi.items())
        put_payout = sum(max(0.0, k - p) * oi for k, oi in put_oi.items())
        total = call_payout + put_payout
        if total < min_payout:
            min_payout = total
            max_pain_strk = p

    # Signal: positive distance (max pain above spot) → expect upside reversion
    distance_pct = (max_pain_strk - spot) / max(spot, 1.0)
    value = float(max(-1.0, min(1.0, distance_pct / _MAX_PAIN_SCALE)))

    # Confidence: total OI * DTE proximity (closer to expiry = stronger pull)
    total_oi = sum(call_oi.values()) + sum(put_oi.values())
    oi_conf = float(min(1.0, total_oi / 5_000.0))
    dte_decay = float(max(0.0, 1.0 - target_dte / 30.0))  # peaks at expiry
    confidence = oi_conf * (0.5 + 0.5 * dte_decay)

    raw: dict[str, float] = {
        "max_pain_strike": max_pain_strk,
        "spot": spot,
        "distance_pct": distance_pct,
        "target_dte": target_dte,
        "confidence": confidence,
    }
    return value, raw


def _term_structure_signal(
    instruments: list[_OptionInstrument],
    spot: float,
) -> tuple[float, dict[str, Any]]:
    """
    Term structure — near-month vs far-month ATM IV.

    Contango   (far > near): normal expectations, mild bullish
    Flat                   : neutral
    Backwardation (near > far): stress / anticipated big move, bearish

    Returns OI-weighted ATM IV for each tenor.
    """
    near_dtes = sorted({i.dte for i in instruments if i.dte > _NEAR_MONTH_MIN_DTE})
    far_dtes = sorted({i.dte for i in instruments if 30.0 < i.dte <= _FAR_MONTH_MAX_DTE})

    if not near_dtes or not far_dtes:
        empty: dict[str, Any] = {
            "near_iv": 0.0,
            "far_iv": 0.0,
            "spread": 0.0,
            "relative_spread": 0.0,
            "near_dte": 0.0,
            "far_dte": 0.0,
            "structure": "unknown",
            "confidence": 0.0,
        }
        return 0.0, empty

    near_dte = near_dtes[0]
    far_dte = far_dtes[-1]

    if near_dte >= far_dte:
        empty = {
            "near_iv": 0.0,
            "far_iv": 0.0,
            "spread": 0.0,
            "relative_spread": 0.0,
            "near_dte": near_dte,
            "far_dte": far_dte,
            "structure": "unknown",
            "confidence": 0.0,
        }
        return 0.0, empty

    def _atm_iv(dte_target: float) -> float | None:
        group = [i for i in instruments if abs(i.dte - dte_target) < 3.0]
        if not group:
            return None
        total_w = 0.0
        weighted_iv = 0.0
        for inst in group:
            moneyness = abs(inst.strike - spot) / max(spot, 1.0)
            atm_w = math.exp(-moneyness / 0.05)  # weight decays with distance from ATM
            w = inst.oi * atm_w
            weighted_iv += inst.iv * w
            total_w += w
        return weighted_iv / total_w if total_w > 0 else None

    near_iv = _atm_iv(near_dte)
    far_iv = _atm_iv(far_dte)

    if near_iv is None or far_iv is None or near_iv <= 0:
        empty = {
            "near_iv": 0.0,
            "far_iv": 0.0,
            "spread": 0.0,
            "relative_spread": 0.0,
            "near_dte": near_dte,
            "far_dte": far_dte,
            "structure": "unknown",
            "confidence": 0.0,
        }
        return 0.0, empty

    spread = far_iv - near_iv
    relative_spread = spread / near_iv

    # Backwardation (stress) → bearish; contango (normal) → mild bullish
    # Scale: ±0.15 relative spread → ±1.0 signal
    value = float(max(-1.0, min(1.0, relative_spread / 0.15)))

    if spread > 0.005:
        structure = "contango"
    elif spread < -0.005:
        structure = "backwardation"
    else:
        structure = "flat"

    # Confidence: need both tenors well-populated
    near_count = sum(1 for i in instruments if abs(i.dte - near_dte) < 3.0)
    far_count = sum(1 for i in instruments if abs(i.dte - far_dte) < 3.0)
    confidence = float(min(1.0, min(near_count, far_count) / 5.0))

    raw: dict[str, Any] = {
        "near_iv": near_iv,
        "far_iv": far_iv,
        "spread": spread,
        "relative_spread": relative_spread,
        "near_dte": near_dte,
        "far_dte": far_dte,
        "structure": structure,
        "confidence": confidence,
    }
    return value, raw


# ── Main provider class ───────────────────────────────────────────────────────


class OptionsSignalProvider:
    """
    Options microstructure signal provider.

    Fetches BTC options chain from Deribit public API (no auth required)
    and produces a composite signal for the Victoria node.

    Sub-signals: GEX (0.30) + PCR (0.25) + IV Skew (0.20)
                 + Max Pain (0.15) + Term Structure (0.10)

    Cache TTL: 60 seconds (well within Deribit's 10 req/sec public limit).
    Graceful degradation: returns value=0, confidence=0 on any failure.
    """

    def __init__(
        self,
        currency: str = "BTC",
        timeout: float = _REQUEST_TIMEOUT,
    ) -> None:
        self._currency = currency.upper()
        self._timeout = timeout

        # (data, fetched_at) cache pairs
        self._book_cache: tuple[list[dict[str, Any]], float] | None = None
        self._spot_cache: tuple[float, float] | None = None

        self._call_count = 0
        self._error_count = 0

    # ── Public interface ──────────────────────────────────────────────────────

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        """
        Compute options microstructure signal.

        Parameters
        ----------
        market_data : dict | None
            VictoriaNode market_data dict — used as spot-price fallback if
            the Deribit index endpoint is unreachable.

        Returns
        -------
        SignalValue
            value      ∈ [-1, +1]
            confidence ∈ [0,  1]
            regime_tag ∈ {"positive_gex", "negative_gex", "fear_extreme",
                           "greed_extreme", "term_backwardation", "neutral",
                           "no_data", "unavailable"}
            raw        : sub-signal values + underlying metrics
        """
        self._call_count += 1
        try:
            return self._compute_internal(market_data)
        except Exception as exc:
            self._error_count += 1
            logger.warning("OptionsSignalProvider.compute failed: %s", exc, exc_info=True)
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="unavailable",
                raw={"error": 1.0},  # sentinel; str preserved in regime_tag
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_internal(self, market_data: dict[str, Any] | None) -> SignalValue:
        spot = self._get_spot(market_data)
        book = self._get_book()

        if not book or spot <= 0:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="no_data",
                raw={"spot": spot, "n_instruments": 0},
            )

        instruments = _parse_book_summary(book, spot)
        n = len(instruments)

        if n < 10:
            logger.debug("options_signals: only %d instruments, skipping", n)
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="insufficient_instruments",
                raw={"spot": spot, "n_instruments": n},
            )

        # ── Sub-signal computation ────────────────────────────────────────────
        gex_val, gex_raw = _gex_signal(instruments, spot)
        pcr_val, pcr_raw = _pcr_signal(instruments)
        skew_val, skew_raw = _skew_signal(instruments)
        pain_val, pain_raw = _max_pain_signal(instruments, spot)
        ts_val, ts_raw = _term_structure_signal(instruments, spot)

        # ── Composite ─────────────────────────────────────────────────────────
        composite = (
            _COMPONENT_WEIGHTS["gex"] * gex_val
            + _COMPONENT_WEIGHTS["pcr"] * pcr_val
            + _COMPONENT_WEIGHTS["skew"] * skew_val
            + _COMPONENT_WEIGHTS["max_pain"] * pain_val
            + _COMPONENT_WEIGHTS["term_structure"] * ts_val
        )

        # ── Confidence ────────────────────────────────────────────────────────
        # Base: fraction of 50 expected liquid instruments
        base_conf = float(min(1.0, n / 50.0))

        # ── Regime ────────────────────────────────────────────────────────────
        regime = self._classify_regime(gex_raw, pcr_raw, skew_raw, ts_raw)

        # ── Build raw dict (all float values for DB persistence) ──────────────
        raw: dict[str, Any] = {
            "gex_signal": float(gex_val),
            "pcr_signal": float(pcr_val),
            "skew_signal": float(skew_val),
            "pain_signal": float(pain_val),
            "ts_signal": float(ts_val),
            "spot": float(spot),
            "n_instruments": float(n),
            # GEX details
            "net_gex": float(gex_raw.get("net_gex", 0.0)),
            "gamma_flip": float(gex_raw.get("gamma_flip", 0.0)),
            "above_flip": float(gex_raw.get("above_flip", 0.0)),
            # PCR details
            "pcr": float(pcr_raw.get("pcr", 0.0)),
            "put_oi": float(pcr_raw.get("put_oi", 0.0)),
            "call_oi": float(pcr_raw.get("call_oi", 0.0)),
            # Skew details
            "iv_skew": float(skew_raw.get("skew", 0.0)),
            "put_25d_iv": float(skew_raw.get("put_25d_iv", 0.0)),
            "call_25d_iv": float(skew_raw.get("call_25d_iv", 0.0)),
            # Max Pain details
            "max_pain_strike": float(pain_raw.get("max_pain_strike", spot)),
            "pain_distance_pct": float(pain_raw.get("distance_pct", 0.0)),
            # Term structure details
            "near_iv": float(ts_raw.get("near_iv", 0.0)),
            "far_iv": float(ts_raw.get("far_iv", 0.0)),
            "ts_spread": float(ts_raw.get("spread", 0.0)),
        }

        logger.info(
            "options_signals: composite=%.4f regime=%s n=%d "
            "gex=%.3f pcr=%.3f skew=%.3f pain=%.3f ts=%.3f "
            "(spot=%.0f flip=%.0f pcr_val=%.2f iv_skew=%.3f)",
            composite,
            regime,
            n,
            gex_val,
            pcr_val,
            skew_val,
            pain_val,
            ts_val,
            spot,
            gex_raw.get("gamma_flip", 0.0),
            pcr_raw.get("pcr", 0.0),
            skew_raw.get("skew", 0.0),
        )

        return SignalValue(
            value=float(max(-1.0, min(1.0, composite))),
            confidence=base_conf,
            regime_tag=regime,
            raw=raw,
        )

    def _classify_regime(
        self,
        gex_raw: dict[str, float],
        pcr_raw: dict[str, float],
        skew_raw: dict[str, Any],
        ts_raw: dict[str, Any],
    ) -> str:
        """Classify market regime from options microstructure."""
        structure = str(ts_raw.get("structure", "flat"))
        pcr = float(pcr_raw.get("pcr", _PCR_MID))
        net_gex = float(gex_raw.get("net_gex", 0.0))

        if structure == "backwardation":
            return "term_backwardation"
        if pcr >= _PCR_BEAR_THR:
            return "fear_extreme"
        if pcr <= _PCR_BULL_THR:
            return "greed_extreme"
        if net_gex > 0:
            return "positive_gex"
        if net_gex < 0:
            return "negative_gex"
        return "neutral"

    # ── Data fetching ─────────────────────────────────────────────────────────

    def _get_spot(self, market_data: dict[str, Any] | None) -> float:
        """
        Resolve BTC spot price.

        Priority: cached value → Deribit index → market_data close prices.
        """
        # Return cached value if fresh
        if self._spot_cache is not None:
            price, ts = self._spot_cache
            if time.time() - ts < _CACHE_TTL:
                return price

        # 1. Deribit index price
        try:
            index_name = f"{self._currency.lower()}_usd"
            url = _INDEX_URL.format(index_name=index_name)
            req = urllib.request.Request(url, headers={"User-Agent": "omega-options/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
            price = float(data["result"]["index_price"])
            if price > 0:
                self._spot_cache = (price, time.time())
                return price
        except Exception as exc:
            logger.debug("Deribit index price fetch failed: %s", exc)

        # 2. market_data fallback (last close of any BTC ticker)
        if market_data:
            for ticker, td in market_data.items():
                if "BTC" in ticker.upper() and isinstance(td, dict):
                    closes = td.get("close", [])
                    if closes:
                        price = float(closes[-1])
                        if price > 0:
                            self._spot_cache = (price, time.time())
                            return price

        return 0.0

    def _get_book(self) -> list[dict[str, Any]]:
        """
        Fetch BTC options book summary from Deribit (60-second cache).

        Returns stale cached data if a fresh fetch fails.
        """
        if self._book_cache is not None:
            book, ts = self._book_cache
            if time.time() - ts < _CACHE_TTL:
                return book

        try:
            url = _BOOK_URL.format(currency=self._currency)
            req = urllib.request.Request(url, headers={"User-Agent": "omega-options/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
            result: list[dict[str, Any]] = data.get("result", [])
            book = result
            if not isinstance(book, list):
                logger.warning("Unexpected Deribit book format: %s", type(book))
                return []
            self._book_cache = (book, time.time())
            logger.debug("Fetched %d BTC options from Deribit", len(book))
            return book
        except Exception as exc:
            logger.warning("Deribit book summary fetch failed: %s", exc)
            # Return stale cache rather than empty (graceful degradation)
            if self._book_cache is not None:
                book, _ = self._book_cache
                return book
            return []
