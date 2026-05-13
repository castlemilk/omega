"""LLM arbitration helpers — tie-breaker + risk-scaling.

Two LLM-call helpers ported from TradingAgents (`docs/research/
tradingagents-evaluation.md`) but compressed into single-call form
that fits Victoria's 15-min cadence:

* `tiebreaker_decision()` — fires only when the three-sub-strategy
  ensemble vote returns "abstain". Asks an LLM to arbitrate using the
  same signal_dict plus the three sub-votes. Returns {direction,
  conviction, reasoning}.

* `risk_scaling_decision()` — fires only for high-conviction trades
  (size_mult >= 0.5). Asks an LLM whether to scale the trade by 0.5×,
  1.0×, or 1.5× given the recent loser MAE/MFE pattern. Returns
  {scale, reasoning}.

Both helpers share a thin OpenAI-compatible client (re-uses
`signals.llm_analyst.OpenAICompatibleProvider` semantics, but with a
shorter timeout and different prompt schema). Failures degrade
gracefully: tie-breaker → "flat", risk-scaling → 1.0× pass-through.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.llm_arbitration")

_DEFAULT_PROVIDER = "deepseek"
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_API_BASE = "https://api.deepseek.com/v1"
_DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
_DEFAULT_TIMEOUT = 8  # seconds — must fit inside a 15-min cycle comfortably


# ---------------------------------------------------------------------------
# Low-level call
# ---------------------------------------------------------------------------


def _call_llm(
    prompt: str,
    *,
    model: str = _DEFAULT_MODEL,
    api_base: str = _DEFAULT_API_BASE,
    api_key_env: str = _DEFAULT_API_KEY_ENV,
    timeout: int = _DEFAULT_TIMEOUT,
    max_tokens: int = 200,
) -> dict[str, Any] | None:
    """Single OpenAI-compatible chat completion. Returns parsed JSON or None."""
    api_key = (os.environ.get(api_key_env) or "").strip()
    if not api_key:
        return None
    endpoint = (
        api_base
        if api_base.endswith("/chat/completions") or "chatcompletion" in api_base
        else f"{api_base.rstrip('/')}/chat/completions"
    )
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode())
    except Exception as exc:
        logger.debug("llm_arbitration call failed: %s", exc)
        return None
    choices = raw.get("choices") or []
    if not choices:
        return None
    text = choices[0]["message"]["content"]
    # Strip code fences if the model added them
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Last-ditch: find the first {...} block
        try:
            start = stripped.index("{")
            end = stripped.rindex("}") + 1
            return json.loads(stripped[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.debug("llm_arbitration JSON parse failed: %r", text[:200])
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compact_signals(signals: dict[str, Any], keep: int = 12) -> dict[str, float]:
    """Keep at most `keep` non-zero numerical signals, largest |value| first."""
    items: list[tuple[str, float]] = []
    for k, v in signals.items():
        if isinstance(v, (int, float)) and v != 0.0 and not k.startswith("_"):
            items.append((k, float(v)))
    items.sort(key=lambda kv: abs(kv[1]), reverse=True)
    return {k: round(v, 4) for k, v in items[:keep]}


def _recent_outcomes(closed_trades: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    """Compress the last N closed trades into prompt-friendly dicts."""
    out: list[dict[str, Any]] = []
    for t in (closed_trades or [])[-n:]:
        out.append(
            {
                "symbol": t.get("symbol") or t.get("sym"),
                "side": t.get("side"),
                "pnl": round(float(t.get("pnl", 0) or 0), 2),
                "regime": t.get("regime"),
                "hold": t.get("hold_cycles"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Tie-breaker
# ---------------------------------------------------------------------------


def tiebreaker_decision(
    signals: dict[str, Any],
    sub_votes: list[Any],
    regime: str,
    closed_trades: list[dict[str, Any]] | None = None,
    *,
    model: str = _DEFAULT_MODEL,
) -> dict[str, Any]:
    """Resolve a split ensemble vote with an LLM.

    Returns dict with keys: direction ("long"/"short"/"flat"),
    conviction (0..1), reasoning (str). On failure returns flat-with-zero.
    """
    votes_repr = [
        {"name": getattr(v, "name", "?"), "direction": getattr(v, "direction", "?"),
         "conviction": round(float(getattr(v, "conviction", 0.0)), 3)}
        for v in sub_votes
    ]
    prompt = (
        "You arbitrate a split decision in a crypto ensemble strategy.\n"
        f"Regime: {regime}\n"
        f"Sub-strategy votes (momentum / mean_reversion / macro): {votes_repr}\n"
        f"Active signals (largest first): {_compact_signals(signals)}\n"
        f"Last 5 closed trades: {_recent_outcomes(closed_trades or [])}\n"
        "\n"
        "Given the disagreement, should the system go LONG, SHORT, or stay FLAT?\n"
        "If conviction is below 0.5, prefer FLAT. Be conservative.\n"
        "Return ONLY a JSON object with keys direction, conviction, reasoning. "
        "direction is one of \"long\", \"short\", \"flat\". conviction is a float "
        "in [0,1]. reasoning is at most 80 characters."
    )
    response = _call_llm(prompt, model=model, max_tokens=200)
    if response is None:
        return {"direction": "flat", "conviction": 0.0, "reasoning": "llm_unavailable"}
    direction = str(response.get("direction", "flat")).lower()
    if direction not in {"long", "short", "flat"}:
        direction = "flat"
    try:
        conviction = float(response.get("conviction", 0.0))
    except (TypeError, ValueError):
        conviction = 0.0
    conviction = max(0.0, min(1.0, conviction))
    return {
        "direction": direction,
        "conviction": round(conviction, 3),
        "reasoning": str(response.get("reasoning", ""))[:120],
    }


# ---------------------------------------------------------------------------
# Risk scaling
# ---------------------------------------------------------------------------


def risk_scaling_decision(
    symbol: str,
    side: str,
    conviction: float,
    signals: dict[str, Any],
    closed_trades: list[dict[str, Any]] | None = None,
    *,
    model: str = _DEFAULT_MODEL,
) -> dict[str, Any]:
    """Ask the LLM to scale a high-conviction trade by 0.5×, 1.0×, or 1.5×.

    Returns dict {scale: float, reasoning: str}. On failure returns 1.0×.
    """
    last_losers = [t for t in (closed_trades or [])[-15:] if float(t.get("pnl", 0) or 0) < 0]
    avg_loser_mae = 0.0
    if last_losers:
        maes = [float(t.get("mae", 0) or 0) for t in last_losers]
        avg_loser_mae = sum(maes) / len(maes) if maes else 0.0
    prompt = (
        "You manage position sizing in a crypto ensemble strategy.\n"
        f"About to enter {side.upper()} {symbol} at conviction {conviction:.3f}.\n"
        f"Active signals: {_compact_signals(signals)}\n"
        f"Last 5 closed trades: {_recent_outcomes(closed_trades or [])}\n"
        f"Avg MAE of last 15 losers: ${avg_loser_mae:.2f}\n"
        "\n"
        "Should I size this 0.5x (cautious), 1.0x (normal), or 1.5x (aggressive)?\n"
        "Be cautious if recent trade outcomes are mostly losses or losers had deep MAE.\n"
        "Return ONLY a JSON object with keys scale (float 0.5/1.0/1.5) and "
        "reasoning (string max 80 chars)."
    )
    response = _call_llm(prompt, model=model, max_tokens=150)
    if response is None:
        return {"scale": 1.0, "reasoning": "llm_unavailable"}
    try:
        scale = float(response.get("scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    # Snap to the discrete options (LLMs sometimes pick 0.75 etc).
    if scale < 0.75:
        scale = 0.5
    elif scale < 1.25:
        scale = 1.0
    else:
        scale = 1.5
    return {"scale": scale, "reasoning": str(response.get("reasoning", ""))[:120]}
