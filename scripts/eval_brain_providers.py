#!/usr/bin/env python3
"""Baseline eval for all brain providers in the Omega system.

Tests each available model on a standardized set of prompts relevant
to Omega's trading/analysis use cases. Measures: response quality,
latency, and availability.

Key mappings:
  CLAUDE_API_KEY  → Anthropic (ANTHROPIC_API_KEY alias)
  OPENROUTER_API_KEY → OpenRouter gateway (gpt-4o-mini, gpt-4o, etc.)
  KIMI_API_KEY    → Moonshot AI Kimi (OpenAI-compatible at api.moonshot.cn)

Usage: python3 scripts/eval_brain_providers.py
       python3 scripts/eval_brain_providers.py --provider anthropic-haiku
       python3 scripts/eval_brain_providers.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from typing import TypedDict

# ---------------------------------------------------------------------------
# Load .env (project root)
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_FILE = os.path.join(_ROOT, ".env")

if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

# Map CLAUDE_API_KEY → ANTHROPIC_API_KEY (omega's alias)
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("CLAUDE_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["CLAUDE_API_KEY"]

# ---------------------------------------------------------------------------
# Eval prompts — cover Omega's core trading/analysis capabilities
# ---------------------------------------------------------------------------


class EvalPrompt(TypedDict):
    id: str
    prompt: str
    expected_contains: list[str]
    tier: str


EVAL_PROMPTS: list[EvalPrompt] = [
    {
        "id": "signal_analysis",
        "prompt": (
            "BTC order flow is bullish (+0.94), cross-asset correlation is bearish (-0.93), "
            "sentiment is extreme fear (+0.15), VRP is neutral. "
            "Should we go LONG, SHORT, or FLAT? "
            "Answer with one word then a one-sentence reason."
        ),
        "expected_contains": ["LONG", "SHORT", "FLAT"],
        "tier": "DEEP",
    },
    {
        "id": "market_regime",
        "prompt": (
            "MVRV ratio is 1.59, Puell Multiple is 0.83, exchange netflow is -365 BTC, "
            "taker buy/sell ratio is 0.89. What market regime are we in? "
            "Answer: ACCUMULATION, DISTRIBUTION, EUPHORIA, or CAPITULATION. "
            "One word then one sentence."
        ),
        "expected_contains": ["ACCUMULATION", "DISTRIBUTION", "EUPHORIA", "CAPITULATION"],
        "tier": "QUICK",
    },
    {
        "id": "risk_assessment",
        "prompt": (
            "Portfolio has 40% in BTCUSDT long and 35% in ETHUSDT long. "
            "BTC dominance is 56.5% and rising. Is this concentration acceptable? "
            "Answer YES or NO then one sentence."
        ),
        "expected_contains": ["YES", "NO"],
        "tier": "QUICK",
    },
    {
        "id": "cycle_reflection",
        "prompt": (
            "Cycle 50: 11 signals computed, quality score 0.896, top signal cross_asset (IC=0.93), "
            "VRP regime NEUTRAL, composite direction bearish. What is the key lesson? One sentence."
        ),
        "expected_contains": [],  # Any coherent response qualifies
        "tier": "QUICK",
    },
    {
        "id": "weather_edge",
        "prompt": (
            "GEFS ensemble: 25 of 31 members predict NYC temperature above 30C tomorrow. "
            "Polymarket YES price is 0.65. Model probability is 0.806. Edge is 15.6%. "
            "Kelly fraction is 0.80. Should we bet? Answer BET or SKIP then one sentence."
        ),
        "expected_contains": ["BET", "SKIP"],
        "tier": "DEEP",
    },
]

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------


def _build_providers(filter_name: str | None) -> list[dict]:
    providers = []

    # --- Anthropic (CLAUDE_API_KEY / ANTHROPIC_API_KEY) ---
    if os.environ.get("ANTHROPIC_API_KEY"):
        providers += [
            {
                "name": "anthropic-haiku",
                "type": "anthropic",
                "model": "claude-haiku-4-5-20251001",
                "tier": "QUICK",
            },
            {
                "name": "anthropic-sonnet",
                "type": "anthropic",
                "model": "claude-sonnet-4-6",
                "tier": "DEEP",
            },
        ]

    # --- OpenRouter (gateway to many models) ---
    if os.environ.get("OPENROUTER_API_KEY"):
        providers += [
            {
                "name": "openrouter-gpt4o-mini",
                "type": "openrouter",
                "model": "openai/gpt-4o-mini",
                "tier": "QUICK",
            },
            {
                "name": "openrouter-gpt4o",
                "type": "openrouter",
                "model": "openai/gpt-4o",
                "tier": "DEEP",
            },
            {
                "name": "openrouter-deepseek-chat",
                "type": "openrouter",
                "model": "deepseek/deepseek-chat",
                "tier": "QUICK",
            },
        ]

    # --- Kimi / Moonshot AI (OpenAI-compatible) ---
    if os.environ.get("KIMI_API_KEY"):
        providers += [
            {
                "name": "kimi-moonshot-v1-8k",
                "type": "openai_compat",
                "model": "moonshot-v1-8k",
                "api_url": "https://api.moonshot.cn/v1/chat/completions",
                "api_key_env": "KIMI_API_KEY",
                "tier": "QUICK",
            },
        ]

    # --- Ollama local (no key required) ---
    try:
        subprocess.run(["which", "ollama"], capture_output=True, check=True)
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        lines = result.stdout.lower().splitlines()
        for model_tag in ["llama3", "mistral", "phi3", "gemma"]:
            for line in lines:
                if model_tag in line:
                    providers.append(
                        {
                            "name": f"ollama-{model_tag}",
                            "type": "ollama",
                            "model": model_tag,
                            "tier": "QUICK",
                        }
                    )
                    break
    except Exception:
        pass

    # --- Claude CLI ---
    try:
        subprocess.run(["which", "claude"], capture_output=True, check=True)
        providers.append(
            {
                "name": "claude-cli-haiku",
                "type": "claude_cli",
                "model": "claude-haiku-4-5-20251001",
                "tier": "QUICK",
            }
        )
    except Exception:
        pass

    if filter_name:
        providers = [p for p in providers if p["name"] == filter_name]

    return providers


# ---------------------------------------------------------------------------
# API call implementations
# ---------------------------------------------------------------------------


def _call_anthropic(model: str, prompt: str, max_tokens: int = 200) -> tuple[str, float]:
    key = os.environ["ANTHROPIC_API_KEY"]
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    t0 = time.time()
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    latency = time.time() - t0
    text = resp["content"][0]["text"] if resp.get("content") else ""
    return text, latency


def _call_openrouter(model: str, prompt: str, max_tokens: int = 200) -> tuple[str, float]:
    key = os.environ["OPENROUTER_API_KEY"]
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    t0 = time.time()
    resp = json.loads(urllib.request.urlopen(req, timeout=45).read())
    latency = time.time() - t0
    text = resp["choices"][0]["message"]["content"] if resp.get("choices") else ""
    return text, latency


def _call_openai_compat(
    api_url: str, api_key: str, model: str, prompt: str, max_tokens: int = 200
) -> tuple[str, float]:
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    t0 = time.time()
    resp = json.loads(urllib.request.urlopen(req, timeout=45).read())
    latency = time.time() - t0
    text = resp["choices"][0]["message"]["content"] if resp.get("choices") else ""
    return text, latency


def _call_ollama(model: str, prompt: str) -> tuple[str, float]:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    latency = time.time() - t0
    text = resp.get("message", {}).get("content", "")
    return text, latency


def _call_claude_cli(model: str, prompt: str) -> tuple[str, float]:
    t0 = time.time()
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", model], capture_output=True, text=True, timeout=60
    )
    latency = time.time() - t0
    return result.stdout.strip(), latency


def run_eval(provider: dict, prompt_text: str) -> tuple[str, float]:
    ptype = provider["type"]
    model = provider["model"]

    if ptype == "anthropic":
        return _call_anthropic(model, prompt_text)
    elif ptype == "openrouter":
        return _call_openrouter(model, prompt_text)
    elif ptype == "openai_compat":
        api_key = os.environ.get(provider["api_key_env"], "")
        return _call_openai_compat(provider["api_url"], api_key, model, prompt_text)
    elif ptype == "ollama":
        return _call_ollama(model, prompt_text)
    elif ptype == "claude_cli":
        return _call_claude_cli(model, prompt_text)
    return "", 0.0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_response(response: str, expected_contains: list[str]) -> float:
    """1.0 if keyword matched, 0.5 if coherent, 0.0 if empty/error."""
    if not response or len(response) < 5:
        return 0.0
    if not expected_contains:
        return 1.0 if len(response) > 10 else 0.5
    for kw in expected_contains:
        if kw.upper() in response.upper():
            return 1.0
    return 0.5  # coherent but no keyword match


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Brain provider eval")
    parser.add_argument("--provider", help="Only test this provider name")
    parser.add_argument(
        "--json", action="store_true", dest="output_json", help="Output results as JSON"
    )
    parser.add_argument("--prompt", help="Only run this prompt ID")
    args = parser.parse_args()

    providers = _build_providers(args.provider)
    prompts = [p for p in EVAL_PROMPTS if not args.prompt or p["id"] == args.prompt]

    if not providers:
        print("No providers available. Configure at least one of:")
        print("  CLAUDE_API_KEY / ANTHROPIC_API_KEY")
        print("  OPENROUTER_API_KEY")
        print("  KIMI_API_KEY")
        print("  or install: ollama, claude (CLI)")
        sys.exit(1)

    if not args.output_json:
        print(f"Brain Provider Eval — {len(providers)} providers, {len(prompts)} prompts")
        print("=" * 80)

    all_results = []

    for prov in providers:
        if not args.output_json:
            print(f"\n--- {prov['name']} ({prov['type']}, {prov['model']}) ---")
        prov_result: dict = {
            "name": prov["name"],
            "type": prov["type"],
            "model": prov["model"],
            "evals": [],
        }

        for ep in prompts:
            if not args.output_json:
                sys.stdout.write(f"  {ep['id']}: ")
                sys.stdout.flush()

            try:
                response, latency = run_eval(prov, ep["prompt"])
                score = score_response(response, ep["expected_contains"])
                preview = response[:80].replace("\n", " ") if response else "(empty)"

                if not args.output_json:
                    print(f"score={score:.1f}  latency={latency:.2f}s  — {preview}")

                prov_result["evals"].append(
                    {
                        "prompt_id": ep["id"],
                        "score": score,
                        "latency_ms": round(latency * 1000),
                        "response_preview": response[:200] if response else "",
                    }
                )
            except Exception as exc:
                if not args.output_json:
                    print(f"ERROR: {exc}")
                prov_result["evals"].append(
                    {
                        "prompt_id": ep["id"],
                        "score": 0.0,
                        "latency_ms": 0,
                        "error": str(exc),
                    }
                )

        scores = [e["score"] for e in prov_result["evals"]]
        latencies = [e["latency_ms"] for e in prov_result["evals"] if e.get("latency_ms", 0) > 0]
        prov_result["avg_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
        prov_result["avg_latency_ms"] = round(sum(latencies) / len(latencies)) if latencies else 0
        all_results.append(prov_result)

    # Output
    if args.output_json:
        print(json.dumps({"providers": all_results, "prompts": prompts}, indent=2))
        return

    print("\n" + "=" * 80)
    print("SUMMARY")
    print(f"{'Provider':<30} {'Model':<30} {'Score':>7} {'Latency':>10} {'Evals':>6}")
    print("-" * 87)
    for r in sorted(all_results, key=lambda x: -x["avg_score"]):
        print(
            f"{r['name']:<30} {r['model']:<30} "
            f"{r['avg_score']:>7.2f} {r['avg_latency_ms']:>8}ms {len(r['evals']):>6}"
        )

    # Persist results
    os.makedirs(os.path.join(_ROOT, "data"), exist_ok=True)
    out_path = os.path.join(_ROOT, "data", "brain_eval_results.json")
    with open(out_path, "w") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "providers": all_results,
                "prompts": prompts,
            },
            f,
            indent=2,
        )
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
