"""
omega.nodes.victoria.signals.llm_analyst
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LLM-as-analyst conviction modifier for Victoria (V139).

The LLM acts as a senior analyst, not a decision-maker. It returns a
conviction_modifier in [0.0, 1.5] that scales the IC-weighted composite
before threshold comparison. The quant system retains full veto authority.

    modifier < 0.5  → LLM veto   (entry blocked regardless of quant score)
    modifier < 1.0  → analyst is cautious  (reduces effective conviction)
    modifier = 1.0  → analyst is neutral   (no change — also the fallback)
    modifier > 1.0  → analyst sees upside  (amplifies conviction)

Feature flag: llm_analyst_enabled (V139)
Cache: data/cache/llm_analyst/{sha256_16}.json (no TTL — deterministic by input)
Log:  data/llm_analyst_log/{version}.jsonl (one JSON per call)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_ROOT = Path(__file__).resolve().parents[5] / "data" / "cache" / "llm_analyst"
_LOG_ROOT = Path(__file__).resolve().parents[5] / "data" / "llm_analyst_log"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_TOKENS = 300
_TIMEOUT_SECONDS = 10

# Signals to include in the prompt (top by |value|, plus macro always)
_MACRO_SIGNALS = {"vix_signal", "dxy_signal", "yield_curve_signal", "spy_signal"}
_MAX_SIGNALS_IN_PROMPT = 8


@dataclass
class LLMAnalystResult:
    conviction_modifier: float = 1.0
    reasoning: str = ""
    regime_override: str | None = None      # parsed but not applied in Phase 1
    signal_adjustments: dict[str, float] = field(default_factory=dict)  # parsed, not applied
    confidence: float = 0.5
    cached: bool = False
    latency_ms: float = 0.0


class LLMAnalystSignal:
    """Compute LLM conviction modifier for a single ticker.

    Call compute() every N cycles (controlled by llm_analyst_call_every_n).
    Results are SHA256-keyed to the full input payload for deterministic replay.
    Every live (non-cached) API call is appended to the JSONL log.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        cache_root: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._model = model
        self._cache_root = cache_root or _CACHE_ROOT
        self._log_path: Path | None = log_path
        self._api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")

    def set_log_path(self, version: str) -> None:
        """Set per-version JSONL log path (call from strategy.py after version is known)."""
        _LOG_ROOT.mkdir(parents=True, exist_ok=True)
        self._log_path = _LOG_ROOT / f"{version}.jsonl"

    def compute(
        self,
        ticker: str,
        direction: str,
        regime: str,
        composite: float,
        weighted_conviction: float,
        signals: dict[str, float],
        bear_prob: float = 0.0,
        bull_prob: float = 0.0,
        last_trades: list[dict[str, Any]] | None = None,
        open_positions: dict[str, Any] | None = None,
        cycle: int = 0,
        timestamp: datetime | None = None,
    ) -> LLMAnalystResult:
        """Return conviction modifier for the given market context.

        Falls back to modifier=1.0 on any error (API unavailable, parse failure,
        missing API key). Never raises.
        """
        if not self._api_key:
            return LLMAnalystResult(conviction_modifier=1.0, reasoning="no_api_key")

        t0 = time.monotonic()
        payload = self._build_payload(
            ticker, direction, regime, composite, weighted_conviction,
            signals, bear_prob, bull_prob, last_trades, open_positions,
            cycle, timestamp,
        )
        key = self._cache_key(payload)

        cached = self._cache_load(key)
        if cached is not None:
            cached.cached = True
            cached.latency_ms = round((time.monotonic() - t0) * 1000, 1)
            return cached

        try:
            raw = self._call_api(payload)
            result = self._parse_response(raw)
            self._cache_store(key, result)
            result.latency_ms = round((time.monotonic() - t0) * 1000, 1)
            self._log_call(payload, result, cache_hit=False)
            return result
        except Exception as exc:
            logger.debug("llm_analyst error for %s: %s", ticker, exc)
            return LLMAnalystResult(
                conviction_modifier=1.0,
                reasoning=f"error:{type(exc).__name__}",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
            )

    # ------------------------------------------------------------------
    # Payload / prompt construction
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        ticker: str,
        direction: str,
        regime: str,
        composite: float,
        weighted_conviction: float,
        signals: dict[str, float],
        bear_prob: float,
        bull_prob: float,
        last_trades: list[dict[str, Any]] | None,
        open_positions: dict[str, Any] | None,
        cycle: int,
        timestamp: datetime | None,
    ) -> dict[str, Any]:
        ts_str = (timestamp or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Select top signals by |value|, always include macro signals
        macro = {k: round(float(signals.get(k, 0.0)), 4) for k in _MACRO_SIGNALS if k in signals}
        other = {
            k: round(float(v), 4)
            for k, v in signals.items()
            if k not in _MACRO_SIGNALS and not k.startswith("_") and isinstance(v, (int, float))
        }
        top_other = dict(sorted(other.items(), key=lambda kv: abs(kv[1]), reverse=True)[:_MAX_SIGNALS_IN_PROMPT])
        selected_signals = {**macro, **top_other}

        # L/S balance from open positions
        long_count = short_count = 0
        if open_positions:
            for pos in open_positions.values():
                side = pos.get("side", "") if isinstance(pos, dict) else ""
                if side == "long":
                    long_count += 1
                elif side == "short":
                    short_count += 1

        # Last 5 closed trades with outcome + reasoning
        recent_trades: list[dict] = []
        if last_trades:
            for t in list(last_trades)[-5:]:
                if not isinstance(t, dict):
                    continue
                recent_trades.append({
                    "ticker": t.get("symbol", t.get("ticker", "?")),
                    "side": t.get("side", "?"),
                    "pnl": round(float(t.get("pnl", 0.0)), 2),
                    "hold_cycles": t.get("hold_cycles", "?"),
                    "reasoning": str(t.get("reasoning", ""))[:100] if t.get("reasoning") else "",
                })

        # Geo signals
        geo = {
            k: round(float(signals.get(k, 0.0)), 3)
            for k in ("geo_event_intensity", "geo_sentiment", "geo_regime_shift", "sanctions_signal")
            if k in signals
        }

        return {
            "_model": self._model,
            "ticker": ticker,
            "direction": direction,
            "regime": regime,
            "composite": round(composite, 5),
            "weighted_conviction": round(weighted_conviction, 5),
            "bear_prob": round(bear_prob, 3),
            "bull_prob": round(bull_prob, 3),
            "signals": selected_signals,
            "geo": geo,
            "open_positions": {"long": long_count, "short": short_count},
            "recent_trades": recent_trades,
            "cycle": cycle,
            "timestamp": ts_str,
        }

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        sig_lines = "\n".join(
            f"  {k}: {v:+.4f}" for k, v in payload["signals"].items()
        )
        geo_str = ""
        if payload.get("geo"):
            geo_str = "\nGeopolitical signals:\n" + "\n".join(
                f"  {k}: {v}" for k, v in payload["geo"].items()
            )

        trades_str = ""
        if payload["recent_trades"]:
            trades_str = "\nLast 5 trades:\n" + "\n".join(
                f"  {t['ticker']} {t['side']} pnl=${t['pnl']:+.0f} hold={t['hold_cycles']}c"
                + (f" | {t['reasoning']}" if t["reasoning"] else "")
                for t in payload["recent_trades"]
            )

        positions_str = (
            f"\nOpen positions: {payload['open_positions']['long']}L / "
            f"{payload['open_positions']['short']}S"
        )

        return (
            f"You are a senior crypto quant analyst reviewing a trade proposal.\n\n"
            f"Ticker: {payload['ticker']}\n"
            f"Proposal: {payload['direction'].upper()}\n"
            f"Market regime: {payload['regime']} "
            f"(bear_prob={payload['bear_prob']:.2f}, bull_prob={payload['bull_prob']:.2f})\n"
            f"Quant composite: {payload['composite']:+.5f}  "
            f"weighted_conviction: {payload['weighted_conviction']:+.5f}\n"
            f"Signals:\n{sig_lines}"
            f"{geo_str}"
            f"{trades_str}"
            f"{positions_str}\n\n"
            f"Your task: return a JSON object with these exact keys:\n"
            f"  conviction_modifier: float in [0.0, 1.5]\n"
            f"    < 0.5 = veto this trade entirely\n"
            f"    0.5–1.0 = cautious (reduces effective conviction)\n"
            f"    1.0 = neutral (no change)\n"
            f"    > 1.0 = amplify (macro/narrative supports quant signal)\n"
            f"  reasoning: 1 sentence, max 80 chars\n"
            f"  confidence: float in [0.0, 1.0]\n\n"
            f"Respond with ONLY the JSON object, no other text."
        )

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_key(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _cache_path(self, key: str) -> Path:
        return self._cache_root / f"{key}.json"

    def _cache_load(self, key: str) -> LLMAnalystResult | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return LLMAnalystResult(
                conviction_modifier=float(data.get("conviction_modifier", 1.0)),
                reasoning=data.get("reasoning", ""),
                regime_override=data.get("regime_override"),
                signal_adjustments=data.get("signal_adjustments", {}),
                confidence=float(data.get("confidence", 0.5)),
            )
        except Exception:
            return None

    def _cache_store(self, key: str, result: LLMAnalystResult) -> None:
        try:
            self._cache_root.mkdir(parents=True, exist_ok=True)
            data = {
                "conviction_modifier": result.conviction_modifier,
                "reasoning": result.reasoning,
                "regime_override": result.regime_override,
                "signal_adjustments": result.signal_adjustments,
                "confidence": result.confidence,
            }
            self._cache_path(key).write_text(json.dumps(data))
        except Exception as exc:
            logger.debug("llm_analyst cache write failed: %s", exc)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_call(self, payload: dict[str, Any], result: LLMAnalystResult, cache_hit: bool) -> None:
        if self._log_path is None:
            return
        try:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "ticker": payload["ticker"],
                "direction": payload["direction"],
                "regime": payload["regime"],
                "cycle": payload["cycle"],
                "composite": payload["composite"],
                "bear_prob": payload["bear_prob"],
                "modifier": result.conviction_modifier,
                "reasoning": result.reasoning,
                "confidence": result.confidence,
                "cached": cache_hit,
                "latency_ms": result.latency_ms,
            }
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("llm_analyst log write failed: %s", exc)

    # ------------------------------------------------------------------
    # API call (urllib, same pattern as brain.py)
    # ------------------------------------------------------------------

    def _call_api(self, payload: dict[str, Any]) -> str:
        prompt = self._build_prompt(payload)
        body = json.dumps({
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            _API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key or "",
                "anthropic-version": _ANTHROPIC_VERSION,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            raw = json.loads(resp.read().decode())
        return raw["content"][0]["text"]

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, text: str) -> LLMAnalystResult:
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned.strip())
            modifier = float(data.get("conviction_modifier", 1.0))
            modifier = max(0.0, min(1.5, modifier))
            return LLMAnalystResult(
                conviction_modifier=modifier,
                reasoning=str(data.get("reasoning", ""))[:120],
                regime_override=data.get("regime_override"),
                signal_adjustments=data.get("signal_adjustments", {}),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
            )
        except Exception as exc:
            logger.debug("llm_analyst parse failed: %s — raw: %r", exc, text[:200])
            return LLMAnalystResult(conviction_modifier=1.0, reasoning="parse_error")
