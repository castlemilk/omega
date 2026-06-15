#!/usr/bin/env python3
"""
scripts/estimate_ics.py — V224 empirical per-(regime, signal) IC estimation.

Computes data-derived Information Coefficients (Spearman rank correlation of each
sub-signal's raw_value vs the 1-bar-forward simple return) on an out-of-sample
LEAVE-ONE-SNAPSHOT-OUT (LOSO) holdout, keyed on the runtime `_regime` label space
(`normal` / `crisis` / `high_vol`). Writes one committed file
(`data/empirical_ic_history.json`) with a per-target block: the ICs used while
trading snapshot X are fit EXCLUSIVELY on the other snapshots — zero look-ahead.

Determinism (V214→V221 channel-closure discipline — this estimator must be
byte-reproducible across runs):
  * Spearman computed as Pearson on INTEGER ordinal ranks (the d^2 shortcut is
    invalid under ties). Tie-break = ordinal over a pinned secondary key
    (value, cycle, ticker, snap) → unique total order even when raw_values
    collide.
  * Every float accumulator uses math.fsum over a pinned-order observation list.
  * No numpy / scipy / builtin sum over unordered iteration.

Data source per snapshot: the DecisionSnapshot JSONL emitted by an IC-off replay
(`/tmp/{version}_decisions.jsonl`) — per cycle it carries the runtime `regime`
label and `per_ticker[sym].signal_traces[].{signal_name, raw_value}` for every
ticker — joined to that snapshot's frozen close series for forward returns via the
exact ReplayIngestionNode cursor walk (cursor starts at window=30, i=cursor-1,
wraps to window when cursor>series_len).

Usage:
  python3 scripts/estimate_ics.py \
    --corpus trend:/tmp/v224_corpus_trend_decisions.jsonl:data/snapshots/snap_trending_2023q4.json \
    --corpus crisis:/tmp/v224_corpus_crisis_decisions.jsonl:data/snapshots/snap_crisis_2022h1.json \
    --corpus recent:/tmp/v224_corpus_recent_decisions.jsonl:data/snapshots/snap_20260414.json \
    --seed data/signal_ic_history.json \
    --out data/empirical_ic_history.json \
    --n-min 30 --horizon 1
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

WINDOW = 30  # ReplayIngestionNode._MIN_WINDOW — keep in lockstep with replay.py
REGIME_KEYS = ("normal", "crisis", "high_vol")  # the gate's runtime label space
NOISE_FLOOR = 1e-4  # consumer drops |ic| < this; report it but still write


# ── observation ───────────────────────────────────────────────────────────────
class Obs:
    """One (signal, regime) observation: signal value at cycle t vs fwd return."""

    __slots__ = ("value", "fwd_ret", "cycle", "ticker", "snap")

    def __init__(self, value: float, fwd_ret: float, cycle: int, ticker: str, snap: str):
        self.value = value
        self.fwd_ret = fwd_ret
        self.cycle = cycle
        self.ticker = ticker
        self.snap = snap


def _cursor_bar_index(cycle: int, series_len: int) -> int:
    """Replicate ReplayIngestionNode's cursor walk → bar index for a 1-based cycle.

    cursor starts at WINDOW; each cycle: i = cursor-1 (last bar of the window),
    then cursor += 1; if cursor > series_len, cursor resets to WINDOW. Returns the
    bar index `i` the strategy saw at `cycle`.
    """
    cursor = WINDOW
    bar_i = WINDOW - 1
    for _ in range(cycle):
        bar_i = cursor - 1
        cursor += 1
        if cursor > series_len:
            cursor = WINDOW
    return bar_i


def _load_snapshot_closes(path: str) -> tuple[dict[str, list[float]], int]:
    data = json.loads(Path(path).read_text())
    symbols = [k for k in data if not k.startswith("_") and isinstance(data[k], dict)]
    closes = {sym: [float(x) for x in (data[sym].get("close") or [])] for sym in symbols}
    series_len = min(len(c) for c in closes.values()) if closes else 0
    return closes, series_len


def _collect_obs(jsonl_path: str, snapshot_path: str, snap_name: str) -> list[Obs]:
    """Parse a decisions JSONL + snapshot into per-(signal,regime) observations.

    Returns a flat list; bucketing by (regime, signal) happens in the caller. Each
    observation pairs a signal raw_value at cycle t with the 1-bar-forward return of
    its ticker. Observations at a wrap boundary (no forward bar) are dropped.
    """
    closes, series_len = _load_snapshot_closes(snapshot_path)
    out: list[tuple[str, str, Obs]] = []  # (regime, signal_name, Obs)
    with open(jsonl_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            regime = str(rec.get("regime", "")).lower()
            if regime not in REGIME_KEYS:
                continue
            cycle = int(rec.get("cycle", 0))
            if cycle <= 0:
                continue
            i = _cursor_bar_index(cycle, series_len)
            if i + 1 >= series_len or i < 0:
                continue  # no forward bar at this cycle
            per_ticker = rec.get("per_ticker") or {}
            for sym in sorted(per_ticker):
                td = per_ticker[sym]
                if not isinstance(td, dict):
                    continue
                series = closes.get(sym)
                if not series or i + 1 >= len(series):
                    continue
                c0 = series[i]
                c1 = series[i + 1]
                if c0 == 0.0:
                    continue
                fwd = c1 / c0 - 1.0
                for tr in td.get("signal_traces") or []:
                    name = tr.get("signal_name")
                    rv = tr.get("raw_value")
                    if name is None or rv is None:
                        continue
                    try:
                        val = float(rv)
                    except (TypeError, ValueError):
                        continue
                    if math.isnan(val) or math.isinf(val):
                        continue
                    out.append((regime, str(name), Obs(val, fwd, cycle, sym, snap_name)))
    # Return flattened but caller buckets; keep as list of (regime, signal, Obs).
    return out  # type: ignore[return-value]


# ── Spearman (ordinal ranks + fsum, byte-reproducible) ─────────────────────────
def _ordinal_ranks(obs: list[Obs], key) -> list[int]:
    """Assign ordinal ranks 0..N-1 over a pinned total order.

    Sort by (value_key, cycle, ticker, snap) ascending — a unique deterministic
    order even under value ties — and emit each observation's rank by position.
    """
    indexed = list(enumerate(obs))
    indexed.sort(key=lambda p: (key(p[1]), p[1].cycle, p[1].ticker, p[1].snap))
    ranks = [0] * len(obs)
    for pos, (orig_idx, _o) in enumerate(indexed):
        ranks[orig_idx] = pos
    return ranks


def _spearman(obs: list[Obs]) -> float | None:
    """Spearman = Pearson on ordinal ranks, fsum-fenced. None if degenerate."""
    n = len(obs)
    if n < 2:
        return None
    rx = _ordinal_ranks(obs, lambda o: o.value)
    ry = _ordinal_ranks(obs, lambda o: o.fwd_ret)
    mx = math.fsum(float(r) for r in rx) / n
    my = math.fsum(float(r) for r in ry) / n
    cov = math.fsum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = math.fsum((rx[i] - mx) ** 2 for i in range(n))
    vy = math.fsum((ry[i] - my) ** 2 for i in range(n))
    if vx <= 0.0 or vy <= 0.0:
        return None
    return cov / math.sqrt(vx * vy)


# ── estimation ─────────────────────────────────────────────────────────────────
def _bucket(rows: list[tuple[str, str, Obs]]):
    """rows → {regime: {signal: [Obs]}} and {signal: [Obs]} (pooled across regime)."""
    by_rs: dict[str, dict[str, list[Obs]]] = {}
    by_sig: dict[str, list[Obs]] = {}
    for regime, signal, o in rows:
        by_rs.setdefault(regime, {}).setdefault(signal, []).append(o)
        by_sig.setdefault(signal, []).append(o)
    return by_rs, by_sig


def _fit_block(fit_rows: list[tuple[str, str, Obs]], n_min: int):
    """Compute per-(regime,signal) + pooled empirical ICs for one LOSO fit set."""
    by_rs, by_sig = _bucket(fit_rows)
    regime_ics: dict[str, dict[str, float]] = {}
    sample_counts: dict[str, dict[str, int]] = {}
    for regime in REGIME_KEYS:
        sig_map = by_rs.get(regime, {})
        for signal in sorted(sig_map):
            obs = sig_map[signal]
            sample_counts.setdefault(signal, {})[regime] = len(obs)
            if len(obs) < n_min:
                continue  # omit → consumer falls back to pooled
            ic = _spearman(obs)
            if ic is None:
                continue
            regime_ics.setdefault(signal, {})[regime] = ic
    pooled_ics: dict[str, float] = {}
    for signal in sorted(by_sig):
        obs = by_sig[signal]
        if len(obs) < n_min:
            continue
        ic = _spearman(obs)
        if ic is not None:
            pooled_ics[signal] = ic
    return regime_ics, pooled_ics, sample_counts


def _round_floats(obj: Any) -> Any:
    """Round every float to 6 dp recursively for a stable, diffable JSON repr."""
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    return obj


# ── reporting ──────────────────────────────────────────────────────────────────
def _report(target: str, fit_on: list[str], regime_ics, pooled_ics, sample_counts,
            seed_regime, seed_pooled) -> None:
    print(f"\n=== target={target}  fit_on={'+'.join(fit_on)} ===")
    # 1. per-regime sample counts + cells written
    for regime in REGIME_KEYS:
        total = math.fsum(
            float(sample_counts.get(s, {}).get(regime, 0)) for s in sorted(sample_counts)
        )
        written = sum(1 for s in regime_ics if regime in regime_ics[s])
        seen = sum(1 for s in sample_counts if regime in sample_counts[s])
        print(f"  {regime:8s}: {int(total):6d} obs, {written}/{seen} cells >= N_min")
    # 2. IC distribution per regime
    for regime in REGIME_KEYS:
        vals = sorted(regime_ics[s][regime] for s in regime_ics if regime in regime_ics[s])
        if not vals:
            print(f"  {regime:8s} dist: (no cells)")
            continue
        med = vals[len(vals) // 2]
        n_neg = sum(1 for v in vals if v < 0)
        n_floor = sum(1 for v in vals if abs(v) < NOISE_FLOOR)
        print(f"  {regime:8s} dist: min={vals[0]:+.4f} med={med:+.4f} "
              f"max={vals[-1]:+.4f}  neg={n_neg} below1e-4={n_floor}")
    # 3. side-by-side vs seed (per-regime), sign-flips flagged
    print("  -- per-regime empirical vs seed (Δ; * = sign flip) --")
    all_sig = sorted(set(regime_ics) | set(seed_regime))
    for signal in all_sig:
        for regime in REGIME_KEYS:
            emp = regime_ics.get(signal, {}).get(regime)
            sd = seed_regime.get(signal, {}).get(regime)
            if emp is None and sd is None:
                continue
            es = f"{emp:+.4f}" if emp is not None else "  pooled"
            ss = f"{sd:+.4f}" if sd is not None else "  pooled"
            flip = ""
            if emp is not None and sd is not None and (emp * sd) < 0:
                flip = " *"
            d = f"{emp - sd:+.4f}" if (emp is not None and sd is not None) else "   -"
            print(f"     {signal:24s} {regime:8s} seed {ss} -> emp {es}  Δ {d}{flip}")
    # 4. pooled coverage delta
    emp_only = sorted(set(pooled_ics) - set(seed_pooled))
    seed_only = sorted(k for k in seed_pooled if k not in pooled_ics and abs(seed_pooled[k]) >= NOISE_FLOOR)
    print(f"  pooled: {len(pooled_ics)} empirical signals; "
          f"empirical-only={emp_only or '∅'}; seed-only(dropped)={seed_only or '∅'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="V224 empirical LOSO IC estimation")
    ap.add_argument("--corpus", action="append", required=True,
                    help="name:decisions_jsonl:snapshot_json (repeat per snapshot)")
    ap.add_argument("--seed", default="data/signal_ic_history.json",
                    help="seed IC file for the comparison report")
    ap.add_argument("--out", default="data/empirical_ic_history.json")
    ap.add_argument("--n-min", type=int, default=30)
    ap.add_argument("--horizon", type=int, default=1)
    args = ap.parse_args()

    if args.horizon != 1:
        raise SystemExit("only horizon=1 is implemented (cursor walk is 1-bar)")

    # Parse corpora in a pinned, sorted-by-name order.
    corpora: dict[str, tuple[str, str]] = {}
    for spec in args.corpus:
        parts = spec.split(":")
        if len(parts) != 3:
            raise SystemExit(f"--corpus must be name:jsonl:snapshot, got {spec!r}")
        name, jsonl, snap = parts
        corpora[name] = (jsonl, snap)
    names = sorted(corpora)

    # Pre-collect each snapshot's observations once (pinned order).
    per_snap_rows: dict[str, list[tuple[str, str, Obs]]] = {}
    for name in names:
        jsonl, snap = corpora[name]
        rows = _collect_obs(jsonl, snap, name)
        # pin order: (regime, signal, cycle, ticker)
        rows.sort(key=lambda t: (t[0], t[1], t[2].cycle, t[2].ticker))
        per_snap_rows[name] = rows
        print(f"[collect] {name}: {len(rows)} observations from {jsonl}")

    seed_raw = {}
    try:
        seed_raw = json.loads(Path(args.seed).read_text())
    except Exception:
        pass
    seed_regime = seed_raw.get("seeded_regime_ics", {}) or {}
    seed_pooled = seed_raw.get("seeded_pooled_ics", {}) or {}

    out: dict[str, Any] = {
        "_provenance": {
            "version": "V224",
            "method": ("leave-one-snapshot-out Spearman, 1-bar forward return, "
                       "ordinal (value,cycle,ticker,snap) tie-break, fsum-fenced"),
            "horizon_bars": args.horizon,
            "n_min": args.n_min,
            "regime_keys": list(REGIME_KEYS),
            "window": WINDOW,
        },
    }

    for target in names:
        fit_on = [n for n in names if n != target]
        fit_rows: list[tuple[str, str, Obs]] = []
        for n in fit_on:
            fit_rows.extend(per_snap_rows[n])
        regime_ics, pooled_ics, sample_counts = _fit_block(fit_rows, args.n_min)
        _report(target, fit_on, regime_ics, pooled_ics, sample_counts, seed_regime, seed_pooled)
        out[target] = {
            "fit_on": fit_on,
            "empirical_regime_ics": _round_floats(regime_ics),
            "empirical_pooled_ics": _round_floats(pooled_ics),
            "_sample_counts": sample_counts,
        }

    # Stable serialization: sorted keys, fixed indent → byte-reproducible.
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"\n[write] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
