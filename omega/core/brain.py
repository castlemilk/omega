"""
omega.core.brain
~~~~~~~~~~~~~~~~
Pluggable LLM "brain" adapters for Omega nodes.

Every node can optionally carry a BrainAdapter. When a node's improve() or
any other operation is called, it can consult the brain for a structured
decision rather than using only rule-based logic.

Design:
  BrainConfig   — configuration (provider, model, temperature, …)
  BrainRequest  — what we send to the LLM (node state, metrics, memories)
  BrainResponse — what we get back  (action, parameters, reasoning, confidence)
  BrainAdapter  — abstract contract
  NoBrain       — default; pure rule-based, no LLM (current behaviour)
  AnthropicBrain / OpenAIBrain / OllamaBrain — provider stubs

BRAIN_REGISTRY maps provider name → adapter class.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# ModelTier — two-tier LLM selection
# ---------------------------------------------------------------------------


class ModelTier(Enum):
    """
    Selects which model class to use for a brain call.

    QUICK — fast, cheap models for high-frequency calls (signal extraction, filters).
             Default: claude-haiku-4-5 / gpt-4o-mini.  Override: OMEGA_BRAIN_QUICK_MODEL.
    DEEP  — slow, smart models for complex reasoning (adversarial debate, planning).
             Default: claude-opus-4-6 / gpt-4o.  Override: OMEGA_BRAIN_DEEP_MODEL.
    """

    QUICK = "quick"
    DEEP = "deep"


# Provider-specific tier defaults
_TIER_DEFAULTS: dict[str, dict[ModelTier, str]] = {
    "anthropic": {
        ModelTier.QUICK: "claude-haiku-4-5-20251001",
        ModelTier.DEEP: "claude-opus-4-6",
    },
    "openai": {
        ModelTier.QUICK: "gpt-4o-mini",
        ModelTier.DEEP: "gpt-4o",
    },
    "deepseek": {
        ModelTier.QUICK: "deepseek-chat",
        ModelTier.DEEP: "deepseek-reasoner",
    },
    "ollama": {
        ModelTier.QUICK: "llama3",
        ModelTier.DEEP: "llama3",
    },
    "google": {
        ModelTier.QUICK: "gemini-1.5-flash",
        ModelTier.DEEP: "gemini-1.5-pro",
    },
}

_TIER_ENV: dict[ModelTier, str] = {
    ModelTier.QUICK: "OMEGA_BRAIN_QUICK_MODEL",
    ModelTier.DEEP: "OMEGA_BRAIN_DEEP_MODEL",
}


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass
class BrainConfig:
    """All configuration needed to initialise a BrainAdapter."""

    provider: str = "none"  # "anthropic" | "openai" | "google" | "deepseek" | "ollama" | "none"
    model: str = ""  # e.g. "claude-sonnet-4-6", "gpt-4o", "llama3"
    temperature: float = 0.7
    max_tokens: int = 1024
    system_prompt: str = ""
    extra_config: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "system_prompt": self.system_prompt,
            "extra_config": self.extra_config,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BrainConfig:
        return cls(
            provider=d.get("provider", "none"),
            model=d.get("model", ""),
            temperature=float(d.get("temperature", 0.7)),
            max_tokens=int(d.get("max_tokens", 1024)),
            system_prompt=d.get("system_prompt", ""),
            extra_config=d.get("extra_config", {}),
        )


@dataclass
class BrainRequest:
    """Everything we give the LLM so it can make a decision."""

    node_id: str
    operation: str  # "execute" | "evaluate" | "improve" | "analyze"
    current_state: dict[str, Any]  # node state snapshot
    recent_metrics: dict[str, float]  # recent evaluation metrics
    relevant_memories: list[dict]  # from MemoryKernel
    available_actions: list[str]  # verbs the node can take
    domain_context: str  # node.describe() + injected skill content
    trace_id: str = ""
    skill_hints: list[str] = field(default_factory=list)  # tags used to load skills


@dataclass
class BrainResponse:
    """Structured decision returned by the LLM."""

    action: str  # which action to take
    parameters: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""  # stored in activity log
    confidence: float = 0.0  # 0.0 - 1.0


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class BrainAdapter(ABC):
    """Contract for any LLM provider brain adapter."""

    @abstractmethod
    def think(self, request: BrainRequest) -> BrainResponse:
        """Send context to the LLM; return a structured decision."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is reachable (key configured, service up)."""

    def consult(self, prompt: str, tier: ModelTier = ModelTier.QUICK) -> str:
        """
        Send a plain-text prompt; return the model's text response.

        Lighter-weight than think() — no structured request/response wrapping.
        Use ModelTier.QUICK for signal generation (fast, cheap).
        Use ModelTier.DEEP for adversarial debate and complex reasoning (slow, smart).

        Tier model selection precedence:
          1. OMEGA_BRAIN_QUICK_MODEL / OMEGA_BRAIN_DEEP_MODEL env vars
          2. Provider-specific defaults in _TIER_DEFAULTS
          3. The adapter's configured model

        Returns empty string if the provider is unavailable or on error.
        Subclasses should override to make a real HTTP call.
        """
        return ""

    def _tier_model(self, tier: ModelTier) -> str:
        """Resolve the model name for the given tier, respecting env overrides."""
        env_override = os.environ.get(_TIER_ENV.get(tier, ""), "")
        if env_override:
            return env_override
        provider = self.provider_name()
        return _TIER_DEFAULTS.get(provider, {}).get(tier, "")

    def provider_name(self) -> str:
        """Human-readable name for logging / StateStore records."""
        return type(self).__name__


