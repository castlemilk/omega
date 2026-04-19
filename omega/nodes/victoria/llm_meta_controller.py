"""
omega/nodes/victoria/llm_meta_controller.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LLM Meta-Controller for Victoria (V145) — Phase 3 of the adaptive engine.

Called every 50 cycles to adjust surface parameters (T and center values)
rather than individual trades. Blends with the meta-learner's config.

Architecture
------------
- "meta" mode (this module): every 50 cycles, adjusts surface parameters.
- "trade" mode (llm_analyst.py): every 10 cycles, per-trade conviction veto.

The LLM acts as a parameter tuner, not a decision-maker. All suggestions
are blended with the meta-learner's config at a 30% LLM weight by default.
Full graceful degradation: any failure returns {} and the meta-learner config
is used unmodified.

Provider support
----------------
Same provider architecture as llm_analyst.py (ClaudeProvider via urllib).
Extensible to openai_compatible providers. Selection via strategy.py feature flags:
    llm_analyst_provider = "claude"
    llm_analyst_model    = "claude-haiku-4-5-20251001"
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM API constants (same as llm_analyst.py)
# ---------------------------------------------------------------------------

_CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
_CLAUDE_VERSION = "2023-06-01"
_CLAUDE_MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}

# OpenAI-compatible provider configs (key env var → (base_url, default_model))
_OPENAI_COMPAT_PROVIDERS: dict[str, tuple[str, str]] = {
    "KIMI_API_KEY":    ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "GLM_API_KEY":     ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    "MINIMAX_API_KEY": ("https://api.minimax.chat/v1", "MiniMax-Text-01"),
}

def _auto_provider() -> tuple[str, str, str] | None:
    """Return (key_env, base_url, model) for first available openai-compat key."""
    for env_var, (base_url, model) in _OPENAI_COMPAT_PROVIDERS.items():
        if os.environ.get(env_var, ""):
            return env_var, base_url, model
    return None

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a quant meta-controller. Given the system state, suggest surface parameter adjustments.
Return ONLY a JSON object with these optional keys:
{
  "temperature_adjustments": {"bear_long": 0.15, "composite_long": 0.06},
  "center_shifts": {"bear_long": -0.02},
  "signal_family_emphasis": {"microstructure": 1.3, "macro": 0.7},
  "reasoning": "brief explanation under 100 words"
}
All values must be floats. temperature_adjustments override current T. center_shifts are DELTAS added to current center.\
"""

# ---------------------------------------------------------------------------
# Surface parameter bounds
# ---------------------------------------------------------------------------

_T_MIN = 0.05
_T_MAX = 0.30
_CENTER_MIN = 0.01
_CENTER_MAX = 0.95


# ---------------------------------------------------------------------------
# LLMMetaController
# ---------------------------------------------------------------------------


