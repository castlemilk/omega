"""
omega.nodes.victoria.stablecoin_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Stablecoin flow signal — tracks USDT + USDC circulating supply changes as a
1-2 day leading indicator for crypto market direction.

  Rising supply  → new fiat entering crypto → bullish (capital inflow)
  Falling supply → redemptions / capital exit → bearish

Data sources (free, no auth required):
  - DeFiLlama:  https://stablecoins.llama.fi/stablecoins  (primary)
  - CoinGecko:  /coins/tether  +  /coins/usd-coin  (fallback)
  - Pre-fetched: market_data["_stablecoin_data"]  (injected by DataIngestion)

Signal output: SignalValue with value in [-1, +1]
  +0.7 to +1.0 : supply increasing + large mints detected -> strong bullish
  -0.7 to -1.0 : supply decreasing + large burns detected -> strong bearish
  ≈ 0.0        : flat supply, neutral

Integration:
  Fed into DynamicWeightAllocator as signal "stablecoin_flow" with initial
  equal weight (converges to ≈15% as IC stabilises over cycles).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.stablecoin_signals")

_DEFILLAMA_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=false"

# Large mint/burn threshold: $100M change in supply = leading indicator
_LARGE_MINT_THRESHOLD = 100_000_000


class StablecoinFlowSignal:
    """
    Stablecoin supply flow signal.

    Tracks combined USDT + USDC circulating supply changes from DeFiLlama
    (primary) with a CoinGecko fallback.  Supply changes are the most
    reliable free proxy for new capital entering / leaving crypto.

    Usage::
        signal = StablecoinFlowSignal()
        sv = signal.compute(market_data)
        conviction = sv.value  # -1.0 .. +1.0
    """

    def __init__(self) -> None:
        # Cache previous total supply for inter-cycle change detection
        self._prev_total_supply: float | None = None

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        raw: dict[str, float] = {}

        # ── 1. Data acquisition ──────────────────────────────────────────────
        sc_data: dict[str, Any] | None = market_data.get("_stablecoin_data")
        if sc_data is None:
            sc_data = self._fetch_stablecoin_data()

        if sc_data is None:
            return SignalValue(value=0.0, confidence=0.0, regime_tag="no_data", raw=raw)

        # ── 2. Parse supply figures ──────────────────────────────────────────
        total_supply = float(sc_data.get("total_supply", 0.0))
        usdt_supply = float(sc_data.get("usdt_supply", 0.0))
        usdc_supply = float(sc_data.get("usdc_supply", 0.0))
        supply_change_24h: float | None = sc_data.get("supply_change_24h")
        usdt_change_usd = float(sc_data.get("usdt_change_24h_usd", 0.0))
        usdc_change_usd = float(sc_data.get("usdc_change_24h_usd", 0.0))

        raw["total_stablecoin_supply_usd"] = total_supply
        raw["usdt_supply_usd"] = usdt_supply
        raw["usdc_supply_usd"] = usdc_supply

        # Inter-cycle change estimate when API doesn't provide 24h delta
        if supply_change_24h is None and self._prev_total_supply and total_supply > 0:
            supply_change_24h = (total_supply - self._prev_total_supply) / self._prev_total_supply

        if total_supply > 0:
            self._prev_total_supply = total_supply

        if supply_change_24h is None:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="insufficient_data",
                raw=raw,
            )

        # ── 3. Core supply-change signal ─────────────────────────────────────
        # +2% daily -> full bull (+1.0); -2% daily -> full bear (-1.0)
        pct_24h = float(supply_change_24h)
        raw["supply_change_24h_pct"] = round(pct_24h * 100, 4)
        supply_signal = max(-1.0, min(1.0, pct_24h * 50.0))

        # ── 4. Large mint/burn boost (4-12h leading indicator) ───────────────
        combined_change_usd = usdt_change_usd + usdc_change_usd
        raw["stablecoin_net_mint_24h_usd"] = combined_change_usd

        mint_boost = 0.0
        if combined_change_usd > _LARGE_MINT_THRESHOLD:
            # Scales: $100M → +0.03, $1B → +0.3 (capped)
            mint_boost = min(0.3, combined_change_usd / 1_000_000_000)
            raw["large_mint_detected"] = 1.0
        elif combined_change_usd < -_LARGE_MINT_THRESHOLD:
            mint_boost = max(-0.3, combined_change_usd / 1_000_000_000)
            raw["large_burn_detected"] = 1.0

        # ── 5. Composite value ───────────────────────────────────────────────
        value = max(-1.0, min(1.0, supply_signal * 0.8 + mint_boost * 0.2))

        # Confidence scales with magnitude of supply change
        # 0% change → 0.2 floor; ≥1.3% change → 1.0 ceiling
        magnitude = abs(pct_24h)
        confidence = min(1.0, magnitude * 100 * 0.6 + 0.2)

        # ── 6. Regime tag ────────────────────────────────────────────────────
        if value >= 0.7:
            regime_tag = "strong_inflow"
        elif value >= 0.3:
            regime_tag = "mild_inflow"
        elif value <= -0.7:
            regime_tag = "strong_outflow"
        elif value <= -0.3:
            regime_tag = "mild_outflow"
        else:
            regime_tag = "stablecoin_neutral"

        raw["final_signal"] = round(value, 4)

        logger.debug(
            "stablecoin_flow: supply_Δ24h=%.4f%% value=%.3f confidence=%.3f regime=%s",
            pct_24h * 100,
            value,
            confidence,
            regime_tag,
        )
        return SignalValue(
            value=value,
            confidence=confidence,
            regime_tag=regime_tag,
            raw=raw,
        )

    # ── Data fetchers ────────────────────────────────────────────────────────

    def _fetch_stablecoin_data(self) -> dict[str, Any] | None:
        """Try DeFiLlama first; fall back to CoinGecko."""
        try:
            return self._fetch_defillama()
        except Exception as exc:
            logger.debug("DeFiLlama stablecoin fetch failed: %s", exc)
        try:
            return self._fetch_coingecko()
        except Exception as exc:
            logger.debug("CoinGecko stablecoin fallback failed: %s", exc)
        return None

    def _fetch_defillama(self) -> dict[str, Any]:
        """
        Fetch stablecoin supply from DeFiLlama.

        DeFiLlama returns per-asset data including circulatingPrevDay which
        lets us compute exact 24h supply changes for USDT and USDC.
        """
        req = urllib.request.Request(_DEFILLAMA_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        stables = data.get("peggedAssets", [])
        total = usdt = usdc = usdt_prev = usdc_prev = 0.0

        for asset in stables:
            sym = str(asset.get("symbol", "")).upper()
            circ = asset.get("circulating") or {}
            pegged = float(circ.get("peggedUSD", 0.0))
            total += pegged
            prev_day_circ = asset.get("circulatingPrevDay") or {}
            prev = float(prev_day_circ.get("peggedUSD", 0.0))
            if sym == "USDT":
                usdt = pegged
                usdt_prev = prev
            elif sym == "USDC":
                usdc = pegged
                usdc_prev = prev

        combined_now = usdt + usdc
        combined_prev = usdt_prev + usdc_prev
        supply_change_24h: float | None = (
            (combined_now - combined_prev) / combined_prev if combined_prev > 0 else None
        )
        return {
            "total_supply": total,
            "usdt_supply": usdt,
            "usdc_supply": usdc,
            "supply_change_24h": supply_change_24h,
            "usdt_change_24h_usd": usdt - usdt_prev,
            "usdc_change_24h_usd": usdc - usdc_prev,
            "source": "defillama",
        }

    def _fetch_coingecko(self) -> dict[str, Any]:
        """
        Fallback: fetch USDT + USDC market cap from CoinGecko.

        Uses market_cap_change_24h as a proxy for supply change USD.
        """
        results: dict[str, float] = {}
        for coin_id, key in [("tether", "usdt"), ("usd-coin", "usdc")]:
            url = (
                f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                "?localization=false&tickers=false&market_data=true"
                "&community_data=false&developer_data=false"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            md = data.get("market_data", {})
            results[f"{key}_supply"] = float(md.get("circulating_supply", 0.0))
            results[f"{key}_change_usd"] = float(md.get("market_cap_change_24h", 0.0))

        usdt = results.get("usdt_supply", 0.0)
        usdc = results.get("usdc_supply", 0.0)
        usdt_chg = results.get("usdt_change_usd", 0.0)
        usdc_chg = results.get("usdc_change_usd", 0.0)
        combined_change = usdt_chg + usdc_chg
        total = usdt + usdc

        return {
            "total_supply": total,
            "usdt_supply": usdt,
            "usdc_supply": usdc,
            "supply_change_24h": (combined_change / total if total > 0 else None),
            "usdt_change_24h_usd": usdt_chg,
            "usdc_change_24h_usd": usdc_chg,
            "source": "coingecko",
        }
