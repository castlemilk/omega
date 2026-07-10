"""
omega.nodes.victoria.reasoning_layer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
V240 Track D — hermetic per-cycle basket review by a frontier reasoning model.

Model (V240.md "Model choice"): **Gemini via the `agy` CLI** (subprocess;
DeepSeek/Kimi/OpenRouter keys unavailable). The CLI exposes no temperature
control, so live-call determinism is NOT assumed: determinism is guaranteed
entirely by the frozen cache below. The quant book retains full veto — the
layer can only trim (drop) or scale positions within [0, 1.5], never invent
one (V139 subordinate posture).

Hermetic cache (V215/V238 pattern):
  data/frozen_llm_cache/{model_id}/{prompt_hash}.json
  prompt_hash = sha256(canonical_prompt_json)[:16]
Under OMEGA_FROZEN_CACHE=1 a cache miss **raises LLMCacheMiss** — never a live
call, never a neutral stub. Cache-fill runs happen only with the flag OFF.
data/frozen_llm_cache/{model_id}/MANIFEST.json records the model string, CLI
version and md5 per entry; a model-string mismatch on replay is a hard error.

Flag: features.reasoning_layer_enabled (default OFF — the layer is not even
constructed when off; OFF path is byte-identical to the V239 baseline).
Falsifier eval is V241, not V240.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("omega.nodes.victoria.reasoning_layer")

CACHE_ROOT = Path(__file__).resolve().parents[3] / "data" / "frozen_llm_cache"

DEFAULT_MODEL_ID = "gemini-3.1-pro-low"
# agy --model strings, keyed by our stable model_id (the cache namespace).
_AGY_MODEL_STRINGS = {
    "gemini-3.1-pro-low": "Gemini 3.1 Pro (Low)",
    "gemini-3.1-pro-high": "Gemini 3.1 Pro (High)",
    "gemini-3.5-flash-medium": "Gemini 3.5 Flash (Medium)",
}

_MAX_MALFORMED_RETRIES = 2
_SIZE_SCALE_MIN, _SIZE_SCALE_MAX = 0.0, 1.5


class LLMCacheMiss(Exception):  # noqa: N818 — name is the pre-registered V240 contract
    """Frozen replay requested a prompt hash absent from the frozen cache."""


class LLMMalformedOutput(Exception):  # noqa: N818 — paired with LLMCacheMiss
    """The model returned unparseable/invalid JSON after bounded retries."""


@dataclass
class BasketReview:
    """Validated per-cycle review. Symbols are always a subset of candidates."""

    keep: list[str]
    drop: list[str]
    size_scale: dict[str, float]
    reasoning: str
    confidence: float
    cached: bool = False
    prompt_hash: str = ""
    raw: dict = field(default_factory=dict)


def _frozen_mode() -> bool:
    return os.environ.get("OMEGA_FROZEN_CACHE") == "1"


class ReasoningLayer:
    """Per-cycle basket review via agy (Gemini), hermetically cached."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        cache_root: Path | None = None,
        agy_bin: str = "agy",
        timeout_s: float = 300.0,
    ) -> None:
        if model_id not in _AGY_MODEL_STRINGS:
            raise ValueError(f"unknown model_id {model_id!r} (no agy model string)")
        self.model_id = model_id
        self._agy_model = _AGY_MODEL_STRINGS[model_id]
        self._agy_bin = agy_bin
        self._timeout_s = timeout_s
        self._cache_dir = (cache_root or CACHE_ROOT) / model_id
        self._manifest_path = self._cache_dir / "MANIFEST.json"

    # ------------------------------------------------------------- public

    def review_basket(
        self, cycle_ctx: dict, candidates: list[dict]
    ) -> tuple[list[str], BasketReview, str]:
        """Review the cycle's candidate basket.

        Args:
            cycle_ctx: cycle-level context (regime label, series values,
                recent basket PnL/drawdown, similar past decisions). Must be
                JSON-serialisable; it is embedded verbatim in the prompt and
                therefore in the cache key.
            candidates: list of candidate dicts; each must carry "symbol" and
                may carry side/conviction/signal breakdown fields.

        Returns:
            (approved_symbols, BasketReview, reasoning_log). approved_symbols
            preserves the input candidate order (keep-set applied), so a
            well-behaved model output cannot reorder the basket.
        """
        symbols = [str(c.get("symbol")) for c in candidates]
        prompt = self._build_prompt(cycle_ctx, candidates)
        phash = self._prompt_hash(prompt)

        entry = self._cache_load(phash)
        if entry is not None:
            raw = entry["response"]
            cached = True
        elif _frozen_mode():
            raise LLMCacheMiss(
                f"frozen replay: no cache entry {self.model_id}/{phash} "
                f"(cycle={cycle_ctx.get('cycle')}) — fill the cache with "
                f"OMEGA_FROZEN_CACHE unset before replaying"
            )
        else:
            raw = self._call_live(prompt, phash)
            cached = False

        review = self._validate(raw, symbols)
        review.cached = cached
        review.prompt_hash = phash
        approved = [s for s in symbols if s in set(review.keep)]
        return approved, review, review.reasoning

    # ------------------------------------------------------------ prompt

    def _build_prompt(self, cycle_ctx: dict, candidates: list[dict]) -> str:
        """Canonical prompt JSON — sorted keys, no whitespace variance."""
        payload = {
            "task": (
                "You are a risk-review layer over a quantitative crypto trading "
                "book. Review this cycle's candidate basket. You may only KEEP, "
                "DROP, or SCALE candidates (scale in [0, 1.5]); you cannot add "
                "positions. Favour vetoing candidates whose signal breakdown "
                "conflicts with the macro/sentiment state or with similar past "
                "decisions that lost money. Respond with ONLY a JSON object: "
                '{"keep": [symbols], "drop": [symbols], '
                '"size_scale": {symbol: float}, "reasoning": str, '
                '"confidence": float in [0,1]}. Every candidate symbol must '
                "appear in exactly one of keep/drop."
            ),
            "cycle_ctx": cycle_ctx,
            "candidates": candidates,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _prompt_hash(prompt: str) -> str:
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]

    # ------------------------------------------------------------- cache

    def _cache_path(self, phash: str) -> Path:
        return self._cache_dir / f"{phash}.json"

    def _cache_load(self, phash: str) -> dict | None:
        p = self._cache_path(phash)
        if not p.is_file():
            return None
        entry = json.loads(p.read_text())
        served = entry.get("model_id")
        if served != self.model_id:
            # V240 pre-reg: a served-model mismatch on replay is a hard error,
            # not a silent accept.
            raise LLMCacheMiss(
                f"cache entry {phash} was served by {served!r}, layer expects "
                f"{self.model_id!r}"
            )
        return entry

    def _cache_store(self, phash: str, prompt: str, response: dict) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        p = self._cache_path(phash)
        p.write_text(
            json.dumps(
                {
                    "model_id": self.model_id,
                    "agy_model_string": self._agy_model,
                    "prompt": prompt,
                    "response": response,
                },
                sort_keys=True,
                indent=1,
            )
            + "\n"
        )
        man = (
            json.loads(self._manifest_path.read_text())
            if self._manifest_path.is_file()
            else {"model_id": self.model_id, "entries": {}}
        )
        man["entries"][phash] = {
            "md5": hashlib.md5(p.read_bytes()).hexdigest(),
            "agy_model_string": self._agy_model,
            "agy_version": self._agy_version(),
        }
        self._manifest_path.write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")

    def _agy_version(self) -> str:
        try:
            out = subprocess.run(
                [self._agy_bin, "--version"], capture_output=True, text=True, timeout=30
            )
            return out.stdout.strip() or out.stderr.strip()
        except Exception:
            return "unknown"

    # ---------------------------------------------------------- live call

    def _call_live(self, prompt: str, phash: str) -> dict:
        """One agy subprocess call per unique prompt; bounded retry on
        malformed JSON, then raise (no neutral fallback)."""
        last_err: Exception | None = None
        for attempt in range(_MAX_MALFORMED_RETRIES + 1):
            proc = subprocess.run(
                [self._agy_bin, "--model", self._agy_model, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"agy exited {proc.returncode}: {proc.stderr.strip()[:500]}"
                )
            try:
                response = self._extract_json(proc.stdout)
                self._cache_store(phash, prompt, response)
                return response
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "reasoning layer: malformed output attempt %d/%d: %s",
                    attempt + 1,
                    _MAX_MALFORMED_RETRIES + 1,
                    exc,
                )
        raise LLMMalformedOutput(str(last_err))

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Parse the model's JSON object, tolerating fences/preamble."""
        s = text.strip()
        if s.startswith("```"):
            s = s.split("```", 2)[1]
            s = s[s.find("{"):]
        start = s.find("{")
        if start < 0:
            raise ValueError("no JSON object in output")
        depth = 0
        for i, ch in enumerate(s[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    obj = json.loads(s[start : i + 1])
                    if not isinstance(obj, dict):
                        raise ValueError("top-level JSON is not an object")
                    return obj
        raise ValueError("unbalanced JSON object in output")

    # --------------------------------------------------------- validation

    @staticmethod
    def _validate(raw: dict, symbols: list[str]) -> BasketReview:
        """Enforce the output schema and the subordinate posture: the layer
        can only trim/scale within bounds; unknown symbols are stripped and
        unmentioned candidates default to keep."""
        sym_set = set(symbols)
        keep = [s for s in raw.get("keep", []) if s in sym_set]
        drop = [s for s in raw.get("drop", []) if s in sym_set and s not in set(keep)]
        mentioned = set(keep) | set(drop)
        keep += [s for s in symbols if s not in mentioned]  # default: keep
        scale_raw = raw.get("size_scale", {}) or {}
        size_scale = {}
        for s, v in scale_raw.items():
            if s in sym_set:
                try:
                    size_scale[s] = min(_SIZE_SCALE_MAX, max(_SIZE_SCALE_MIN, float(v)))
                except (TypeError, ValueError):
                    continue
        try:
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        return BasketReview(
            keep=keep,
            drop=drop,
            size_scale=size_scale,
            reasoning=str(raw.get("reasoning", "")),
            confidence=confidence,
            raw=raw,
        )
