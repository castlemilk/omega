"""
omega.nodes.victoria.signals.llm_analyst
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LLM-as-analyst conviction modifier for Victoria (V139).

The LLM acts as a senior analyst, not a decision-maker. It returns a
conviction_modifier in [0.0, 1.5] that scales the IC-weighted composite
before threshold comparison. The quant system retains full authority.

    modifier < 1.0  → analyst is cautious  (reduces effective conviction)
    modifier = 1.0  → analyst is neutral   (no change — also the fallback)
    modifier > 1.0  → analyst sees upside  (amplifies conviction)

Feature flag: llm_analyst_enabled (V139)
Cache: data/cache/llm_analyst/{sha256_16}.json (no TTL — deterministic by input)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_ROOT = Path(__file__).resolve().parents[5] / "data" / "cache" / "llm_analyst"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_TOKENS = 256
_TIMEOUT_SECONDS = 10


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

    Designed to be called every N cycles (controlled by llm_analyst_call_every_n).
    Results are SHA256-keyed to the full input payload for deterministic replay.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        cache_root: Path | None = None,
    ) -> None:
        self._model = model
        self._cache_root = cache_root or _CACHE_ROOT
        self._api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")

    def compute(
        self,
        ticker: str,
        regime: str,
        composite: float,
        proposal: str,
        signals: dict[str, float],
        bear_prob: float = 0.0,
        bull_prob: float = 0.0,
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
            ticker, regime, composite, proposal, signals, bear_prob, bull_prob, timestamp
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
        regime: str,
        composite: float,
        proposal: str,
        signals: dict[str, float],
        bear_prob: float,
        bull_prob: float,
        timestamp: datetime | None,
    ) -> dict[str, Any]:
        ts_str = (timestamp or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        top_signals = sorted(signals.items(), key=lambda kv: abs(kv[1]), reverse=True)[:6]
        return {
            "_model": self._model,
            "ticker": ticker,
            "regime": regime,
            "composite": round(composite, 4),
            "proposal": proposal,
            "bear_prob": round(bear_prob, 3),
            "bull_prob": round(bull_prob, 3),
            "top_signals": {k: round(v, 4) for k, v in top_signals},
            "timestamp": ts_str,
        }

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        sig_lines = "\n".join(
            f"  {k}: {v:+.4f}" for k, v in payload["top_signals"].items()
        )
        return (
            f"You are a senior crypto quant analyst reviewing a trade proposal.\n\n"
            f"Ticker: {payload['ticker']}\n"
            f"Proposal: {payload['proposal']}\n"
            f"Market regime: {payload['regime']} "
            f"(bear_prob={payload['bear_prob']:.2f}, bull_prob={payload['bull_prob']:.2f})\n"
            f"Quant composite score: {payload['composite']:+.4f}\n"
            f"Top signals:\n{sig_lines}\n\n"
            f"Your task: return a JSON object with these exact keys:\n"
            f"  conviction_modifier: float in [0.0, 1.5] — scale the quant score "
            f"(1.0=neutral, <1=cautious, >1=amplify)\n"
            f"  reasoning: 1-sentence explanation (max 80 chars)\n"
            f"  confidence: float in [0.0, 1.0] — your confidence in this assessment\n\n"
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
            # Strip markdown fences if present
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
