"""V260 Track F — News-driven regime detection: LLM-vs-calendar agreement probe.

Offline scorer (Phase-0). Reads the frozen gdelt daily tone/vol series and the
walk-forward manifest, asks a lightweight LLM (via ``agy``) to classify each
window's dominant news regime into {panic, uncertainty, calm, euphoria}, maps
that to the calendar regime {crisis, trend, recent}, and reports agreement.

Pre-registration: ``omega/nodes/victoria/training_log/V260.md``.

Hermetic: every unique prompt is cached at
``data/frozen_llm_cache/v260/{prompt_hash}.json``. Re-runs are $0 and
deterministic. Cost cap enforced by ``--max-calls`` (default 50).

Usage:
    python3 -m omega.tools.v260_news_regime_scorer            # run (uses cache)
    python3 -m omega.tools.v260_news_regime_scorer --dry-run  # build prompts, no agy
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "walk_forward_manifest.json"
FROZEN = ROOT / "data" / "frozen_series"
CACHE_DIR = ROOT / "data" / "frozen_llm_cache" / "v260"
OUT_JSON = ROOT / "data" / "v260_news_regime_scorer.json"

AGY_BIN = "agy"
AGY_MODEL = "Gemini 3.1 Pro (Low)"
MODEL_ID = "gemini-3.1-pro-low"

CATEGORIES = [
    "central_bank",
    "crypto_regulation",
    "financial_crisis",
    "geopolitical",
    "sanctions",
]

# Pre-declared LLM-regime -> calendar-regime mapping (see V260.md).
LLM_TO_CALENDAR = {
    "panic": "crisis",
    "euphoria": "trend",
    "calm": "recent",
    "uncertainty": "recent",
}

TASK = (
    "You are a macro-regime classifier reading ONLY news-media signals for a "
    "~90-day period. You are given, per news category, the GDELT tone (negative "
    "= adverse coverage, positive = favourable) and coverage-volume statistics. "
    "Classify the DOMINANT news regime of the period as EXACTLY ONE of: "
    "'panic' (acute fear/crisis coverage), 'uncertainty' (elevated but "
    "unresolved anxiety), 'calm' (benign, low-stress coverage), 'euphoria' "
    "(strongly optimistic/risk-on coverage). Judge from the news tone/volume "
    "ONLY — you are NOT given prices. Respond with ONLY a JSON object: "
    '{"regime": one of the four words, "confidence": float in [0,1], '
    '"reasoning": short string}.'
)


def _load_series() -> dict[str, dict[str, float]]:
    """Return {series_name: {date: value}} for all 10 gdelt series."""
    out: dict[str, dict[str, float]] = {}
    for metric in ("tone", "vol"):
        for cat in CATEGORIES:
            name = f"gdelt_{metric}_{cat}"
            p = FROZEN / f"{name}.json"
            out[name] = json.loads(p.read_text())["series"]
    return out


def _spikes(vals: list[float], sd_mult: float = 2.0) -> int:
    if len(vals) < 3:
        return 0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    sd = var ** 0.5
    if sd == 0:
        return 0
    return sum(1 for v in vals if abs(v - mean) > sd_mult * sd)


def _window_summary(series: dict[str, dict[str, float]], lo: str, hi: str) -> dict:
    """Deterministic per-category tone/vol summary sliced to [lo, hi]."""
    summ: dict[str, dict] = {}
    for cat in CATEGORIES:
        tone = [v for d, v in series[f"gdelt_tone_{cat}"].items() if lo <= d <= hi]
        vol = [v for d, v in series[f"gdelt_vol_{cat}"].items() if lo <= d <= hi]
        if not tone:
            continue
        summ[cat] = {
            "tone_mean": round(sum(tone) / len(tone), 3),
            "tone_min": round(min(tone), 3),
            "tone_max": round(max(tone), 3),
            "tone_last": round(tone[-1], 3),
            "tone_neg_spikes": _spikes(tone),
            "vol_mean": round(sum(vol) / len(vol), 3) if vol else 0.0,
            "vol_max": round(max(vol), 3) if vol else 0.0,
            "n_days": len(tone),
        }
    return summ


def _build_prompt(summary: dict) -> str:
    payload = {"task": TASK, "news_summary": summary}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _cache_load(phash: str) -> dict | None:
    p = CACHE_DIR / f"{phash}.json"
    if not p.is_file():
        return None
    response: dict = json.loads(p.read_text())["response"]
    return response


def _cache_store(phash: str, prompt: str, response: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{phash}.json").write_text(
        json.dumps(
            {"model_id": MODEL_ID, "agy_model_string": AGY_MODEL,
             "prompt": prompt, "response": response},
            sort_keys=True, indent=1,
        ) + "\n"
    )


def _extract_json(text: str) -> dict:
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
                obj = json.loads(s[start:i + 1])
                if not isinstance(obj, dict):
                    raise ValueError("top-level JSON not an object")
                return obj
    raise ValueError("unbalanced JSON object")


def _call_live(prompt: str) -> dict:
    for attempt in range(3):
        proc = subprocess.run(
            [AGY_BIN, "--model", AGY_MODEL, "-p", prompt],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"agy exited {proc.returncode}: {proc.stderr.strip()[:300]}")
        try:
            return _extract_json(proc.stdout)
        except Exception:
            if attempt == 2:
                raise
    raise RuntimeError("unreachable")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build prompts, no agy calls")
    ap.add_argument("--max-calls", type=int, default=50, help="budget cap on cache misses")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    windows = manifest["windows"]
    series = _load_series()

    rows = []
    live_calls = 0
    for w in windows:
        lo, hi = w["date_range"]
        summary = _window_summary(series, lo, hi)
        prompt = _build_prompt(summary)
        phash = _prompt_hash(prompt)
        cached = _cache_load(phash)
        if cached is None:
            if args.dry_run:
                resp = {"regime": None, "confidence": None, "reasoning": "(dry-run)"}
            else:
                if live_calls >= args.max_calls:
                    print(f"BUDGET CAP hit ({args.max_calls} calls) — checkpointing, stopping.")
                    break
                resp = _call_live(prompt)
                _cache_store(phash, prompt, resp)
                live_calls += 1
                print(f"  {w['id']} [{w['regime']}] -> LLM {resp.get('regime')!r} "
                      f"(call {live_calls}, hash {phash})")
        llm_regime = (resp.get("regime") or "").strip().lower()
        mapped = LLM_TO_CALENDAR.get(llm_regime)
        rows.append({
            "window": w["id"],
            "date_range": w["date_range"],
            "calendar_regime": w["regime"],
            "high_vol": w.get("high_vol"),
            "llm_regime": llm_regime or None,
            "llm_mapped": mapped,
            "agree": (mapped == w["regime"]) if mapped else None,
            "confidence": resp.get("confidence"),
            "cache_hit": cached is not None,
        })

    scored = [r for r in rows if r["agree"] is not None]
    n = len(scored)
    n_agree = sum(1 for r in scored if r["agree"])
    agreement = n_agree / n if n else None

    # confusion matrix: llm_regime (4) x calendar_regime (3)
    confusion: dict[str, Counter] = {k: Counter() for k in LLM_TO_CALENDAR}
    for r in scored:
        if r["llm_regime"] in confusion:
            confusion[r["llm_regime"]][r["calendar_regime"]] += 1
    confusion_out = {k: dict(v) for k, v in confusion.items()}

    llm_dist = Counter(r["llm_regime"] for r in scored)
    cal_dist = Counter(r["calendar_regime"] for r in scored)

    verdict = "PENDING"
    if agreement is not None:
        if agreement > 0.95:
            verdict = "REFUTED (>95% — re-labeling, no new info)"
        elif agreement < 0.20:
            verdict = "REFUTED (<20% — noise, no coherent signal)"
        else:
            verdict = "SIGNAL EXISTS (20-95%) — cap FLAG-GATED (out of scope to test trading value)"

    result = {
        "version": "v260",
        "model_id": MODEL_ID,
        "n_windows": len(windows),
        "n_scored": n,
        "live_calls_this_run": live_calls,
        "agreement": round(agreement, 4) if agreement is not None else None,
        "n_agree": n_agree,
        "mapping": LLM_TO_CALENDAR,
        "verdict": verdict,
        "llm_regime_distribution": dict(llm_dist),
        "calendar_regime_distribution": dict(cal_dist),
        "confusion_llm_x_calendar": confusion_out,
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n")
    print("\n=== V260 RESULT ===")
    print(f"windows scored : {n}/{len(windows)}")
    print(f"live agy calls : {live_calls}")
    print(f"agreement      : {agreement}")
    print(f"llm dist       : {dict(llm_dist)}")
    print(f"calendar dist  : {dict(cal_dist)}")
    print(f"verdict        : {verdict}")
    print(f"written        : {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
