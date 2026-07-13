"""
omega.nodes.victoria.reasoning_layer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
V240 Track D — hermetic per-cycle basket review by a frontier reasoning model.

Model (V240.md "Model choice"): **Gemini via the `agy` CLI** (subprocess;
DeepSeek/Kimi/OpenRouter keys unavailable). The CLI exposes no temperature
control, so live-call determinism is NOT assumed: determinism is guaranteed
entirely by the frozen cache below. The quant book retains full veto — the
layer can only trim (drop) or scale positions within [0, 1], never invent
or up-size one (V139 subordinate posture; V241 contract).

Hermetic cache (V215/V238 pattern):
  data/frozen_llm_cache/{model_id}/{prompt_hash}.json
  prompt_hash = sha256(canonical_prompt_json)[:16]
Under OMEGA_FROZEN_CACHE=1 a cache miss **raises LLMCacheMiss** — never a live
call, never a neutral stub. Cache-fill runs set OMEGA_LLM_CACHE_FILL=1 on top
of the frozen grid conditions (see _frozen_mode) so fill-time prompts hash-match
replay-time prompts.
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
import time
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
# V241 contract tightening: the layer may never up-size past the strategy's
# proposed weight — scale is [0, 1], not the V240 draft's [0, 1.5].
_SIZE_SCALE_MIN, _SIZE_SCALE_MAX = 0.0, 1.0


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
    """Frozen replay for the LLM path.

    OMEGA_LLM_CACHE_FILL=1 overrides OMEGA_FROZEN_CACHE=1 for the LLM path
    ONLY: a cache-fill run must execute under the *identical* frozen
    market/macro conditions the grid will replay (the prompt embeds in-run
    computed values, so fill-time and replay-time prompts must hash-match),
    while cache misses go live via the agy subprocess (which the urllib/HTTP
    fences do not and should not intercept).
    """
    if os.environ.get("OMEGA_LLM_CACHE_FILL") == "1":
        return False
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
        t0 = time.perf_counter()
        symbols = [str(c.get("symbol")) for c in candidates]
        prompt = self._build_prompt(cycle_ctx, candidates)
        phash = self._prompt_hash(prompt)
        raw, cached = self._dispatch(prompt, phash, cycle_ctx.get("cycle"))
        review = self._validate(raw, symbols)
        review.cached = cached
        review.prompt_hash = phash
        approved = [s for s in symbols if s in set(review.keep)]
        self._trace(cycle_ctx, symbols, approved, review, t0)
        return approved, review, review.reasoning

    def _dispatch(
        self, prompt: str, phash: str, cycle: object = None
    ) -> tuple[dict, bool]:
        """Resolve a single prompt to a raw response dict + cached flag.

        The V240/V241 cache/frozen/live contract, factored out of
        ``review_basket`` so the specialist ensemble (V258) shares exactly one
        code path: cache hit → served; frozen miss → ``LLMCacheMiss``; else
        one live ``agy`` call. No neutral stub, ever.
        """
        entry = self._cache_load(phash)
        if entry is not None:
            return entry["response"], True
        if _frozen_mode():
            raise LLMCacheMiss(
                f"frozen replay: no cache entry {self.model_id}/{phash} "
                f"(cycle={cycle}) — fill the cache with "
                f"OMEGA_FROZEN_CACHE unset before replaying"
            )
        return self._call_live(prompt, phash), False

    @staticmethod
    def _trace(
        cycle_ctx: dict,
        symbols: list[str],
        approved: list[str],
        review: BasketReview,
        t0: float,
    ) -> None:
        """V241 phase-0 inertness tracer — one JSONL line per review call.

        Active only when OMEGA_REASONING_TRACE names a path; pure observability
        (appends to a sidecar file, feeds nothing back into the run). Latency is
        wall-clock for ops visibility only — it never touches trading state.
        """
        path = os.environ.get("OMEGA_REASONING_TRACE")
        if not path:
            return
        scaled_down = {
            s: v for s, v in review.size_scale.items() if v < 1.0 and s in set(approved)
        }
        rec = {
            "cycle": cycle_ctx.get("cycle"),
            "regime": cycle_ctx.get("regime"),
            "window": os.environ.get("WINDOW_LABEL", ""),
            "candidates_in": len(symbols),
            "candidates_out": len(approved),
            "drops": review.drop,
            "scaled_down": scaled_down,
            "intervened": bool(review.drop or scaled_down),
            "confidence": review.confidence,
            "cache_hit": review.cached,
            "prompt_hash": review.prompt_hash,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
        }
        try:
            with open(path, "a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
        except OSError as exc:  # tracing must never kill a run
            logger.warning("reasoning trace write failed: %s", exc)

    # ------------------------------------------------------------ prompt

    def _build_prompt(self, cycle_ctx: dict, candidates: list[dict]) -> str:
        """Canonical prompt JSON — sorted keys, no whitespace variance."""
        payload = {
            "task": (
                "You are a risk-review layer over a quantitative crypto trading "
                "book. Review this cycle's candidate basket. You may only KEEP, "
                "DROP, or SCALE candidates (scale in [0, 1] — you may only "
                "reduce size, never increase it); you cannot add "
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
                f"cache entry {phash} was served by {served!r}, layer expects {self.model_id!r}"
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
                raise RuntimeError(f"agy exited {proc.returncode}: {proc.stderr.strip()[:500]}")
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
            s = s[s.find("{") :]
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


# --------------------------------------------------------------------------
# V258 Track E — specialist ensemble
# --------------------------------------------------------------------------
# V241 died because ONE agent reviewed the whole composite. Track E's premise:
# decompose the review into per-signal-class specialists (each scoring per-name
# conviction on a 1-5 scale) then a meta-prompt that aggregates. The ensemble
# reuses ReasoningLayer's cache/frozen/live plumbing verbatim (composition, not
# rewrite — V258 pre-registration). Model, cache namespace, and drop/scale-only
# posture are identical to V241; only the prompt decomposition differs.

# (lens_key, human description) — one specialist per pre-registered signal class.
SPECIALIST_LENSES: list[tuple[str, str]] = [
    ("fear_greed", "crypto market fear/greed and sentiment extremes"),
    ("macro", "equity-volatility (VIX) regime and US-dollar strength (DXY)"),
    ("yield_curve", "the US Treasury yield curve (2s/10s) and rates backdrop"),
    ("funding_oi", "perpetual-futures funding rates and open-interest positioning"),
    ("gdelt_news", "geopolitical, regulatory and macro news-flow tone (GDELT)"),
]


@dataclass
class SpecialistScores:
    """One specialist's per-name conviction scores (1-5) for a cycle."""

    lens: str
    scores: dict[str, int]
    reasoning: str
    cached: bool = False
    prompt_hash: str = ""


