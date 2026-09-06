"""V281: the reasoning layer's local-model provider.

Context that must not be lost: the reasoning layer's TRADING hypothesis is REFUTED.
V241 measured per-cycle basket review on the 32-window walk-forward grid and found it
"ACTIVE but adds variance, not expectancy"; V258's specialist-ensemble rehabilitation
was refuted at Phase 0. `reasoning_layer_enabled` is False and V281 does not change it.

V281 adds a PROVIDER, so future hypotheses are cheap to test. These tests pin the two
properties the whole design rests on — the hermetic contract and the layer's bounded
authority — per-provider rather than only for the original agy path.
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from omega.nodes.victoria.reasoning_layer import (
    _PROVIDERS,
    LLMCacheMiss,
    ReasoningLayer,
)

# ----------------------------------------------------------------- G1: compat

def test_agy_model_ids_still_construct_and_route_to_agy() -> None:
    """The 693 committed gemini-3.1-pro-low cache entries must stay reachable."""
    layer = ReasoningLayer(model_id="gemini-3.1-pro-low")
    assert layer._provider == "agy"
    assert layer._agy_model == "Gemini 3.1 Pro (Low)"
    assert layer.model_id == "gemini-3.1-pro-low"


def test_local_model_id_now_constructs() -> None:
    """Before V281 this raised ValueError — every id outside the agy dict did."""
    layer = ReasoningLayer(model_id="qwen3.8-27b-mlx")
    assert layer._provider == "ollama"
    assert layer._agy_model == "qwen3.8:27b-mlx"


def test_unknown_model_id_still_raises() -> None:
    with pytest.raises(ValueError, match="unknown model_id"):
        ReasoningLayer(model_id="not-a-real-model")


def test_cache_dir_is_namespaced_per_model(tmp_path) -> None:
    """Providers must never shadow each other's cache."""
    a = ReasoningLayer(model_id="gemini-3.1-pro-low", cache_root=tmp_path)
    b = ReasoningLayer(model_id="qwen3.8-27b-mlx", cache_root=tmp_path)
    assert a._cache_dir != b._cache_dir
    assert a._cache_dir.name == "gemini-3.1-pro-low"
    assert b._cache_dir.name == "qwen3.8-27b-mlx"


# ------------------------------------------------- G2: the hermetic contract

def test_frozen_replay_raises_cache_miss_for_the_local_provider(tmp_path) -> None:
    """THE gate. A frozen replay must never make a live call, for ANY provider.

    If this regresses, a cache miss would silently reach out to a local model
    mid-backtest and the run would stop being a function of committed bytes.
    """
    layer = ReasoningLayer(model_id="qwen3.8-27b-mlx", cache_root=tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "OMEGA_LLM_CACHE_FILL"}
    env["OMEGA_FROZEN_CACHE"] = "1"
    with (
        mock.patch.dict(os.environ, env, clear=True),
        mock.patch.object(ReasoningLayer, "_invoke_provider") as spy,
    ):
        with pytest.raises(LLMCacheMiss):
            layer.review_basket(
                {"cycle": 1, "regime": "normal"},
                [{"symbol": "ETHUSDT", "side": "long", "weight": 0.5}],
            )
        spy.assert_not_called()


# ---------------------------------------------------- G3: bounded authority

def test_size_scale_is_still_clamped_to_one_for_a_local_model(tmp_path) -> None:
    """The V241 posture: trim or scale DOWN only — never invent, never up-size.

    A local model is not more trusted than a frontier one; the provider changes who
    answers, never what the answer is permitted to do.
    """
    layer = ReasoningLayer(model_id="qwen3.8-27b-mlx", cache_root=tmp_path)
    candidates = [{"symbol": "ETHUSDT", "side": "long", "weight": 0.5}]
    rogue = json.dumps({
        "keep": ["ETHUSDT"],
        "drop": [],
        "size_scale": {"ETHUSDT": 4.0},      # attempts a 4x up-size
        "reasoning": "very confident",
        "confidence": 0.99,
    })
    with mock.patch.dict(os.environ, {"OMEGA_LLM_CACHE_FILL": "1"}), mock.patch.object(
        ReasoningLayer, "_invoke_provider", return_value=(rogue, "some thinking")
    ):
        _kept, review, _ = layer.review_basket({"cycle": 1}, candidates)
    assert review.size_scale.get("ETHUSDT", 1.0) <= 1.0, (
        f"local model up-sized a position to {review.size_scale.get('ETHUSDT')} — the "
        "V241 [0,1] contract has been widened by the provider change."
    )


def test_thinking_is_captured_but_not_load_bearing(tmp_path) -> None:
    """The trace is recorded for audit; only keep/drop/size_scale move a position."""
    layer = ReasoningLayer(model_id="qwen3.8-27b-mlx", cache_root=tmp_path)
    payload = json.dumps({
        "keep": ["ETHUSDT"], "drop": [], "size_scale": {},
        "reasoning": "r", "confidence": 0.5,
    })
    with mock.patch.dict(os.environ, {"OMEGA_LLM_CACHE_FILL": "1"}), mock.patch.object(
        ReasoningLayer, "_invoke_provider",
        return_value=(payload, "step 1: consider vol"),
    ):
        _kept, review, _ = layer.review_basket(
            {"cycle": 1}, [{"symbol": "ETHUSDT", "side": "long", "weight": 0.5}]
        )
    assert review.thinking == "step 1: consider vol"
    assert "ETHUSDT" in review.keep


def test_every_registered_provider_has_a_known_kind() -> None:
    """Guards typos in the registry — an unknown kind silently falls back to agy."""
    bad = {m: sp for m, sp in _PROVIDERS.items() if sp.get("kind") not in {"agy", "ollama"}}
    assert bad == {}, f"provider(s) with an unrecognised kind: {bad}"
