"""
omega.nodes.victoria.signals.llm_analyst
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LLM-as-analyst conviction modifier for Victoria (V139).

The LLM acts as a senior analyst, not a decision-maker. It returns a
conviction_modifier in [0.0, 1.5] that scales the IC-weighted composite
before threshold comparison. The quant system retains full veto authority.

    modifier < 0.5  → LLM veto   (entry blocked)
    modifier < 1.0  → analyst cautious (reduces effective conviction)
    modifier = 1.0  → neutral   (no change — also the error fallback)
    modifier > 1.0  → upside signal (amplifies conviction)

Provider architecture (V139 refactor):
    PROVIDERS = {
        "claude":             ClaudeProvider       — Anthropic API
        "openai_compatible":  OpenAICompatibleProvider — Kimi, GLM, MiniMax, etc.
        "cli":                CLIProvider          — wraps any CLI tool
    }

Provider selection via feature flags:
    llm_analyst_provider    = "claude"
    llm_analyst_model       = "claude-haiku-4-5-20251001"
    llm_analyst_api_base    = ""                   (OpenAI-compatible only)
    llm_analyst_api_key_env = "ANTHROPIC_API_KEY"  (env var name)

Cache:  data/cache/llm_analyst/{sha256_16}.json  (no TTL — keyed by input)
Log:    data/llm_analyst_log/{version}.jsonl     (provider/model/cost/response)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_CACHE_ROOT = Path(__file__).resolve().parents[4] / "data" / "cache" / "llm_analyst"
_LOG_ROOT = Path(__file__).resolve().parents[4] / "data" / "llm_analyst_log"

# ---------------------------------------------------------------------------
# Cost table (USD per token — input, output)
# ---------------------------------------------------------------------------

_COST_TABLE: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.80e-6, 4.00e-6),
    "claude-haiku-4-5": (0.80e-6, 4.00e-6),
    "claude-sonnet-4-6": (3.00e-6, 15.00e-6),
    "claude-opus-4-7": (15.00e-6, 75.00e-6),
    "kimi-v2": (0.15e-6, 0.60e-6),
    "kimi-v2-5": (0.15e-6, 0.60e-6),
    "glm-5.1": (0.10e-6, 0.10e-6),
    "glm-4": (0.05e-6, 0.05e-6),
    "minimax-2.7": (0.05e-6, 0.10e-6),
    "minimax-text-01": (0.05e-6, 0.10e-6),
}
_DEFAULT_COST = (0.50e-6, 1.50e-6)  # conservative unknown-model fallback

# ---------------------------------------------------------------------------
# Response JSON schema
# ---------------------------------------------------------------------------

_RESPONSE_REQUIRED_KEYS = {"conviction_modifier", "reasoning"}
_RESPONSE_SCHEMA_HINTS = (
    "Return ONLY a JSON object with:\n"
    "  conviction_modifier: float [0.0, 1.5]  "
    "(< 0.5=veto, 0.5–1.0=cautious, 1.0=neutral, >1.0=amplify)\n"
    "  reasoning: 1 sentence, max 80 chars\n"
    "  confidence: float [0.0, 1.0]\n"
    "  regime_override: optional string (null if no override)\n"
    "No other text."
)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class LLMAnalystResult:
    conviction_modifier: float = 1.0
    reasoning: str = ""
    regime_override: str | None = None
    signal_adjustments: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.5
    cached: bool = False
    latency_ms: float = 0.0
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Response normalizer
# ---------------------------------------------------------------------------


def normalize_response(raw: str, provider: str = "") -> dict:
    """Parse and normalise any LLM response to the conviction schema.

    Handles:
      - Raw JSON
      - Markdown-fenced JSON (```json ... ```)
      - Partial JSON with missing optional keys
      - Numeric strings for conviction_modifier
      - Single-key responses
    """
    text = raw.strip()

    # Strip markdown fences
    if text.startswith("```"):
        parts = text.split("```")
        # Take the content after the first fence
        for i, part in enumerate(parts):
            if i % 2 == 1:  # inside fence
                if part.startswith("json"):
                    part = part[4:]
                text = part.strip()
                break

    # Try direct JSON parse
    try:
        data = json.loads(text)
    except json.JSONDecodeError as outer_err:
        # Try to find first {...} block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError as inner_err:
                raise ValueError(f"Cannot parse JSON from response: {text[:200]!r}") from inner_err
        else:
            raise ValueError(f"No JSON object found in response: {text[:200]!r}") from outer_err

    # Coerce fields
    modifier = data.get("conviction_modifier", 1.0)
    try:
        modifier = float(modifier)
    except (TypeError, ValueError):
        modifier = 1.0
    modifier = max(0.0, min(1.5, modifier))

    confidence = data.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "conviction_modifier": modifier,
        "reasoning": str(data.get("reasoning", ""))[:120],
        "confidence": confidence,
        "regime_override": data.get("regime_override"),
        "signal_adjustments": data.get("signal_adjustments") or {},
    }


# ---------------------------------------------------------------------------
# Abstract provider base
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract LLM provider.  Providers are stateless — create once, call many times."""

    @abstractmethod
    def analyze(self, prompt: str, model: str) -> tuple[dict, int, int]:
        """Call the LLM and return (parsed_response, tokens_in, tokens_out).

        *parsed_response* must already be normalised (use normalize_response()).
        Token counts are used for cost estimation; pass 0 if unavailable.
        Raise any exception on failure — LLMAnalystSignal catches and degrades.
        """