# ---------------------------------------------------------------------------
# NoBrain — default, pure rule-based, zero latency, no cost
# ---------------------------------------------------------------------------


class NoBrain(BrainAdapter):
    """
    Default brain adapter — no LLM, no cost.

    think() always returns action="pass" so caller falls back to its
    existing rule-based logic.  This preserves all current behaviour when
    no brain is configured.
    """

    def __init__(self, config: BrainConfig | None = None) -> None:
        pass  # config ignored; NoBrain is always a no-op

    def think(self, request: BrainRequest) -> BrainResponse:
        return BrainResponse(
            action="pass",
            reasoning="No LLM brain configured — using rule-based logic",
            confidence=0.0,
        )

    def consult(self, prompt: str, tier: ModelTier = ModelTier.QUICK) -> str:
        return ""

    def is_available(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "none"


# ---------------------------------------------------------------------------
# AnthropicBrain — Claude adapter (uses urllib, no SDK dependency)
# ---------------------------------------------------------------------------

_ANTHROPIC_SYSTEM = """\
You are a decision-making brain embedded inside an autonomous AI node.
You receive structured context about the node's current state, recent performance
metrics, and available actions. Your job is to decide which action to take and why.

Always respond with valid JSON only — no markdown, no prose, no code fences:
{
  "action": "<one of the available_actions>",
  "parameters": {},
  "reasoning": "<concise explanation, 1-2 sentences>",
  "confidence": <float 0.0-1.0>
}

If you are unsure or the context is insufficient, respond with action="pass" and
confidence=0.0 so the node falls back to its rule-based logic.
"""


class AnthropicBrain(BrainAdapter):
    """
    Claude adapter via Anthropic Messages API.

    Requires ANTHROPIC_API_KEY env var (or api_key in extra_config).
    Falls back gracefully to action="pass" if key is absent.

    Stub status: interface complete, HTTP call implemented.
    Activate by setting ANTHROPIC_API_KEY.
    """

    API_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, config: BrainConfig) -> None:
        self.config = config
        self._api_key = config.extra_config.get("api_key") or os.environ.get(
            "ANTHROPIC_API_KEY", ""
        )
        self._model = config.model or "claude-sonnet-4-6"
        self._system = config.system_prompt or _ANTHROPIC_SYSTEM

    def is_available(self) -> bool:
        return bool(self._api_key)

    def think(self, request: BrainRequest) -> BrainResponse:
        if not self._api_key:
            return BrainResponse(
                action="pass",
                reasoning="AnthropicBrain: no API key — set ANTHROPIC_API_KEY",
                confidence=0.0,
            )
        try:
            prompt = self._build_prompt(request)
            payload = {
                "model": self._model,
                "max_tokens": self.config.max_tokens,
                "system": self._system,
                "messages": [{"role": "user", "content": prompt}],
            }
            if self.config.temperature != 1.0:
                payload["temperature"] = self.config.temperature

            req = urllib.request.Request(
                self.API_URL,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self._api_key,
                    "anthropic-version": self.ANTHROPIC_VERSION,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())

            text = body["content"][0]["text"].strip()
            return self._parse_response(text)

        except Exception as exc:
            return BrainResponse(
                action="pass",
                reasoning=f"AnthropicBrain error: {exc}",
                confidence=0.0,
            )

    def consult(self, prompt: str, tier: ModelTier = ModelTier.QUICK) -> str:
        if not self._api_key:
            return ""
        model = self._tier_model(tier) or self._model
        try:
            payload = {
                "model": model,
                "max_tokens": self.config.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                self.API_URL,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self._api_key,
                    "anthropic-version": self.ANTHROPIC_VERSION,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
            return str(body["content"][0]["text"]).strip()
        except Exception:
            return ""

    def _build_prompt(self, request: BrainRequest) -> str:
        metrics_str = json.dumps(request.recent_metrics, indent=2)
        state_str = json.dumps(request.current_state, indent=2)
        memories_str = (
            json.dumps(request.relevant_memories[:5], indent=2)
            if request.relevant_memories
            else "[]"
        )
        return (
            f"Node ID: {request.node_id}\n"
            f"Operation: {request.operation}\n"
            f"Domain: {request.domain_context}\n\n"
            f"Current State:\n{state_str}\n\n"
            f"Recent Metrics:\n{metrics_str}\n\n"
            f"Relevant Memories (up to 5):\n{memories_str}\n\n"
            f"Available Actions: {request.available_actions}\n\n"
            f"Decide which action to take and respond with JSON."
        )

    def _parse_response(self, text: str) -> BrainResponse:
        # Strip markdown fences if present
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("{") or part.startswith("json\n{"):
                    text = part.lstrip("json").strip()
                    break
        try:
            data = json.loads(text)
            return BrainResponse(
                action=str(data.get("action", "pass")),
                parameters=data.get("parameters") or {},
                reasoning=str(data.get("reasoning", "")),
                confidence=float(data.get("confidence", 0.0)),
            )
        except json.JSONDecodeError:
            return BrainResponse(
                action="pass",
                reasoning=f"AnthropicBrain: could not parse JSON response: {text[:200]}",
                confidence=0.0,
            )

    def provider_name(self) -> str:
        return "anthropic"


# ---------------------------------------------------------------------------
# OpenAIBrain — GPT adapter (OpenAI-compatible API)
# ---------------------------------------------------------------------------

_OPENAI_SYSTEM = _ANTHROPIC_SYSTEM  # same contract


class OpenAIBrain(BrainAdapter):
    """
    OpenAI GPT adapter via Chat Completions API.

    Requires OPENAI_API_KEY env var (or api_key in extra_config).
    Also works with any OpenAI-compatible API (set base_url in extra_config).

    Stub status: interface complete, HTTP call implemented.
    Activate by setting OPENAI_API_KEY.
    """

    DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, config: BrainConfig) -> None:
        self.config = config
        self._api_key = config.extra_config.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        self._model = config.model or "gpt-4o"
        self._api_url = config.extra_config.get("base_url", self.DEFAULT_API_URL)
        self._system = config.system_prompt or _OPENAI_SYSTEM

    def is_available(self) -> bool:
        return bool(self._api_key)

    def think(self, request: BrainRequest) -> BrainResponse:
        if not self._api_key:
            return BrainResponse(
                action="pass",
                reasoning="OpenAIBrain: no API key — set OPENAI_API_KEY",
                confidence=0.0,
            )
        try:
            prompt = self._build_prompt(request)
            payload = {
                "model": self._model,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": self._system},
                    {"role": "user", "content": prompt},
                ],
            }
            req = urllib.request.Request(
                self._api_url,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())

            text = body["choices"][0]["message"]["content"].strip()
            data = json.loads(text)
            return BrainResponse(
                action=str(data.get("action", "pass")),
                parameters=data.get("parameters") or {},
                reasoning=str(data.get("reasoning", "")),
                confidence=float(data.get("confidence", 0.0)),
            )

        except Exception as exc:
            return BrainResponse(
                action="pass",
                reasoning=f"OpenAIBrain error: {exc}",
                confidence=0.0,
            )

    def consult(self, prompt: str, tier: ModelTier = ModelTier.QUICK) -> str:
        if not self._api_key:
            return ""
        model = self._tier_model(tier) or self._model
        try:
            payload = {
                "model": model,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                self._api_url,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
            return str(body["choices"][0]["message"]["content"]).strip()
        except Exception:
            return ""

    def _build_prompt(self, request: BrainRequest) -> str:
        return (
            f"Node: {request.node_id} | Op: {request.operation}\n"
            f"State: {json.dumps(request.current_state)}\n"
            f"Metrics: {json.dumps(request.recent_metrics)}\n"
            f"Actions: {request.available_actions}\n"
            f"Context: {request.domain_context}"
        )

    def provider_name(self) -> str:
        return "openai"


# ---------------------------------------------------------------------------
# DeepSeekBrain — DeepSeek adapter (OpenAI-compatible)
# ---------------------------------------------------------------------------


class DeepSeekBrain(OpenAIBrain):
    """
    DeepSeek adapter — reuses OpenAI-compatible protocol.

    Requires DEEPSEEK_API_KEY env var (or api_key in extra_config).
    """

    DEFAULT_API_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, config: BrainConfig) -> None:
        # Inject DeepSeek defaults before handing to OpenAIBrain
        config.extra_config.setdefault(
            "base_url", config.extra_config.get("base_url", self.DEFAULT_API_URL)
        )
        if not config.model:
            config.model = "deepseek-chat"
        super().__init__(config)
        # Override API key env var
        self._api_key = (
            config.extra_config.get("api_key")
            or os.environ.get("DEEPSEEK_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
        )

    def provider_name(self) -> str:
        return "deepseek"


# ---------------------------------------------------------------------------
# OllamaBrain — local model adapter (hits localhost:11434)
# ---------------------------------------------------------------------------


class OllamaBrain(BrainAdapter):
    """
    Ollama local model adapter.

    Hits Ollama's REST API at localhost:11434 (or OLLAMA_HOST env var).
    No API key required — works fully offline.

    Stub status: interface complete, HTTP call implemented.
    Activate by running: `ollama pull <model>` and starting Ollama.
    """

    def __init__(self, config: BrainConfig) -> None:
        self.config = config
        host = config.extra_config.get("host") or os.environ.get(
            "OLLAMA_HOST", "http://localhost:11434"
        )
        self._api_url = f"{host.rstrip('/')}/api/chat"
        self._model = config.model or "llama3"

    def is_available(self) -> bool:
        try:
            host = self._api_url.replace("/api/chat", "")
            urllib.request.urlopen(f"{host}/api/tags", timeout=2)
            return True
        except Exception:
            return False

    def think(self, request: BrainRequest) -> BrainResponse:
        try:
            prompt = (
                f"Node: {request.node_id}\nOp: {request.operation}\n"
                f"State: {json.dumps(request.current_state)}\n"
                f"Metrics: {json.dumps(request.recent_metrics)}\n"
                f"Actions: {request.available_actions}\n"
                f"Context: {request.domain_context}\n\n"
                "Respond with JSON only: "
                '{"action":"<action>","parameters":{},"reasoning":"<why>","confidence":<0-1>}'
            )
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": _ANTHROPIC_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": self.config.temperature},
            }
            req = urllib.request.Request(
                self._api_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read())

            text = body["message"]["content"].strip()
            # Strip markdown fences
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()

            data = json.loads(text)
            return BrainResponse(
                action=str(data.get("action", "pass")),
                parameters=data.get("parameters") or {},
                reasoning=str(data.get("reasoning", "")),
                confidence=float(data.get("confidence", 0.0)),
            )

        except Exception as exc:
            return BrainResponse(
                action="pass",
                reasoning=f"OllamaBrain error: {exc}",
                confidence=0.0,
            )

    def provider_name(self) -> str:
        return "ollama"


