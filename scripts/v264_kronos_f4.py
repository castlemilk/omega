#!/usr/bin/env python3
"""V264 Phase 4 — F4-ft: directional-edge gate for a (possibly fine-tuned) Kronos.

NOT strategy code. Read-only against the frozen V262 1h corpus.

This is V263's F4 statistic re-run on the **holdout only**. V263 scored windows
spanning 2020->2026, but the fine-tuned arm can only be scored on 2025-2026 (the
rest is its training data). Comparing across those two window sets would confound
the fine-tuning effect with a *period* effect — and that confound is not
hypothetical: the same zero-shot model scores -0.027 over 2020-2026 and +0.028
over 2025-2026, a swing larger than the F4 bar itself.

(To be precise: the zero-shot arm cannot be "contaminated" — it never trained on
anything. The re-run exists to give the fine-tuned arm a *period-matched* control,
not to launder a tainted one.)

So BOTH arms are evaluated on the identical 2025-2026 window set, and the honest
delta is fine-tuned minus zero-shot-on-holdout.

Windows are constrained so the entire ``lookback + pred_len`` span sits inside the
holdout: no forecast can see a bar the model was trained on.

Pre-registered gate (locked in V263, no post-hoc adjustment):
    F4-ft PASS iff pooled (mean-across-cell) Spearman rho > +0.05.

Usage::

    PYTHONPATH=third_party/kronos HF_HOME=<cache> \
    python3 scripts/v264_kronos_f4.py --arm zeroshot --tag zeroshot_holdout
    python3 scripts/v264_kronos_f4.py --arm finetuned --tag finetuned \
        --tokenizer <ckpt>/tokenizer/best_model --model <ckpt>/predictor/best_model
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "data" / "frozen_series" / "binance_intraday"

# The eight pre-declared V263 cells, carried over unchanged.
CELLS = [
    ("BTCUSDT", 1),
    ("BTCUSDT", 4),
    ("BTCUSDT", 12),
    ("BTCUSDT", 24),
    ("SOLUSDT", 1),
    ("SOLUSDT", 24),
    ("XRPUSDT", 1),
    ("XRPUSDT", 24),
]

HOLDOUT_START = pd.Timestamp("2025-01-01")
F4_BAR = 0.05


def load_symbol(symbol: str) -> pd.DataFrame:
    sym_dir = CORPUS / symbol / "1h"
    rows: list[list] = []
    columns: list[str] | None = None
    for month_file in sorted(sym_dir.glob("*.json.gz")):
        with gzip.open(month_file, "rt") as fh:
            payload = json.load(fh)
        if columns is None:
            columns = payload["columns"]
        elif columns != payload["columns"]:
            raise SystemExit(f"column drift in {month_file}")
        rows.extend(payload["bars"])
    df = pd.DataFrame(rows, columns=columns)
    ts_col = columns[0]
    df["timestamps"] = pd.to_datetime(df[ts_col], unit="ms", utc=True).dt.tz_localize(None)
    df = df.drop(columns=[ts_col]).sort_values("timestamps").reset_index(drop=True)
    if int(df["timestamps"].duplicated().sum()):
        raise SystemExit(f"{symbol}: duplicate 1h timestamps in frozen corpus")
    return df


def holdout_windows(df: pd.DataFrame, lookback: int, pred_len: int, count: int) -> list[dict]:
    """Evenly-spaced windows whose FULL span (lookback + forecast) is inside the holdout."""
    idx = df.index[df["timestamps"] >= HOLDOUT_START]
    if len(idx) == 0:
        raise SystemExit("no holdout bars")
    first = int(idx[0]) + lookback  # forecast anchor; lookback start is >= holdout start
    last = len(df) - pred_len
    if last <= first:
        raise SystemExit("holdout too short for this lookback/horizon")
    step = max(1, (last - first) // max(count, 1))
    out = []
    pos = first
    while pos < last and len(out) < count:
        out.append(
            {
                "anchor": str(df.loc[pos, "timestamps"]),
                "lb_start": pos - lookback,
                "lb_end": pos,
                "fc_end": pos + pred_len,
            }
        )
        pos += step
    return out


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    def rank(x):
        order = np.argsort(x, kind="stable")
        r = np.empty(len(x), dtype=float)
        r[order] = np.arange(len(x), dtype=float)
        _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
        sums = np.zeros(len(counts))
        np.add.at(sums, inv, r)
        return (sums / counts)[inv]

    ra, rb = rank(a), rank(b)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = math.sqrt(float((ra**2).sum()) * float((rb**2).sum()))
    return float((ra * rb).sum() / denom) if denom > 0 else 0.0


def cell_stats(rows: list[dict]) -> dict:
    f = np.array([r["forecast_ret"] for r in rows], dtype=float)
    y = np.array([r["realized_ret"] for r in rows], dtype=float)
    n = len(rows)
    rho = spearman(f, y)
    p_rho = float(math.erfc(abs(rho * math.sqrt(n - 1)) / math.sqrt(2.0)))

    fs, ys = np.sign(f), np.sign(y)
    tp = int(((fs > 0) & (ys > 0)).sum())
    tn = int(((fs < 0) & (ys < 0)).sum())
    fp = int(((fs > 0) & (ys < 0)).sum())
    fn = int(((fs < 0) & (ys > 0)).sum())
    up_recall = tp / max(tp + fn, 1)
    dn_recall = tn / max(tn + fp, 1)
    den = math.sqrt(float((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    ratios = np.array([r["rmse_kronos"] / r["rmse_naive"] for r in rows if r["rmse_naive"] > 0])
    return {
        "n": n,
        "raw_dir_acc": round(float((fs == ys).mean()), 4),
        "realized_up_rate": round(float((ys > 0).mean()), 4),
        "forecast_up_rate": round(float((fs > 0).mean()), 4),
        "balanced_acc": round((up_recall + dn_recall) / 2, 4),
        "mcc": round(((tp * tn - fp * fn) / den) if den > 0 else 0.0, 4),
        "spearman": round(rho, 4),
        "spearman_p": round(p_rho, 4),
        "median_rmse_ratio": round(float(np.median(ratios)), 4),
        "rmse_beat_naive_frac": round(float((ratios < 1.0).mean()), 4),
    }


def score_window(hist: pd.DataFrame, fut: pd.DataFrame, pred: pd.DataFrame) -> dict:
    last_close = float(hist["close"].iloc[-1])
    realized = fut["close"].to_numpy(dtype=float)
    fc = pred["close"].to_numpy(dtype=float)
    naive = np.full_like(realized, last_close)

    def rmse(a, b):
        return float(np.sqrt(np.mean((a - b) ** 2)))

    return {
        "realized_ret": float(realized[-1] / last_close - 1.0),
        "forecast_ret": float(fc[-1] / last_close - 1.0),
        "rmse_kronos": rmse(fc, realized),
        "rmse_naive": rmse(naive, realized),
        "has_nan": bool(np.isnan(fc).any()),
    }


def run_cell(predictor, df, symbol, pred_len, args) -> dict:
    wins = holdout_windows(df, args.lookback, pred_len, args.count)
    rows: list[dict] = []
    t0 = time.time()
    import torch

    for b0 in range(0, len(wins), args.batch):
        chunk = wins[b0 : b0 + args.batch]
        torch.manual_seed(args.seed + b0)
        np.random.seed(args.seed + b0)
        df_list, x_ts, y_ts, hists, futs = [], [], [], [], []
        for w in chunk:
            hist = df.iloc[w["lb_start"] : w["lb_end"]]
            fut = df.iloc[w["lb_end"] : w["fc_end"]]
            hists.append(hist)
            futs.append(fut)
            df_list.append(hist[["open", "high", "low", "close", "volume"]].reset_index(drop=True))
            x_ts.append(hist["timestamps"].reset_index(drop=True))
            y_ts.append(fut["timestamps"].reset_index(drop=True))
        preds = predictor.predict_batch(
            df_list=df_list,
            x_timestamp_list=x_ts,
            y_timestamp_list=y_ts,
            pred_len=pred_len,
            T=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=args.sample_count,
            verbose=False,
        )
        for w, hist, fut, pred in zip(chunk, hists, futs, preds, strict=True):
            m = score_window(hist, fut, pred)
            m["anchor"] = w["anchor"]
            rows.append(m)
        done = min(b0 + args.batch, len(wins))
        print(
            f"    {symbol} h{pred_len}: {done}/{len(wins)} windows "
            f"({(time.time() - t0) / done:.2f}s/window)",
            flush=True,
        )
    stats = cell_stats(rows)
    stats |= {
        "cell": f"{symbol}_h{pred_len}",
        "symbol": symbol,
        "horizon": pred_len,
        "any_nan": any(r["has_nan"] for r in rows),
        "first_anchor": rows[0]["anchor"],
        "last_anchor": rows[-1]["anchor"],
        "elapsed_s": round(time.time() - t0, 1),
    }
    return {"stats": stats, "windows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["zeroshot", "finetuned"], required=True)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
    ap.add_argument("--model", default="NeoQuasar/Kronos-small")
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--count", type=int, default=405, help="windows per cell (V263 parity)")
    ap.add_argument("--sample-count", type=int, default=8, help="V263 fairness fix")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-context", type=int, default=512)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument(
        "--cells",
        default=None,
        help="comma-separated SYMBOL:HORIZON subset (default: all 8 pre-declared cells). "
        "Long horizons need a smaller --batch; running them separately is a memory "
        "workaround, not a change to the cell set.",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="reuse an already-written windows_*.json for a cell instead of re-forecasting",
    )
    args = ap.parse_args()

    selected = CELLS
    if args.cells:
        want = {tuple(c.split(":")) for c in args.cells.split(",")}
        want = {(s, int(h)) for s, h in want}
        selected = [c for c in CELLS if c in want]
        if len(selected) != len(want):
            raise SystemExit(f"unknown cell(s) in --cells: {want - set(CELLS)}")

    tag = args.tag or args.arm
    root = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(REPO / "data"))) / "v264"
    out_dir = Path(args.out_dir) if args.out_dir else root / "f4" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    from model import Kronos, KronosPredictor, KronosTokenizer

    print(f"[f4] arm={args.arm} tokenizer={args.tokenizer} model={args.model}")
    print(f"[f4] cells={[f'{s}_h{h}' for s, h in selected]}")

    predictor = None
    corpus_cache: dict[str, pd.DataFrame] = {}
    cells = []
    for symbol, horizon in selected:
        wpath = out_dir / f"windows_{symbol}_h{horizon}.json"
        if args.resume and wpath.exists():
            rows = json.loads(wpath.read_text())
            stats = cell_stats(rows) | {
                "cell": f"{symbol}_h{horizon}",
                "symbol": symbol,
                "horizon": horizon,
                "any_nan": any(r["has_nan"] for r in rows),
                "first_anchor": rows[0]["anchor"],
                "last_anchor": rows[-1]["anchor"],
                "resumed": True,
            }
            cells.append(stats)
            print(f"  [cell] {stats['cell']}  rho={stats['spearman']:+.4f}  (resumed)", flush=True)
            continue
        if predictor is None:
            tokenizer = KronosTokenizer.from_pretrained(args.tokenizer)
            model = Kronos.from_pretrained(args.model)
            predictor = KronosPredictor(
                model, tokenizer, device=args.device, max_context=args.max_context
            )
            print(f"[f4] device={predictor.device}  holdout >= {HOLDOUT_START}")
        if symbol not in corpus_cache:
            corpus_cache[symbol] = load_symbol(symbol)
        res = run_cell(predictor, corpus_cache[symbol], symbol, horizon, args)
        cells.append(res["stats"])
        wpath.write_text(json.dumps(res["windows"]))
        print(f"  [cell] {res['stats']['cell']}  rho={res['stats']['spearman']:+.4f}", flush=True)

    pooled = float(np.mean([c["spearman"] for c in cells]))
    k = len(cells)
    summary = {
        "arm": args.arm,
        "tag": tag,
        "tokenizer": args.tokenizer,
        "model": args.model,
        "holdout_start": str(HOLDOUT_START),
        "config": vars(args),
        "cells": cells,
        "pooled_spearman": round(pooled, 4),
        "f4_bar": F4_BAR,
        "f4_pass": bool(pooled > F4_BAR),
        "bonferroni_alpha": 0.05 / k,
        "cells_pass_bonferroni": sum(1 for c in cells if c["spearman_p"] < 0.05 / k),
        "cells_beating_naive_rmse": sum(1 for c in cells if c["median_rmse_ratio"] < 1.0),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    hdr = (
        f"{'cell':<16}{'n':>5}{'rawAcc':>8}{'upRate':>8}{'fcUp':>7}"
        f"{'balAcc':>8}{'MCC':>8}{'rho':>9}{'p(rho)':>9}{'bonf':>7}{'rmseR':>8}"
    )
    print("\n" + hdr)
    print("-" * len(hdr))
    for c in cells:
        sig = "PASS" if c["spearman_p"] < 0.05 / k else "-"
        print(
            f"{c['cell']:<16}{c['n']:>5}{c['raw_dir_acc']:>8.3f}{c['realized_up_rate']:>8.3f}"
            f"{c['forecast_up_rate']:>7.3f}{c['balanced_acc']:>8.3f}{c['mcc']:>8.3f}"
            f"{c['spearman']:>+9.3f}{c['spearman_p']:>9.4f}{sig:>7}{c['median_rmse_ratio']:>8.3f}"
        )
    print(
        f"\npooled Spearman = {pooled:+.4f}  vs F4 bar +{F4_BAR}  -> "
        f"F4{'-ft' if args.arm == 'finetuned' else ''} "
        f"{'PASS' if summary['f4_pass'] else 'FAIL'}"
    )
    print(f"cells beating naive RMSE = {summary['cells_beating_naive_rmse']}/{k}")
    print(f"summary -> {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
