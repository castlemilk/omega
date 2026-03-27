"""
omega.nodes.polymarket.vol_arb
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
VolArbNode — volatility arbitrage for Polymarket binary options.

Two detection modes
-------------------
1. **Both-sides spread arb**: when YES + NO prices sum > 1.00, selling both
   sides locks in premium against a guaranteed $1.00 payout. Flagged when
   combined premium > ``spread_threshold`` (default 1.01).

2. **Implied vol arb**: for crypto price-prediction markets ("BTC above $X by Y"),
   compute implied volatility from the binary option price via the digital
   Black-Scholes formula, compare to 30-day realized vol from Binance, and flag
   when implied >> realized by more than ``vol_premium_threshold`` (default 20%).

Regime guard
------------
When BTC moves > 5 % in the last hour we skip vol-sell signals — avoids selling
into a genuine breakout (the Christensen & Prabhala caveat).

Observational only — no execution. Opportunities are logged and appended to
``data/polymarket_vol_arb_opportunities.json``.

References
----------
- Christensen & Prabhala (1998). "The relation between implied and realized
  volatility." J. Financial Economics 50(2), 125–150.
- browomo (2025). Polymarket volatility harvester thread.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.polymarket.vol_arb")

# ── API endpoints ──────────────────────────────────────────────────────────────

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
BINANCE_API = "https://api.binance.com/api/v3"
USER_AGENT = "omega-polymarket-vol-arb/1.0"
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

# ── Thresholds ─────────────────────────────────────────────────────────────────

SPREAD_ARB_THRESHOLD: float = 1.01    # flag when YES+NO > 1.01 (1 % net profit)
VOL_PREMIUM_THRESHOLD: float = 0.20   # flag when implied_vol > realized * 1.20
REGIME_GUARD_PCT: float = 0.05        # skip vol-sell if BTC 1h move > 5 %
REALIZED_VOL_DAYS: int = 30           # rolling window for realized vol

# ── Output path ────────────────────────────────────────────────────────────────

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
OUTPUT_PATH = os.path.join(_REPO_ROOT, "data", "polymarket_vol_arb_opportunities.json")

# ── Market keyword filters ─────────────────────────────────────────────────────

_CRYPTO_KEYWORDS = [
    "btc", "bitcoin", "eth ", "ethereum", "sol ", "solana",
    "crypto", "above $", "below $", "will reach", "price target",
]
_CRYPTO_BLOCKLIST = ["ethan", "bethlehem", " seth ", "meteorological"]

_SYMBOL_MAP: dict[str, str] = {
    "bitcoin": "BTCUSDT",
    "btc":     "BTCUSDT",
    "ethereum": "ETHUSDT",
    "eth":     "ETHUSDT",
    "solana":  "SOLUSDT",
    "sol":     "SOLUSDT",
}


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class VolArbOpportunity:
    market_id: str
    question: str
    yes_price: float
    no_price: float
    arb_type: str               # "spread_arb" | "vol_arb" | "synthetic"
    implied_vol: float | None = None
    realized_vol: float | None = None
    vol_premium_pct: float | None = None
    spread: float | None = None
    recommended_action: str = ""
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ── Node ───────────────────────────────────────────────────────────────────────


class VolArbNode(Node):
    """
    Volatility arbitrage scanner for Polymarket binary options.

    Actions
    -------
    vol_arb / scan   — run full scan, return summary + opportunities list
    """

    def __init__(
        self,
        spread_threshold: float = SPREAD_ARB_THRESHOLD,
        vol_premium_threshold: float = VOL_PREMIUM_THRESHOLD,
    ) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._opportunities_detected = 0
        self.spread_threshold = spread_threshold
        self.vol_premium_threshold = vol_premium_threshold
        self._cache: dict[str, tuple[float, Any]] = {}

    # ── Node protocol ──────────────────────────────────────────────────────────

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="VolArbNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={
                "spread_threshold": self.spread_threshold,
                "vol_premium_threshold": self.vol_premium_threshold,
                "opportunities_detected": self._opportunities_detected,
            },
        )

    def get_capabilities(self) -> list[str]:
        return [NodeAction.VOL_ARB.value, "scan", "vol_arb"]

    def describe(self) -> str:
        return (
            "Volatility arbitrage for Polymarket binary options. Detects both-sides "
            "spread arb and implied-vol >> realized-vol opportunities. "
            "Observational only — no execution."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action.lower()
        cycle = int(inp.context.get("cycle", 0))

        result: Any = None
        try:
            if action in (NodeAction.VOL_ARB.value, "scan", "vol_arb"):
                result = self._scan(cycle)
            else:
                raise ValueError(
                    f"Unknown action '{action}'. Supported: {self.get_capabilities()}"
                )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.warning("VolArbNode error: %s", exc)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

        elapsed = (time.perf_counter() - t0) * 1000
        self._total_latency_ms += elapsed
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": elapsed},
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "opportunities_detected": float(self._opportunities_detected),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False
        if "spread_threshold" in feedback:
            new = float(feedback["spread_threshold"])
            if new != self.spread_threshold:
                self.spread_threshold = new
                changed = True
        if "vol_premium_threshold" in feedback:
            new = float(feedback["vol_premium_threshold"])
            if new != self.vol_premium_threshold:
                self.vol_premium_threshold = new
                changed = True
        return changed

    # ── Core scan ─────────────────────────────────────────────────────────────

    def _scan(self, cycle: int) -> dict[str, Any]:
        """Run the full vol-arb scan. Returns summary with opportunities list."""
        opportunities: list[VolArbOpportunity] = []

        # Pull live data in parallel order (separate calls, no shared state)
        markets = self._fetch_crypto_markets()
        realized_vols = self._fetch_realized_vols(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        in_breakout = self._detect_breakout("BTCUSDT")

        for mkt in markets:
            yes_p = mkt["yes_price"]
            no_p = mkt["no_price"]
            combined = yes_p + no_p

            # ── Mode 1: both-sides spread arb ─────────────────────────────────
            if combined > self.spread_threshold:
                net = combined - 1.0
                opp = VolArbOpportunity(
                    market_id=mkt["market_id"],
                    question=mkt["question"],
                    yes_price=yes_p,
                    no_price=no_p,
                    arb_type="spread_arb",
                    spread=round(net, 4),
                    recommended_action=(
                        f"SELL BOTH: YES at {yes_p:.2f} + NO at {no_p:.2f} = "
                        f"{combined:.3f} collected vs $1.00 payout → +{net*100:.1f}¢ net"
                    ),
                )
                opportunities.append(opp)
                logger.info(
                    "SPREAD ARB | %s | YES=%.3f NO=%.3f sum=%.3f net=+%.3f",
                    mkt["question"][:70], yes_p, no_p, combined, net,
                )

            # ── Mode 2: implied vol arb (skip during BTC breakout) ────────────
            if not in_breakout:
                symbol = _detect_symbol(mkt["question"])
                if symbol and symbol in realized_vols:
                    rv = realized_vols[symbol]
                    iv = self._compute_implied_vol(mkt)
                    if iv is not None and rv > 1e-6:
                        premium = (iv - rv) / rv
                        if premium > self.vol_premium_threshold:
                            # Sell the more expensive side
                            if yes_p >= no_p:
                                sell_side, sell_price = "YES", yes_p
                            else:
                                sell_side, sell_price = "NO", no_p
                            opp = VolArbOpportunity(
                                market_id=mkt["market_id"],
                                question=mkt["question"],
                                yes_price=yes_p,
                                no_price=no_p,
                                arb_type="vol_arb",
                                implied_vol=round(iv, 4),
                                realized_vol=round(rv, 4),
                                vol_premium_pct=round(premium * 100, 1),
                                recommended_action=(
                                    f"SELL {sell_side} at {sell_price:.2f}: "
                                    f"implied vol {iv*100:.0f}%, realized vol {rv*100:.0f}%, "
                                    f"+{premium*100:.0f}% vol premium"
                                ),
                            )
                            opportunities.append(opp)
                            logger.info(
                                "VOL ARB | %s | IV=%.0f%% RV=%.0f%% premium=+%.0f%% — SELL %s at %.2f",
                                mkt["question"][:70],
                                iv * 100, rv * 100, premium * 100,
                                sell_side, sell_price,
                            )

        # ── Synthetic fallback when Gamma API returns no matching markets ──────
        # Constructs representative scenarios from live Binance data so the node
        # produces meaningful output even when live Polymarket markets are sparse.
        if not markets and realized_vols:
            opportunities.extend(self._synthetic_scenarios(realized_vols, in_breakout, cycle))

        self._save_opportunities(opportunities, cycle)
        self._opportunities_detected += len(opportunities)

        summary: dict[str, Any] = {
            "cycle": cycle,
            "markets_scanned": len(markets),
            "opportunities": len(opportunities),
            "spread_arbs": sum(1 for o in opportunities if o.arb_type == "spread_arb"),
            "vol_arbs": sum(1 for o in opportunities if o.arb_type == "vol_arb"),
            "synthetic": sum(1 for o in opportunities if o.arb_type == "synthetic"),
            "in_breakout_regime": in_breakout,
            "realized_vols": {k: round(v, 4) for k, v in realized_vols.items()},
            "details": [o.to_dict() for o in opportunities],
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "vol_arb scan: cycle=%d markets=%d opps=%d "
            "(spread=%d vol=%d synthetic=%d) breakout=%s",
            cycle, len(markets), len(opportunities),
            summary["spread_arbs"], summary["vol_arbs"], summary["synthetic"],
            in_breakout,
        )
        return summary

    # ── Implied vol computation ────────────────────────────────────────────────

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Standard normal CDF via Abramowitz & Stegun (1964) approximation.
        Max error: 7.5e-8.
        """
        if x < 0:
            return 1.0 - VolArbNode._norm_cdf(-x)
        k = 1.0 / (1.0 + 0.2316419 * x)
        poly = k * (
            0.319381530
            + k * (-0.356563782
            + k * (1.781477937
            + k * (-1.821255978
            + k * 1.330274429)))
        )
        return 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly

    def _binary_call_price(self, S: float, K: float, T: float, sigma: float) -> float:
        """
        Digital call option price under Black-Scholes (r = 0):
            P = N(d2),  d2 = [ln(S/K) − ½σ²T] / (σ√T)
        """
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return 0.5
        d2 = (math.log(S / K) - 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
        return self._norm_cdf(d2)

    def _implied_vol_bisect(
        self,
        market_price: float,
        S: float,
        K: float,
        T: float,
        lo: float = 0.01,
        hi: float = 20.0,
        n_iter: int = 60,
    ) -> float | None:
        """Bisection solver for implied vol from a binary call price."""
        # Extreme prices → near-certain outcome, not a vol signal
        if not (0.02 < market_price < 0.98):
            return None
        if T <= 1e-6:
            return None

        f_lo = self._binary_call_price(S, K, T, lo) - market_price
        f_hi = self._binary_call_price(S, K, T, hi) - market_price

        if f_lo * f_hi > 0:
            # No root in [lo, hi] — deep ITM/OTM with no vol solution
            return None

        for _ in range(n_iter):
            mid = (lo + hi) / 2.0
            f_mid = self._binary_call_price(S, K, T, mid) - market_price
            if abs(f_mid) < 1e-7:
                return mid
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo = mid
                f_lo = f_mid

        return (lo + hi) / 2.0

    def _compute_implied_vol(self, mkt: dict[str, Any]) -> float | None:
        """
        Compute annualised implied vol from the market's YES price.
        Returns None if the market can't be parsed as a crypto price prediction.
        """
        symbol = _detect_symbol(mkt["question"])
        if not symbol:
            return None
        S = self._get_spot_price(symbol)
        if S is None:
            return None
        K = _parse_strike(mkt["question"])
        if K is None or K <= 0:
            return None
        T = _parse_time_to_expiry(mkt)
        if T is None or T <= 0:
            return None
        return self._implied_vol_bisect(mkt["yes_price"], S, K, T)

    # ── Realized vol ──────────────────────────────────────────────────────────

    def _fetch_realized_vols(self, symbols: list[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        for sym in symbols:
            rv = self._realized_vol_binance(sym)
            if rv is not None:
                result[sym] = rv
        return result

    def _realized_vol_binance(self, symbol: str) -> float | None:
        """Fetch REALIZED_VOL_DAYS daily closes → annualised realized vol."""
        cache_key = f"rv:{symbol}"
        cached = self._get_cached(cache_key, ttl=300)
        if cached is not None:
            return float(cached)

        url = (
            f"{BINANCE_API}/klines"
            f"?symbol={symbol}&interval=1d&limit={REALIZED_VOL_DAYS + 1}"
        )
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("Binance klines failed for %s: %s", symbol, exc)
            return None

        if not raw or len(raw) < 3:
            return None

        closes = [float(k[4]) for k in raw]
        log_rets = [
            math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        if len(log_rets) < 2:
            return None

        mean = sum(log_rets) / len(log_rets)
        variance = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
        rv = math.sqrt(variance) * math.sqrt(252)  # annualise

        self._set_cached(cache_key, rv)
        return rv

    # ── Regime guard ──────────────────────────────────────────────────────────

    def _detect_breakout(self, symbol: str) -> bool:
        """Return True if symbol moved > REGIME_GUARD_PCT on the last 1h candle."""
        cache_key = f"breakout:{symbol}"
        cached = self._get_cached(cache_key, ttl=300)
        if cached is not None:
            return bool(cached)

        url = f"{BINANCE_API}/klines?symbol={symbol}&interval=1h&limit=2"
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("Breakout check failed for %s: %s", symbol, exc)
            return False

        if not raw:
            return False

        last = raw[-1]
        open_p, close_p = float(last[1]), float(last[4])
        if open_p <= 0:
            return False

        pct = abs(close_p - open_p) / open_p
        is_breakout = pct > REGIME_GUARD_PCT

        if is_breakout:
            logger.info(
                "REGIME GUARD: %s 1h move=%.1f%% > %.0f%% — skipping vol-sell signals",
                symbol, pct * 100, REGIME_GUARD_PCT * 100,
            )

        self._set_cached(cache_key, is_breakout)
        return is_breakout

    # ── Market fetching ───────────────────────────────────────────────────────

    def _fetch_crypto_markets(self) -> list[dict[str, Any]]:
        """Fetch active Polymarket markets for crypto price predictions."""
        cache_key = "crypto_markets"
        cached = self._get_cached(cache_key, ttl=120)
        if cached is not None:
            return list(cached)

        markets: list[dict[str, Any]] = []
        seen: set[str] = set()

        for page in range(5):
            url = (
                f"{GAMMA_API_BASE}/markets"
                f"?active=true&closed=false&limit=100&offset={page * 100}"
            )
            try:
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as exc:
                logger.warning("Gamma API page %d fetch failed: %s", page, exc)
                break

            raw_list = data if isinstance(data, list) else data.get("markets", [])
            if not raw_list:
                break

            for raw in raw_list:
                mid = str(raw.get("conditionId", raw.get("id", "")))
                if mid in seen:
                    continue
                parsed = self._parse_market(raw)
                if parsed:
                    seen.add(mid)
                    markets.append(parsed)

            if len(markets) >= 20:
                break  # enough to analyse

        logger.debug("vol_arb: %d crypto markets from Gamma API", len(markets))
        self._set_cached(cache_key, markets)
        return markets

    def _parse_market(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        question = raw.get("question", raw.get("title", ""))
        if not _is_crypto_market(question):
            return None

        yes_price, no_price = 0.5, 0.5
        tokens = raw.get("tokens", [])
        if len(tokens) >= 2:
            for tok in tokens:
                outcome = str(tok.get("outcome", "")).lower()
                price = float(tok.get("price", 0.5))
                if outcome == "yes":
                    yes_price = price
                elif outcome == "no":
                    no_price = price
        elif "outcomePrices" in raw:
            prices_raw = raw["outcomePrices"]
            if isinstance(prices_raw, list) and len(prices_raw) >= 2:
                try:
                    yes_price = float(prices_raw[0])
                    no_price = float(prices_raw[1])
                except (TypeError, ValueError):
                    pass

        return {
            "market_id": str(raw.get("conditionId", raw.get("id", ""))),
            "question": question,
            "yes_price": round(yes_price, 4),
            "no_price": round(no_price, 4),
            "end_date": raw.get("endDate", raw.get("endDateIso", "")),
            "active": raw.get("active", True),
        }

    # ── Spot price ────────────────────────────────────────────────────────────

    def _get_spot_price(self, symbol: str) -> float | None:
        cache_key = f"spot:{symbol}"
        cached = self._get_cached(cache_key, ttl=30)
        if cached is not None:
            return float(cached)

        url = f"{BINANCE_API}/ticker/price?symbol={symbol}"
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            price = float(data["price"])
            self._set_cached(cache_key, price)
            return price
        except Exception as exc:
            logger.debug("Spot price fetch failed for %s: %s", symbol, exc)
            return None

    # ── Synthetic scenarios ────────────────────────────────────────────────────

    def _synthetic_scenarios(
        self,
        realized_vols: dict[str, float],
        in_breakout: bool,
        cycle: int,
    ) -> list[VolArbOpportunity]:
        """
        Generate representative vol-arb scenarios from live Binance data when
        the Gamma API returns no matching crypto markets.

        Constructs hypothetical "BTC above $K by end-of-month" markets with
        prices derived from Black-Scholes, then artificially inflates implied vol
        to simulate panic conditions — demonstrating what the scanner would flag.
        """
        opps: list[VolArbOpportunity] = []
        scenarios = [
            ("BTCUSDT", 1.05,  7 / 365.0, 0.55,  "Will BTC be above {K:,.0f} by next week?"),
            ("BTCUSDT", 0.95,  7 / 365.0, 0.52,  "Will BTC stay above {K:,.0f} through April?"),
            ("ETHUSDT", 1.10, 14 / 365.0, 0.45,  "Will ETH exceed {K:,.0f} before end of month?"),
            ("SOLUSDT", 0.90,  5 / 365.0, 0.58,  "Will SOL drop below {K:,.0f} this week?"),
        ]

        for symbol, k_mult, T, yes_p, q_tmpl in scenarios:
            S = self._get_spot_price(symbol)
            if S is None:
                continue
            K = round(S * k_mult, -2)  # round to nearest 100
            rv = realized_vols.get(symbol)
            if rv is None:
                continue

            question = q_tmpl.format(K=K)
            iv = self._implied_vol_bisect(yes_p, S, K, T)

            if iv is not None and not in_breakout:
                premium = (iv - rv) / rv if rv > 1e-6 else 0.0
                if premium > self.vol_premium_threshold:
                    sell_side = "YES" if yes_p >= 1 - yes_p else "NO"
                    sell_price = yes_p if sell_side == "YES" else round(1 - yes_p, 4)
                    opp = VolArbOpportunity(
                        market_id=f"synthetic_{symbol}_{cycle}",
                        question=question,
                        yes_price=yes_p,
                        no_price=round(1 - yes_p - 0.03, 4),  # simulate 3% spread
                        arb_type="synthetic",
                        implied_vol=round(iv, 4),
                        realized_vol=round(rv, 4),
                        vol_premium_pct=round(premium * 100, 1),
                        recommended_action=(
                            f"[SYNTHETIC] SELL {sell_side} at {sell_price:.2f}: "
                            f"implied vol {iv*100:.0f}%, realized vol {rv*100:.0f}%, "
                            f"+{premium*100:.0f}% vol premium | S={S:,.0f} K={K:,.0f} T={T*365:.0f}d"
                        ),
                    )
                    opps.append(opp)
                    logger.info(
                        "SYNTHETIC VOL ARB | %s | S=%.0f K=%.0f IV=%.0f%% RV=%.0f%% +%.0f%%",
                        symbol, S, K, iv * 100, rv * 100, premium * 100,
                    )

        return opps

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_opportunities(
        self, opps: list[VolArbOpportunity], cycle: int
    ) -> None:
        if not opps:
            return

        existing: list[dict[str, Any]] = []
        try:
            if os.path.exists(OUTPUT_PATH):
                with open(OUTPUT_PATH) as f:
                    existing = json.load(f)
        except Exception:
            existing = []

        new_entries = [{**o.to_dict(), "cycle": cycle} for o in opps]
        combined = existing + new_entries
        if len(combined) > 1000:
            combined = combined[-1000:]

        try:
            os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
            with open(OUTPUT_PATH, "w") as f:
                json.dump(combined, f, indent=2)
            logger.debug("Saved %d vol-arb opportunities to %s", len(new_entries), OUTPUT_PATH)
        except Exception as exc:
            logger.warning("Failed to save opportunities: %s", exc)

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _get_cached(self, key: str, ttl: int = 120) -> Any:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < ttl:
                return val
        return None

    def _set_cached(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time(), val)


# ── Module-level pure helpers (no self, easily testable) ──────────────────────


def _is_crypto_market(question: str) -> bool:
    q = question.lower()
    if any(bl in q for bl in _CRYPTO_BLOCKLIST):
        return False
    return any(kw in q for kw in _CRYPTO_KEYWORDS)


def _detect_symbol(question: str) -> str | None:
    """Return the Binance pair (e.g. 'BTCUSDT') mentioned in a market question."""
    q = question.lower()
    # Check longer tokens first to avoid 'eth' matching 'ethereum'
    for kw in sorted(_SYMBOL_MAP, key=len, reverse=True):
        if kw in q:
            return _SYMBOL_MAP[kw]
    return None


def _parse_strike(question: str) -> float | None:
    """
    Extract a numeric price target from a market question.
    Handles: $70,000 | $70K | 70000 USD | above 70000 | will reach 95000
    """
    patterns = [
        r'\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)([kK]?)',
        r'([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:usd|usdt|dollars?)\b',
        r'(?:above|below|reach|hit|exceed|surpass|cross)\s+\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)([kK]?)',
    ]
    for pat in patterns:
        m = re.search(pat, question, re.IGNORECASE)
        if m:
            num_str = m.group(1).replace(",", "")
            try:
                val = float(num_str)
                # Handle K suffix in group 2 when present
                if len(m.groups()) >= 2 and m.group(2) and m.group(2).lower() == "k":
                    val *= 1000
                if 0.0001 < val < 10_000_000:
                    return val
            except ValueError:
                continue
    return None


def _parse_time_to_expiry(mkt: dict[str, Any]) -> float | None:
    """Return time to expiry in years from the market's end_date field."""
    end_str = mkt.get("end_date", "")
    if not end_str:
        return 30.0 / 365.0  # default: 30 days

    fmts = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        trimmed = end_str[: len(fmt)]
        try:
            end_dt = datetime.strptime(trimmed, fmt)
            delta_s = (end_dt - datetime.utcnow()).total_seconds()
            if delta_s <= 0:
                return None
            return delta_s / (365.25 * 24 * 3600)
        except ValueError:
            continue

    return 30.0 / 365.0  # fallback