# ---------------------------------------------------------------------------
# GoogleBrain — Gemini adapter stub
# ---------------------------------------------------------------------------


class GoogleBrain(BrainAdapter):
    """
    Google Gemini adapter stub.

    Requires GOOGLE_API_KEY env var (or api_key in extra_config).
    Stub status: is_available() and think() interface defined; HTTP call is
    a placeholder — activate once Gemini endpoint details are confirmed.
    """

    def __init__(self, config: BrainConfig) -> None:
        self.config = config
        self._api_key = config.extra_config.get("api_key") or os.environ.get("GOOGLE_API_KEY", "")
        self._model = config.model or "gemini-1.5-pro"

    def is_available(self) -> bool:
        return bool(self._api_key)

    def think(self, request: BrainRequest) -> BrainResponse:
        # TODO: implement Gemini generateContent API call
        # Endpoint: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
        return BrainResponse(
            action="pass",
            reasoning="GoogleBrain: HTTP implementation pending",
            confidence=0.0,
        )

    def provider_name(self) -> str:
        return "google"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BRAIN_REGISTRY: dict[str, type] = {
    "none": NoBrain,
    "anthropic": AnthropicBrain,
    "openai": OpenAIBrain,
    "deepseek": DeepSeekBrain,
    "ollama": OllamaBrain,
    "google": GoogleBrain,
}


def create_brain(config: BrainConfig | None = None) -> BrainAdapter:
    """
    Factory: create the appropriate BrainAdapter from a BrainConfig.

    Falls back to NoBrain if provider is unknown or config is None.
    """
    cfg = config or BrainConfig()
    cls = BRAIN_REGISTRY.get(cfg.provider, NoBrain)
    return cls(cfg)  # type: ignore[no-any-return]