class LLMMetaController:
    """
    Calls an LLM every 50 cycles to suggest surface parameter adjustments.

    Usage (in strategy.py)::

        ctrl = LLMMetaController()
        if ctrl.should_call(cycle):
            ctx = ctrl.build_context(...)
            result = ctrl.call(ctx, provider="claude", model="claude-haiku-4-5-20251001")
            if result:
                ml_cfg = ctrl.blend_with_meta_learner(ml_cfg, result)
                confidence_surface = ConfidenceSurface(ml_cfg)
    """

    def __init__(self, call_interval: int = 50) -> None:
        self.call_interval: int = call_interval
        self.last_call_cycle: int = -1

    # ------------------------------------------------------------------
    # Cycle gating
    # ------------------------------------------------------------------

    def should_call(self, cycle: int) -> bool:
        """Return True if cycle is a multiple of call_interval (and > 0)."""
        if cycle <= 0:
            return False
        return (cycle % self.call_interval) == 0

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def build_context(
        self,
        regime_pf: dict[str, Any],
        signal_ic: dict[str, float],
        surface_summary: dict[str, Any],
        recent_trades: list[dict],
        macro_snapshot: dict[str, Any] | None = None,
    ) -> str:
        """
        Format a prompt string for the LLM meta-controller.

        Parameters
        ----------
        regime_pf       : rolling profit factor per regime, e.g. {"crisis": 1.2, "normal": 0.9}
        signal_ic       : IC drift per signal family, e.g. {"momentum": 0.03, "macro": -0.01}
        surface_summary : current surface T and center per surface name (from meta_learner.summary())
        recent_trades   : list of trade dicts with keys: symbol, side, pnl, regime (last 10 used)
        macro_snapshot  : optional macro indicators dict
        """
        lines: list[str] = ["=== VICTORIA META-CONTROLLER STATE ===\n"]

        # --- Regime profit factors ---
        lines.append("** Rolling Profit Factor per Regime **")
        for regime, pf in regime_pf.items():
            pf_str = f"{pf:.3f}" if pf is not None else "N/A"
            lines.append(f"  {regime}: PF={pf_str}")
        lines.append("")

        # --- Signal IC drift ---
        lines.append("** Signal IC per Family **")
        for family, ic in signal_ic.items():
            lines.append(f"  {family}: IC={ic:+.4f}")
        lines.append("")

        # --- Current surface T and center ---
        lines.append("** Current Surface Parameters **")
        for surf_name, surf_data in surface_summary.items():
            center = surf_data.get("center", "?")
            temp = surf_data.get("T", "?")
            n_adj = surf_data.get("n_adj", 0)
            lines.append(f"  {surf_name}: center={center}, T={temp}, adjustments={n_adj}")
        lines.append("")

        # --- Recent trade outcomes (last 10) ---
        lines.append("** Last 10 Trade Outcomes **")
        trades_to_show = recent_trades[-10:] if recent_trades else []
        if trades_to_show:
            for t in trades_to_show:
                symbol = t.get("symbol", "?")
                side = t.get("side", "?")
                pnl = t.get("pnl", 0.0)
                regime = t.get("regime", "?")
                lines.append(f"  {symbol} {side} pnl={pnl:+.2f} regime={regime}")
        else:
            lines.append("  (no recent trades)")
        lines.append("")

        # --- Macro snapshot (optional) ---
        if macro_snapshot:
            lines.append("** Macro Snapshot **")
            for k, v in macro_snapshot.items():
                lines.append(f"  {k}: {v}")
            lines.append("")

        lines.append(
            "Based on the above state, suggest surface parameter adjustments.\n"
            "Return ONLY the JSON object as specified in the system prompt."
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def call(
        self,
        context: str,
        provider: str = "claude",
        model: str = "claude-haiku-4-5-20251001",
        key_env: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Call the LLM with the context and return parsed adjustments dict.

        Returns empty dict on any failure (LLM unavailable, parse error, timeout).
        Logs a warning on failure, reasoning on success.
        """
        self.last_call_cycle = -1  # reset; set after successful return

        try:
            result = self._call_provider(context, provider, model, key_env=key_env, base_url=base_url)
            reasoning = result.get("reasoning", "")
            if reasoning:
                logger.info("V145 llm_meta_ctrl reasoning: %s", reasoning[:200])
            return result
        except Exception as exc:
            logger.warning("V145 llm_meta_ctrl call failed (%s): %s", provider, exc)
            return {}

    def _call_provider(
        self,
        context: str,
        provider: str,
        model: str,
        key_env: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Internal: dispatch to the right provider and parse JSON response."""
        if provider == "claude" or provider == "cli":
            return self._call_claude(context, model)
        if provider == "openai_compatible":
            return self._call_openai_compatible(context, model, key_env=key_env, base_url=base_url)
        # Auto-detect: try openai-compat keys first, then claude
        auto = _auto_provider()
        if auto:
            logger.info("V145 llm_meta_ctrl: auto-routing to %s", auto[0])
            return self._call_openai_compatible(context, model, key_env=auto[0], base_url=auto[1])
        logger.warning("V145 llm_meta_ctrl: unknown provider %r, falling back to claude", provider)
        return self._call_claude(context, model)

    def _call_openai_compatible(
        self,
        context: str,
        model: str,
        key_env: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Call any OpenAI-compatible API (Kimi, GLM, MiniMax) via urllib."""
        # Resolve key: explicit env var > auto-detect first available
        if key_env is None:
            auto = _auto_provider()
            if auto is None:
                raise RuntimeError("No openai-compatible API key found in environment")
            key_env, _auto_base, _auto_model = auto
            if base_url is None:
                base_url = _auto_base
            # Only use auto model if caller didn't specify a real one
            if not model or model == "claude-haiku-4-5-20251001":
                model = _auto_model
        api_key = os.environ.get(key_env, "")
        if not api_key:
            raise RuntimeError(f"{key_env} not set")
        if base_url is None:
            base_url = _OPENAI_COMPAT_PROVIDERS.get(key_env, ("", ""))[0]

        url = base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": model,
            "max_tokens": 512,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
        }).encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode())

        text = raw["choices"][0]["message"]["content"]
        return self._parse_response(text)

    def _call_claude(self, context: str, model: str) -> dict[str, Any]:
        """Call Anthropic Claude API via urllib (zero extra deps)."""
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        resolved_model = _CLAUDE_MODEL_ALIASES.get(model, model)

        body = json.dumps(
            {
                "model": resolved_model,
                "max_tokens": 512,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": context}],
            }
        ).encode()

        req = urllib.request.Request(
            _CLAUDE_API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": _CLAUDE_VERSION,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode())

        text = raw["content"][0]["text"]
        return self._parse_response(text)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse LLM JSON response safely. Returns empty dict on failure."""
        text = raw.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            for part in text.split("```")[1::2]:
                if part.startswith("json"):
                    part = part[4:]
                text = part.strip()
                break

        # Try direct JSON parse
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end])
                except json.JSONDecodeError:
                    logger.warning("V145 llm_meta_ctrl: cannot parse JSON from response")
                    return {}
            else:
                logger.warning("V145 llm_meta_ctrl: no JSON object in response")
                return {}

        # Validate and coerce types
        result: dict[str, Any] = {}

        temp_adj = data.get("temperature_adjustments")
        if isinstance(temp_adj, dict):
            result["temperature_adjustments"] = {
                k: float(v) for k, v in temp_adj.items() if isinstance(v, (int, float))
            }

        center_shifts = data.get("center_shifts")
        if isinstance(center_shifts, dict):
            result["center_shifts"] = {
                k: float(v) for k, v in center_shifts.items() if isinstance(v, (int, float))
            }

        sig_emphasis = data.get("signal_family_emphasis")
        if isinstance(sig_emphasis, dict):
            result["signal_family_emphasis"] = {
                k: float(v) for k, v in sig_emphasis.items() if isinstance(v, (int, float))
            }

        reasoning = data.get("reasoning", "")
        if reasoning:
            result["reasoning"] = str(reasoning)[:300]

        return result

    # ------------------------------------------------------------------
    # Blending with meta-learner config
    # ------------------------------------------------------------------

    def blend_with_meta_learner(
        self,
        ml_config: Any,  # SurfaceConfig
        llm_result: dict[str, Any],
        llm_weight: float = 0.3,
    ) -> Any:
        """
        Blend meta-learner's SurfaceConfig with LLM suggestions.

        Rules
        -----
        - temperature: final_T = (1 - w) * ml_T + w * llm_T  (if LLM suggests)
        - center:      final_μ = ml_μ + llm_delta             (if LLM suggests)
        - T clamped to [0.05, 0.30]
        - center clamped to [0.01, 0.95]
        - Surfaces not mentioned by LLM are returned unchanged.

        Returns a new SurfaceConfig (does NOT mutate ml_config).
        """
        try:
            from omega.nodes.victoria.confidence_surface import SurfaceConfig, SurfaceParams
        except ImportError:
            logger.warning("V145 blend: cannot import SurfaceConfig, returning ml_config")
            return ml_config

        # Build field-level overrides from LLM suggestions
        temp_adj: dict[str, float] = llm_result.get("temperature_adjustments", {})
        center_shifts: dict[str, float] = llm_result.get("center_shifts", {})

        if not temp_adj and not center_shifts:
            return ml_config  # nothing to blend

        # Snapshot current params from ml_config
        # SurfaceConfig stores named SurfaceParams attributes; we iterate by name
        _surface_names = [
            "bear_long",
            "bear_short",
            "composite_long",
            "composite_short",
            "llm_long",
            "llm_short",
        ]

        new_params: dict[str, SurfaceParams] = {}
        for name in _surface_names:
            sp: SurfaceParams | None = getattr(ml_config, name, None)
            if sp is None:
                continue

            ml_temp = sp.temperature
            ml_center = sp.center

            # Blend temperature
            if name in temp_adj:
                llm_temp = float(temp_adj[name])
                blended_temp = (1.0 - llm_weight) * ml_temp + llm_weight * llm_temp
                blended_temp = max(_T_MIN, min(_T_MAX, blended_temp))
            else:
                blended_temp = ml_temp

            # Apply center delta
            if name in center_shifts:
                blended_center = ml_center + float(center_shifts[name])
                blended_center = max(_CENTER_MIN, min(_CENTER_MAX, blended_center))
            else:
                blended_center = ml_center

            new_params[name] = SurfaceParams(center=blended_center, temperature=blended_temp)

        # Rebuild SurfaceConfig preserving unchanged fields
        kwargs: dict[str, Any] = {}
        for name in _surface_names:
            if name in new_params:
                kwargs[name] = new_params[name]
            else:
                existing = getattr(ml_config, name, None)
                if existing is not None:
                    kwargs[name] = existing

        # Preserve regime_base_weights if present
        rbw = getattr(ml_config, "regime_base_weights", None)
        if rbw is not None:
            kwargs["regime_base_weights"] = rbw

        try:
            new_cfg = SurfaceConfig(**kwargs)
        except Exception as exc:
            logger.warning("V145 blend: SurfaceConfig construction failed: %s", exc)
            return ml_config

        logger.debug(
            "V145 llm_meta_ctrl blended config: temp_adj=%s center_shifts=%s",
            temp_adj,
            center_shifts,
        )
        return new_cfg
