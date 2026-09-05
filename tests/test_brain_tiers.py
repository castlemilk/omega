"""
tests/test_brain_tiers.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the two-tier LLM architecture in omega.core.brain.

Tests:
  - ModelTier enum values
  - _TIER_DEFAULTS coverage
  - BrainAdapter._tier_model() — env var overrides and provider defaults
  - NoBrain.consult() always returns ""
  - AnthropicBrain.consult() — QUICK vs DEEP model selection, HTTP mocked
  - OpenAIBrain.consult() — QUICK vs DEEP model selection, HTTP mocked
  - DeepSeekBrain inherits OpenAI consult with deepseek defaults
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from omega.core.brain import (
    _TIER_DEFAULTS,
    _TIER_ENV,
    AnthropicBrain,
    BrainConfig,
    DeepSeekBrain,
    ModelTier,
    NoBrain,
    OpenAIBrain,
)

# ---------------------------------------------------------------------------
# ModelTier enum
# ---------------------------------------------------------------------------


def test_model_tier_values():
    assert ModelTier.QUICK.value == "quick"
    assert ModelTier.DEEP.value == "deep"


def test_model_tier_distinct():
    assert ModelTier.QUICK != ModelTier.DEEP


# ---------------------------------------------------------------------------
# _TIER_DEFAULTS coverage
# ---------------------------------------------------------------------------


def test_tier_defaults_anthropic():
    assert "claude-haiku" in _TIER_DEFAULTS["anthropic"][ModelTier.QUICK]
    assert "opus" in _TIER_DEFAULTS["anthropic"][ModelTier.DEEP]


def test_tier_defaults_openai():
    assert _TIER_DEFAULTS["openai"][ModelTier.QUICK] == "gpt-4o-mini"
    assert _TIER_DEFAULTS["openai"][ModelTier.DEEP] == "gpt-4o"


def test_tier_defaults_deepseek():
    assert _TIER_DEFAULTS["deepseek"][ModelTier.QUICK] == "deepseek-chat"
    assert _TIER_DEFAULTS["deepseek"][ModelTier.DEEP] == "deepseek-reasoner"


# ---------------------------------------------------------------------------
# _tier_model — provider defaults and env overrides
# ---------------------------------------------------------------------------


def test_tier_model_anthropic_defaults():
    brain = AnthropicBrain(BrainConfig(provider="anthropic", model="claude-sonnet-4-6"))
    assert "haiku" in brain._tier_model(ModelTier.QUICK)
    assert "opus" in brain._tier_model(ModelTier.DEEP)


def test_tier_model_env_override_quick(monkeypatch):
    monkeypatch.setenv("OMEGA_BRAIN_QUICK_MODEL", "custom-quick-model")
    # Disable the shell transport. AnthropicBrain is "shell path first, urllib
    # fallback" — it invokes the `claude` CLI by subprocess and only falls back to
    # urllib. These tests patch urlopen, so on any machine with an authenticated
    # CLI the patch intercepted nothing and the assertions ran against REAL model
    # output: that is why test_anthropic_consult_no_api_key received a genuine
    # answer where it expected "". Every run of this file was also spending real
    # tokens.
    monkeypatch.setattr(
        "omega.core.brain.AnthropicBrain._shell_consult", lambda *a, **k: ""
    )
    brain = AnthropicBrain(BrainConfig(provider="anthropic"))
    assert brain._tier_model(ModelTier.QUICK) == "custom-quick-model"


def test_tier_model_env_override_deep(monkeypatch):
    monkeypatch.setenv("OMEGA_BRAIN_DEEP_MODEL", "custom-deep-model")
    # Disable the shell transport. AnthropicBrain is "shell path first, urllib
    # fallback" — it invokes the `claude` CLI by subprocess and only falls back to
    # urllib. These tests patch urlopen, so on any machine with an authenticated
    # CLI the patch intercepted nothing and the assertions ran against REAL model
    # output: that is why test_anthropic_consult_no_api_key received a genuine
    # answer where it expected "". Every run of this file was also spending real
    # tokens.
    monkeypatch.setattr(
        "omega.core.brain.AnthropicBrain._shell_consult", lambda *a, **k: ""
    )
    brain = AnthropicBrain(BrainConfig(provider="anthropic"))
    assert brain._tier_model(ModelTier.DEEP) == "custom-deep-model"


def test_tier_model_openai_defaults():
    brain = OpenAIBrain(BrainConfig(provider="openai"))
    assert brain._tier_model(ModelTier.QUICK) == "gpt-4o-mini"
    assert brain._tier_model(ModelTier.DEEP) == "gpt-4o"


# ---------------------------------------------------------------------------
# NoBrain.consult
# ---------------------------------------------------------------------------


def test_nobrain_consult_quick():
    brain = NoBrain()
    result = brain.consult("What is the trend?", ModelTier.QUICK)
    assert result == ""


def test_nobrain_consult_deep():
    brain = NoBrain()
    result = brain.consult("Debate the risk.", ModelTier.DEEP)
    assert result == ""


def test_nobrain_consult_default_tier():
    brain = NoBrain()
    result = brain.consult("Any prompt")
    assert result == ""


# ---------------------------------------------------------------------------
# AnthropicBrain.consult — model selected per tier
# ---------------------------------------------------------------------------


def _make_anthropic_response(text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({"content": [{"text": text}]}).encode()
    return mock_resp


def test_anthropic_consult_no_api_key(monkeypatch):
    # Ensure no API key is resolvable (clear both canonical key and legacy alias)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    from omega.core import credentials as creds_mod
    monkeypatch.setattr(creds_mod.credentials, "_cache", {})
    monkeypatch.setattr(creds_mod.credentials, "_env_file_loaded", True)  # skip .env load
    # Disable the shell transport. AnthropicBrain is "shell path first, urllib
    # fallback" — it invokes the `claude` CLI by subprocess and only falls back to
    # urllib. These tests patch urlopen, so on any machine with an authenticated
    # CLI the patch intercepted nothing and the assertions ran against REAL model
    # output: that is why test_anthropic_consult_no_api_key received a genuine
    # answer where it expected "". Every run of this file was also spending real
    # tokens.
    monkeypatch.setattr(
        "omega.core.brain.AnthropicBrain._shell_consult", lambda *a, **k: ""
    )
    brain = AnthropicBrain(BrainConfig(provider="anthropic"))
    # no key set — should return ""
    result = brain.consult("hello")
    assert result == ""


def test_anthropic_consult_quick_uses_haiku(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Disable the shell transport. AnthropicBrain is "shell path first, urllib
    # fallback" — it invokes the `claude` CLI by subprocess and only falls back to
    # urllib. These tests patch urlopen, so on any machine with an authenticated
    # CLI the patch intercepted nothing and the assertions ran against REAL model
    # output: that is why test_anthropic_consult_no_api_key received a genuine
    # answer where it expected "". Every run of this file was also spending real
    # tokens.
    monkeypatch.setattr(
        "omega.core.brain.AnthropicBrain._shell_consult", lambda *a, **k: ""
    )
    brain = AnthropicBrain(BrainConfig(provider="anthropic"))

    captured = {}

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data)
        captured["model"] = body["model"]
        return _make_anthropic_response("quick answer")

    with patch("omega.core.brain.urllib.request.urlopen", fake_urlopen):
        result = brain.consult("signal prompt", ModelTier.QUICK)

    assert result == "quick answer"
    assert "haiku" in captured["model"]


def test_anthropic_consult_deep_uses_opus(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Disable the shell transport. AnthropicBrain is "shell path first, urllib
    # fallback" — it invokes the `claude` CLI by subprocess and only falls back to
    # urllib. These tests patch urlopen, so on any machine with an authenticated
    # CLI the patch intercepted nothing and the assertions ran against REAL model
    # output: that is why test_anthropic_consult_no_api_key received a genuine
    # answer where it expected "". Every run of this file was also spending real
    # tokens.
    monkeypatch.setattr(
        "omega.core.brain.AnthropicBrain._shell_consult", lambda *a, **k: ""
    )
    brain = AnthropicBrain(BrainConfig(provider="anthropic"))

    captured = {}

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data)
        captured["model"] = body["model"]
        return _make_anthropic_response("deep reasoning")

    with patch("omega.core.brain.urllib.request.urlopen", fake_urlopen):
        result = brain.consult("adversarial debate prompt", ModelTier.DEEP)

    assert result == "deep reasoning"
    assert "opus" in captured["model"]


def test_anthropic_consult_env_model_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OMEGA_BRAIN_QUICK_MODEL", "claude-sonnet-4-6")
    # Disable the shell transport. AnthropicBrain is "shell path first, urllib
    # fallback" — it invokes the `claude` CLI by subprocess and only falls back to
    # urllib. These tests patch urlopen, so on any machine with an authenticated
    # CLI the patch intercepted nothing and the assertions ran against REAL model
    # output: that is why test_anthropic_consult_no_api_key received a genuine
    # answer where it expected "". Every run of this file was also spending real
    # tokens.
    monkeypatch.setattr(
        "omega.core.brain.AnthropicBrain._shell_consult", lambda *a, **k: ""
    )
    brain = AnthropicBrain(BrainConfig(provider="anthropic"))

    captured = {}

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data)
        captured["model"] = body["model"]
        return _make_anthropic_response("override result")

    with patch("omega.core.brain.urllib.request.urlopen", fake_urlopen):
        result = brain.consult("prompt", ModelTier.QUICK)

    assert result == "override result"
    assert captured["model"] == "claude-sonnet-4-6"


def test_anthropic_consult_error_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Disable the shell transport. AnthropicBrain is "shell path first, urllib
    # fallback" — it invokes the `claude` CLI by subprocess and only falls back to
    # urllib. These tests patch urlopen, so on any machine with an authenticated
    # CLI the patch intercepted nothing and the assertions ran against REAL model
    # output: that is why test_anthropic_consult_no_api_key received a genuine
    # answer where it expected "". Every run of this file was also spending real
    # tokens.
    monkeypatch.setattr(
        "omega.core.brain.AnthropicBrain._shell_consult", lambda *a, **k: ""
    )
    brain = AnthropicBrain(BrainConfig(provider="anthropic"))

    def fake_urlopen(req, timeout=30):
        raise ConnectionError("network failure")

    with patch("omega.core.brain.urllib.request.urlopen", fake_urlopen):
        result = brain.consult("prompt", ModelTier.QUICK)

    assert result == ""


# ---------------------------------------------------------------------------
# OpenAIBrain.consult — model selected per tier
# ---------------------------------------------------------------------------


def _make_openai_response(text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": text}}]}
    ).encode()
    return mock_resp


def test_openai_consult_no_api_key():
    brain = OpenAIBrain(BrainConfig(provider="openai"))
    assert brain.consult("hello") == ""


def test_openai_consult_quick_uses_mini(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    brain = OpenAIBrain(BrainConfig(provider="openai"))

    captured = {}

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data)
        captured["model"] = body["model"]
        return _make_openai_response("mini result")

    with patch("omega.core.brain.urllib.request.urlopen", fake_urlopen):
        result = brain.consult("signal prompt", ModelTier.QUICK)

    assert result == "mini result"
    assert captured["model"] == "gpt-4o-mini"


def test_openai_consult_deep_uses_gpt4o(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    brain = OpenAIBrain(BrainConfig(provider="openai"))

    captured = {}

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data)
        captured["model"] = body["model"]
        return _make_openai_response("deep result")

    with patch("omega.core.brain.urllib.request.urlopen", fake_urlopen):
        result = brain.consult("debate prompt", ModelTier.DEEP)

    assert result == "deep result"
    assert captured["model"] == "gpt-4o"


def test_openai_consult_error_returns_empty(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    brain = OpenAIBrain(BrainConfig(provider="openai"))

    with patch("omega.core.brain.urllib.request.urlopen", side_effect=OSError("timeout")):
        result = brain.consult("prompt", ModelTier.DEEP)

    assert result == ""


# ---------------------------------------------------------------------------
# DeepSeek inherits OpenAI consult with its own defaults
# ---------------------------------------------------------------------------


def test_deepseek_tier_defaults():
    brain = DeepSeekBrain(BrainConfig(provider="deepseek"))
    assert brain._tier_model(ModelTier.QUICK) == "deepseek-chat"
    assert brain._tier_model(ModelTier.DEEP) == "deepseek-reasoner"


# ---------------------------------------------------------------------------
# _TIER_ENV maps tiers to env var names
# ---------------------------------------------------------------------------


def test_tier_env_keys():
    assert _TIER_ENV[ModelTier.QUICK] == "OMEGA_BRAIN_QUICK_MODEL"
    assert _TIER_ENV[ModelTier.DEEP] == "OMEGA_BRAIN_DEEP_MODEL"
