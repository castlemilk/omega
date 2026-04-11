"""
omega.core.llm_shell
~~~~~~~~~~~~~~~~~~~~~
Thin subprocess wrapper for shell-based LLM access.

Invokes the `claude` CLI (Claude Code) via subprocess so callers don't need
an ANTHROPIC_API_KEY in .env — auth is handled by the existing Claude Code
login session.

CLI detection order: claude → claude-cli → cl

Usage:
    from omega.core.llm_shell import invoke, is_available

    text = invoke("Explain this trade: ETH long at conviction 0.15 lost $42")
    # → "The loss suggests ..."

    # With model and system prompt:
    text = invoke(
        prompt="Why did ETH long fail?",
        model="claude-haiku-4-5-20251001",
        system="You are a quant analyst. Be concise.",
    )

    # Check before using:
    if is_available():
        result = invoke(prompt)

Detection is cached after the first call — no repeated `which` lookups.

Model tier shorthands (passed through to --model):
  "quick" → claude-haiku-4-5-20251001
  "deep"  → claude-opus-4-6
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Final

logger = logging.getLogger("omega.core.llm_shell")

# ---------------------------------------------------------------------------
# Model tier shorthands
# ---------------------------------------------------------------------------

_TIER_MODELS: dict[str, str] = {
    "quick": "claude-haiku-4-5-20251001",
    "deep": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
}

DEFAULT_MODEL: Final[str] = "claude-sonnet-4-6"
DEFAULT_TIMEOUT: Final[int] = 120  # seconds

# ---------------------------------------------------------------------------
# CLI detection (cached)
# ---------------------------------------------------------------------------

_CLI_CANDIDATES: Final[list[str]] = ["claude", "claude-cli", "cl"]
_detected_cli: str | None = None
_detection_done: bool = False


def detect_cli() -> str | None:
    """
    Return the first available LLM CLI binary name, or None.
    Result is cached — only runs `shutil.which` once.
    """
    global _detected_cli, _detection_done
    if _detection_done:
        return _detected_cli
    _detection_done = True
    for candidate in _CLI_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            _detected_cli = candidate
            logger.debug("llm_shell: detected CLI '%s' at %s", candidate, path)
            return _detected_cli
    logger.debug("llm_shell: no LLM CLI found (tried: %s)", ", ".join(_CLI_CANDIDATES))
    return None


def is_available() -> bool:
    """Return True if a supported LLM CLI is installed and reachable."""
    return detect_cli() is not None


def reset_detection() -> None:
    """Clear the cached detection result (useful in tests)."""
    global _detected_cli, _detection_done
    _detected_cli = None
    _detection_done = False


# ---------------------------------------------------------------------------
# Core invoke
# ---------------------------------------------------------------------------


def invoke(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    Send a prompt to the LLM via CLI subprocess; return the response text.

    Parameters
    ----------
    prompt  : The user prompt.
    model   : Model name or tier shorthand ("quick", "deep", "sonnet").
              Defaults to DEFAULT_MODEL.
    system  : Optional system prompt passed via --system-prompt.
    timeout : Subprocess timeout in seconds (default 120).

    Returns
    -------
    str  — stripped response text, or "" on any error.

    Never raises — all errors are logged and return "".
    """
    cli = detect_cli()
    if cli is None:
        logger.warning("llm_shell.invoke: no CLI available — returning empty string")
        return ""

    resolved_model = _TIER_MODELS.get(model or "", model or DEFAULT_MODEL)

    cmd = [cli, "--print", prompt, "--model", resolved_model, "--output-format", "text"]
    if system:
        cmd += ["--system-prompt", system]

    logger.debug("llm_shell.invoke: %s", " ".join(cmd[:4]) + " ...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.warning(
                "llm_shell.invoke: CLI exited %d — %s",
                result.returncode,
                stderr[:200],
            )
            return ""
        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        logger.warning("llm_shell.invoke: timed out after %ds", timeout)
        return ""
    except FileNotFoundError:
        logger.warning("llm_shell.invoke: CLI binary '%s' not found", cli)
        reset_detection()
        return ""
    except Exception as exc:
        logger.warning("llm_shell.invoke: unexpected error: %s", exc)
        return ""


def invoke_json(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict | None:
    """
    Like invoke() but parses the response as JSON.
    Returns None if the response is not valid JSON.
    Strips markdown fences before parsing.
    """
    import json

    text = invoke(prompt=prompt, model=model, system=system, timeout=timeout)
    if not text:
        return None

    # Strip markdown fences if present
    if "```" in text:
        for part in text.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{") or part.startswith("["):
                text = part
                break

    try:
        return json.loads(text)
    except Exception:
        logger.debug("llm_shell.invoke_json: could not parse JSON from: %s", text[:200])
        return None