class SpecialistEnsemble:
    """V258 specialist-ensemble review: N per-signal-class scorers + a meta-combiner.

    Drop-in comparable with ``ReasoningLayer.review_basket`` — same return shape
    ``(approved_symbols, BasketReview, reasoning)`` and the same subordinate posture
    (keep/drop/scale-in-[0,1] only). Uses a composed ``ReasoningLayer`` for the
    cache/frozen/live dispatch so there is exactly one plumbing code path.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        cache_root: Path | None = None,
        agy_bin: str = "agy",
        timeout_s: float = 300.0,
        lenses: list[tuple[str, str]] | None = None,
    ) -> None:
        self._layer = ReasoningLayer(model_id, cache_root, agy_bin, timeout_s)
        self.model_id = self._layer.model_id
        self._lenses = lenses if lenses is not None else list(SPECIALIST_LENSES)

    # ------------------------------------------------------------- public

    def review_basket(
        self, cycle_ctx: dict, candidates: list[dict]
    ) -> tuple[list[str], BasketReview, str]:
        """Score the basket through each specialist, then meta-combine to a review."""
        t0 = time.perf_counter()
        symbols = [str(c.get("symbol")) for c in candidates]
        spec_scores = self.specialist_scores(cycle_ctx, candidates)
        meta_prompt = self._build_meta_prompt(cycle_ctx, candidates, spec_scores)
        phash = ReasoningLayer._prompt_hash(meta_prompt)
        raw, cached = self._layer._dispatch(meta_prompt, phash, cycle_ctx.get("cycle"))
        review = self._layer._validate(raw, symbols)
        review.cached = cached and all(s.cached for s in spec_scores)
        review.prompt_hash = phash
        approved = [s for s in symbols if s in set(review.keep)]
        ReasoningLayer._trace(cycle_ctx, symbols, approved, review, t0)
        return approved, review, review.reasoning

    def specialist_scores(
        self, cycle_ctx: dict, candidates: list[dict]
    ) -> list[SpecialistScores]:
        """Run every specialist prompt; return per-lens 1-5 per-name scores."""
        symbols = [str(c.get("symbol")) for c in candidates]
        out: list[SpecialistScores] = []
        for lens_key, lens_desc in self._lenses:
            prompt = self._build_specialist_prompt(lens_key, lens_desc, cycle_ctx, candidates)
            phash = ReasoningLayer._prompt_hash(prompt)
            raw, cached = self._layer._dispatch(prompt, phash, cycle_ctx.get("cycle"))
            out.append(
                SpecialistScores(
                    lens=lens_key,
                    scores=self._validate_scores(raw, symbols),
                    reasoning=str(raw.get("reasoning", "")),
                    cached=cached,
                    prompt_hash=phash,
                )
            )
        return out

    # ------------------------------------------------------------ prompts

    @staticmethod
    def _build_specialist_prompt(
        lens_key: str, lens_desc: str, cycle_ctx: dict, candidates: list[dict]
    ) -> str:
        payload = {
            "task": (
                f"You are the {lens_desc} specialist on a quantitative crypto "
                "trading desk. Judge each candidate position ONLY through your "
                "lens; ignore signal classes outside your remit. Score each "
                "candidate's conviction on an integer 1-5 scale (1 = your lens "
                "strongly argues against this position, 3 = neutral, 5 = your "
                "lens strongly supports it). You are a reviewer, not a trader: "
                "you may not change sides or add positions. Respond with ONLY a "
                'JSON object: {"scores": {symbol: int in [1,5]}, "reasoning": str}. '
                "Every candidate symbol must appear exactly once in scores."
            ),
            "lens": lens_key,
            "cycle_ctx": cycle_ctx,
            "candidates": candidates,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _build_meta_prompt(
        cycle_ctx: dict, candidates: list[dict], spec_scores: list[SpecialistScores]
    ) -> str:
        # Canonical per-name score matrix: {symbol: {lens: score}} — sorted so the
        # prompt (and thus the cache key) is order-invariant.
        matrix: dict[str, dict[str, int]] = {}
        for ss in spec_scores:
            for sym, sc in ss.scores.items():
                matrix.setdefault(sym, {})[ss.lens] = sc
        payload = {
            "task": (
                "You are the meta risk-review layer over a quantitative crypto "
                "trading book. Five signal-class specialists have each scored the "
                "cycle's candidates 1-5 through their own lens (see "
                "specialist_scores). Aggregate those scores into a final review. "
                "You may only KEEP, DROP, or SCALE candidates (scale in [0, 1] — "
                "you may only reduce size, never increase it); you cannot add "
                "positions or change sides. Favour dropping/scaling candidates the "
                "specialists broadly score low (<=2) or on which they strongly "
                "disagree against the macro/sentiment state. Respond with ONLY a "
                'JSON object: {"keep": [symbols], "drop": [symbols], '
                '"size_scale": {symbol: float}, "reasoning": str, '
                '"confidence": float in [0,1]}. Every candidate symbol must appear '
                "in exactly one of keep/drop."
            ),
            "cycle_ctx": cycle_ctx,
            "candidates": candidates,
            "specialist_scores": matrix,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    # --------------------------------------------------------- validation

    @staticmethod
    def _validate_scores(raw: dict, symbols: list[str]) -> dict[str, int]:
        """Clamp specialist scores to integer [1,5]; unknown symbols dropped,
        unmentioned candidates default to a neutral 3."""
        sym_set = set(symbols)
        scores_raw = raw.get("scores", {}) or {}
        out: dict[str, int] = {}
        for s, v in scores_raw.items():
            if s in sym_set:
                try:
                    out[s] = int(min(5, max(1, round(float(v)))))
                except (TypeError, ValueError):
                    continue
        for s in symbols:
            out.setdefault(s, 3)  # neutral default — never invent conviction
        return out