# ---------------------------------------------------------------------------
# ClaudeProvider
# ---------------------------------------------------------------------------

_CLAUDE_MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}
_CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
_CLAUDE_VERSION = "2023-06-01"


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider (urllib, same pattern as brain.py)."""

    def __init__(self, api_key_env: str = "ANTHROPIC_API_KEY", timeout: int = 10) -> None:
        self._api_key = (os.environ.get(api_key_env) or "").strip()
        self._timeout = timeout

    def analyze(self, prompt: str, model: str) -> tuple[dict, int, int]:
        resolved = _CLAUDE_MODEL_ALIASES.get(model, model)
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        body = json.dumps(
            {
                "model": resolved,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        req = urllib.request.Request(
            _CLAUDE_API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": _CLAUDE_VERSION,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            raw = json.loads(resp.read().decode())
        text = raw["content"][0]["text"]
        usage = raw.get("usage", {})
        t_in = usage.get("input_tokens", 0)
        t_out = usage.get("output_tokens", 0)
        return normalize_response(text, "claude"), t_in, t_out


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider (Kimi, GLM, MiniMax, etc.)
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """Provider for any OpenAI-format /v1/chat/completions endpoint.

    Works with: Kimi (api.moonshot.cn/v1), GLM (open.bigmodel.cn/api/paas/v4),
    MiniMax (api.minimax.chat/v1 or api.minimax.io/anthropic), and others.

    Anthropic-compat mode: when api_base contains '/anthropic', uses x-api-key
    header + /v1/messages endpoint (MiniMax's Anthropic proxy).
    """

    _ANTHROPIC_SYSTEM = (
        "You are a senior quantitative crypto trading analyst embedded in an automated trading system. "
        "Your role is to review trade proposals and return a structured JSON assessment. "
        "Every response MUST be a valid JSON object and nothing else — no preamble, no markdown, no explanation. "
        "JSON schema: "
        "{\"conviction_modifier\": <float 0.0-1.5>, "
        "\"reasoning\": <string max 80 chars>, "
        "\"confidence\": <float 0.0-1.0>, "
        "\"regime_override\": <string or null>}. "
        "conviction_modifier semantics: <0.5 veto, 0.5-1.0 cautious, 1.0 neutral, >1.0 amplify."
    )

    def __init__(
        self,
        api_base: str,
        api_key_env: str,
        timeout: int = 15,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = (os.environ.get(api_key_env) or "").strip()
        self._timeout = timeout

        # Anthropic-compat mode: /anthropic proxy uses x-api-key + /v1/messages
        # Extended-thinking models can be slow (4-10s), so use 60s timeout.
        self._anthropic_compat = "/anthropic" in self._api_base
        if self._anthropic_compat:
            self._endpoint = f"{self._api_base}/v1/messages"
            self._timeout = max(timeout, 60)
        elif "chatcompletion" in self._api_base or self._api_base.endswith("/chat/completions"):
            # Full endpoint path already provided (e.g. MiniMax chatcompletion_v2)
            self._endpoint = self._api_base
        else:
            self._endpoint = f"{self._api_base}/chat/completions"

    def analyze(self, prompt: str, model: str) -> tuple[dict, int, int]:
        if not self._api_key:
            raise RuntimeError(f"API key env var empty (api_base={self._api_base})")

        if self._anthropic_compat:
            return self._call_anthropic_compat(prompt, model)
        return self._call_openai(prompt, model)

    def _call_openai(self, prompt: str, model: str) -> tuple[dict, int, int]:
        body = json.dumps(
            {
                "model": model,
                "max_tokens": 300,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            raw = json.loads(resp.read().decode())
        choices = raw.get("choices")
        if not choices:
            # Some providers (MiniMax chatcompletion_v2) embed errors in base_resp
            base = raw.get("base_resp", {})
            raise RuntimeError(
                f"No choices in response (status={base.get('status_code')}: "
                f"{base.get('status_msg', 'unknown')})"
            )
        text = choices[0]["message"]["content"]
        usage = raw.get("usage", {})
        t_in = usage.get("prompt_tokens", 0)
        t_out = usage.get("completion_tokens", 0)
        return normalize_response(text, "openai_compatible"), t_in, t_out

    def _call_anthropic_compat(self, prompt: str, model: str) -> tuple[dict, int, int]:
        """MiniMax Anthropic proxy: x-api-key header, /v1/messages endpoint."""
        # Strip schema hints from user prompt — they're now in system prompt.
        # Avoid triggering refusal filters on the "Return ONLY JSON" instruction.
        clean_prompt = prompt
        schema_hint_start = "Return ONLY a JSON object with:"
        if schema_hint_start in clean_prompt:
            clean_prompt = clean_prompt[: clean_prompt.index(schema_hint_start)].rstrip()
        # Extended thinking models consume many tokens before output;
        # use 1024 to leave room for the JSON response after thinking.
        body = json.dumps(
            {
                "model": model,
                "max_tokens": 1024,
                "system": self._ANTHROPIC_SYSTEM,
                "messages": [{"role": "user", "content": clean_prompt}],
            }
        ).encode()
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            raw = json.loads(resp.read().decode())
        # Extract text: skip thinking blocks, fall back to first block
        text = ""
        for block in raw.get("content", []):
            if block.get("type") == "text":
                text = block["text"]
                break
        if not text:
            blocks = raw.get("content", [])
            text = blocks[0].get("text", blocks[0].get("thinking", "")) if blocks else ""
        if not text:
            raise RuntimeError(f"No text in Anthropic-compat response: {raw!r}")
        usage = raw.get("usage", {})
        t_in = usage.get("input_tokens", 0)
        t_out = usage.get("output_tokens", 0)
        return normalize_response(text, "openai_compatible"), t_in, t_out


# ---------------------------------------------------------------------------
# CLIProvider (wraps any installed LLM CLI, e.g. `claude -p`)
# ---------------------------------------------------------------------------


class CLIProvider(LLMProvider):
    """Wraps any CLI tool that accepts a prompt and emits text to stdout.

    Default: ``claude -p <prompt>`` (Claude Code CLI).
    Override *cli_template* for other tools, e.g. ``["llm", "-m", "{model}", "{prompt}"]``.
    {model} and {prompt} are substituted at call time.
    """

    def __init__(
        self,
        cli_template: list[str] | None = None,
        timeout: int = 30,
    ) -> None:
        # Default: claude CLI with explicit model selection (-p for non-interactive print mode)
        self._template = cli_template or ["claude", "--model", "{model}", "-p", "{prompt}"]
        self._timeout = timeout

    def analyze(self, prompt: str, model: str) -> tuple[dict, int, int]:
        cmd = [
            part.replace("{model}", model).replace("{prompt}", prompt) for part in self._template
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"CLI exit {result.returncode}: {result.stderr[:200]}")
        text = result.stdout.strip()
        # CLI providers don't expose token counts
        return normalize_response(text, "cli"), 0, 0


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, type[LLMProvider]] = {
    "claude": ClaudeProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "cli": CLIProvider,
}

# Known OpenAI-compatible endpoints (provider_name → api_base)
KNOWN_BASES: dict[str, str] = {
    "kimi": "https://api.moonshot.cn/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    # Full endpoint path — chatcompletion_v2 is MiniMax's OpenAI-compat chat endpoint
    "minimax": "https://api.minimax.chat/v1/text/chatcompletion_v2",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    # V169: DeepSeek (OpenAI-compatible). Use "deepseek" with model
    # "deepseek-chat" for V3, or "deepseek-reasoner" for R1 (chain-of-thought).
    "deepseek": "https://api.deepseek.com/v1",
}

# Known API key env var names per provider shorthand
KNOWN_API_KEY_ENVS: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "kimi": "KIMI_API_KEY",
    "glm": "GLM_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "together": "TOGETHER_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def build_provider(
    provider: str,
    model: str,
    api_base: str = "",
    api_key_env: str = "",
) -> LLMProvider:
    """Construct the right LLMProvider given feature-flag config.

    Handles shorthand names like "kimi" or "glm" that map to
    OpenAICompatibleProvider with known api_base values.
    """
    # kimi_cli: wrap kimi-cli binary (same pattern as Claude CLI)
    if provider == "kimi_cli":
        return CLIProvider(
            cli_template=["kimi-cli", "--quiet", "--prompt", "{prompt}"],
            timeout=90,
        )

    # Shorthand → OpenAI-compatible
    if provider in KNOWN_BASES:
        resolved_base = api_base or KNOWN_BASES[provider]
        resolved_key_env = api_key_env or KNOWN_API_KEY_ENVS.get(provider, "")
        return OpenAICompatibleProvider(api_base=resolved_base, api_key_env=resolved_key_env)

    if provider == "claude":
        resolved_key_env = api_key_env or "ANTHROPIC_API_KEY"
        return ClaudeProvider(api_key_env=resolved_key_env)

    if provider == "cli":
        return CLIProvider()

    if provider == "openai_compatible":
        if not api_base:
            raise ValueError("openai_compatible provider requires llm_analyst_api_base")
        resolved_key_env = api_key_env or "OPENAI_API_KEY"
        return OpenAICompatibleProvider(api_base=api_base, api_key_env=resolved_key_env)

    raise ValueError(f"Unknown LLM provider: {provider!r}. Known: {list(PROVIDERS)}")


# ---------------------------------------------------------------------------
# Signal selection helpers
# ---------------------------------------------------------------------------

_MACRO_SIGNALS = {"vix_signal", "dxy_signal", "yield_curve_signal", "spy_signal"}
_GEO_SIGNALS = {"geo_event_intensity", "geo_sentiment", "geo_regime_shift", "sanctions_signal"}
_MAX_OTHER_SIGNALS = 8


# ---------------------------------------------------------------------------
# LLMAnalystSignal  (public interface — unchanged from strategy.py perspective)
# ---------------------------------------------------------------------------


class LLMAnalystSignal:
    """Compute LLM conviction modifier for a single ticker.

    Provider-agnostic: delegates to whichever LLMProvider is configured.
    SHA256-keyed cache ensures deterministic backtest replay across all providers.
    Every live (non-cached) call is appended to the JSONL log.
    """

    def __init__(
        self,
        provider: str = "claude",
        model: str = "claude-haiku-4-5-20251001",
        api_base: str = "",
        api_key_env: str = "",
        cache_root: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._provider_name = provider
        self._model = model
        self._cache_root = cache_root or _CACHE_ROOT
        self._log_path: Path | None = log_path

        try:
            self._provider: LLMProvider | None = build_provider(
                provider, model, api_base, api_key_env
            )
        except Exception as exc:
            logger.warning(
                "LLMProvider build failed (%s): %s — will degrade to 1.0", provider, exc
            )
            self._provider = None

        # V153: trend-mode preamble injection (set externally from strategy.py)
        self.trend_mode_enabled: bool = False

    def set_log_path(self, version: str) -> None:
        """Set per-version JSONL log path. Call from strategy.py after version is known."""
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

        Degrades to modifier=1.0 on any failure (no provider, API error, parse error).
        """
        if self._provider is None:
            return LLMAnalystResult(
                conviction_modifier=1.0,
                reasoning="no_provider",
                provider=self._provider_name,
                model=self._model,
            )

        t0 = time.monotonic()
        payload = self._build_payload(
            ticker,
            direction,
            regime,
            composite,
            weighted_conviction,
            signals,
            bear_prob,
            bull_prob,
            last_trades,
            open_positions,
            cycle,
            timestamp,
        )
        key = self._cache_key(payload)

        cached = self._cache_load(key)
        if cached is not None:
            cached.cached = True
            cached.latency_ms = round((time.monotonic() - t0) * 1000, 1)
            return cached

        try:
            prompt = self._build_prompt(payload)
            parsed, t_in, t_out = self._provider.analyze(prompt, self._model)
            result = LLMAnalystResult(
                conviction_modifier=parsed["conviction_modifier"],
                reasoning=parsed["reasoning"],
                regime_override=parsed.get("regime_override"),
                signal_adjustments=parsed.get("signal_adjustments", {}),
                confidence=parsed.get("confidence", 0.5),
                provider=self._provider_name,
                model=self._model,
                tokens_in=t_in,
                tokens_out=t_out,
                cost_usd=self._estimate_cost(t_in, t_out),
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
            )
            self._cache_store(key, result)
            self._log_call(payload, result, cache_hit=False)
            return result

        except Exception as exc:
            logger.debug(
                "LLMAnalystSignal error [%s/%s] %s: %s",
                self._provider_name,
                self._model,
                ticker,
                exc,
            )
            return LLMAnalystResult(
                conviction_modifier=1.0,
                reasoning=f"error:{type(exc).__name__}",
                provider=self._provider_name,
                model=self._model,
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
        ts_str = (timestamp or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")

        macro = {k: round(float(signals.get(k, 0.0)), 4) for k in _MACRO_SIGNALS if k in signals}
        geo = {k: round(float(signals.get(k, 0.0)), 3) for k in _GEO_SIGNALS if k in signals}
        other = {
            k: round(float(v), 4)
            for k, v in signals.items()
            if k not in _MACRO_SIGNALS
            and k not in _GEO_SIGNALS
            and not k.startswith("_")
            and isinstance(v, (int, float))
        }
        top_other = dict(
            sorted(other.items(), key=lambda kv: abs(kv[1]), reverse=True)[:_MAX_OTHER_SIGNALS]
        )

        long_count = short_count = 0
        if open_positions:
            for pos in open_positions.values():
                side = pos.get("side", "") if isinstance(pos, dict) else ""
                if side == "long":
                    long_count += 1
                elif side == "short":
                    short_count += 1

        recent_trades: list[dict] = []
        if last_trades:
            for t in list(last_trades)[-5:]:
                if not isinstance(t, dict):
                    continue
                recent_trades.append(
                    {
                        "ticker": t.get("symbol", t.get("ticker", "?")),
                        "side": t.get("side", "?"),
                        "pnl": round(float(t.get("pnl", 0.0)), 2),
                        "hold_cycles": t.get("hold_cycles", "?"),
                        "reasoning": str(t.get("reasoning", ""))[:100]
                        if t.get("reasoning")
                        else "",
                    }
                )

        return {
            "_provider": self._provider_name,
            "_model": self._model,
            "ticker": ticker,
            "direction": direction,
            "regime": regime,
            "composite": round(composite, 5),
            "weighted_conviction": round(weighted_conviction, 5),
            "bear_prob": round(bear_prob, 3),
            "bull_prob": round(bull_prob, 3),
            "signals": {**macro, **top_other},
            "geo": geo,
            "open_positions": {"long": long_count, "short": short_count},
            "recent_trades": recent_trades,
            "cycle": cycle,
            "timestamp": ts_str,
        }

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        sig_lines = "\n".join(f"  {k}: {v:+.4f}" for k, v in payload["signals"].items())
        geo_str = ""
        if payload.get("geo"):
            geo_str = "\nGeopolitical:\n" + "\n".join(
                f"  {k}: {v}" for k, v in payload["geo"].items()
            )
        trades_str = ""
        if payload["recent_trades"]:
            trades_str = "\nLast trades:\n" + "\n".join(
                f"  {t['ticker']} {t['side']} ${t['pnl']:+.0f} {t['hold_cycles']}c"
                + (f" | {t['reasoning']}" if t.get("reasoning") else "")
                for t in payload["recent_trades"]
            )
        positions_str = (
            f"\nOpen: {payload['open_positions']['long']}L / {payload['open_positions']['short']}S"
        )
        # V153: trend-mode preamble — injected when bull_prob confirms uptrend.
        # Counteracts the LLM's crisis-trained bearish bias in bull markets.
        trend_ctx = ""
        if (
            self.trend_mode_enabled
            and payload.get("bull_prob", 0.0) > 0.55
            and payload.get("regime", "") in ("trending", "normal")
        ):
            trend_ctx = (
                "MARKET CONTEXT: Confirmed uptrend (bull_prob={:.2f}). "
                "Long entries are primary — bias toward confirmation. "
                "Short entries require exceptional cross-signal conviction.\n\n"
            ).format(payload["bull_prob"])

        return (
            f"You are a senior crypto quant analyst.\n\n"
            f"{trend_ctx}"
            f"Ticker: {payload['ticker']}  Proposal: {payload['direction'].upper()}\n"
            f"Regime: {payload['regime']}  "
            f"bear_prob={payload['bear_prob']:.2f}  bull_prob={payload['bull_prob']:.2f}\n"
            f"Quant composite: {payload['composite']:+.5f}  "
            f"w_conv: {payload['weighted_conviction']:+.5f}\n"
            f"Signals:\n{sig_lines}"
            f"{geo_str}"
            f"{trades_str}"
            f"{positions_str}\n\n"
            f"{_RESPONSE_SCHEMA_HINTS}"
        )

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        c_in, c_out = _COST_TABLE.get(self._model, _DEFAULT_COST)
        return round(tokens_in * c_in + tokens_out * c_out, 8)

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
                provider=data.get("provider", self._provider_name),
                model=data.get("model", self._model),
                tokens_in=int(data.get("tokens_in", 0)),
                tokens_out=int(data.get("tokens_out", 0)),
                cost_usd=float(data.get("cost_usd", 0.0)),
            )
        except Exception:
            return None

    def _cache_store(self, key: str, result: LLMAnalystResult) -> None:
        try:
            self._cache_root.mkdir(parents=True, exist_ok=True)
            self._cache_path(key).write_text(
                json.dumps(
                    {
                        "conviction_modifier": result.conviction_modifier,
                        "reasoning": result.reasoning,
                        "regime_override": result.regime_override,
                        "signal_adjustments": result.signal_adjustments,
                        "confidence": result.confidence,
                        "provider": result.provider,
                        "model": result.model,
                        "tokens_in": result.tokens_in,
                        "tokens_out": result.tokens_out,
                        "cost_usd": result.cost_usd,
                    }
                )
            )
        except Exception as exc:
            logger.debug("llm_analyst cache write failed: %s", exc)

    # ------------------------------------------------------------------
    # JSONL log
    # ------------------------------------------------------------------

    def _log_call(
        self, payload: dict[str, Any], result: LLMAnalystResult, cache_hit: bool
    ) -> None:
        if self._log_path is None:
            return
        try:
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "provider": result.provider,
                "model": result.model,
                "ticker": payload["ticker"],
                "direction": payload["direction"],
                "regime": payload["regime"],
                "cycle": payload["cycle"],
                "composite": payload["composite"],
                "bear_prob": payload["bear_prob"],
                "modifier": result.conviction_modifier,
                "reasoning": result.reasoning,
                "confidence": result.confidence,
                "regime_override": result.regime_override,
                "cached": cache_hit,
                "latency_ms": result.latency_ms,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "cost_usd": result.cost_usd,
            }
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("llm_analyst log write failed: %s", exc)
