#!/usr/bin/env python3
"""V263 Phase 1 — Kronos foundation-model smoke test on the frozen V262 1h corpus.

NOT a scorer. NOT strategy code. Read-only against ``data/frozen_series/
binance_intraday/`` — loads a symbol's 1h OHLCV, runs Kronos-small forecasts on
pre-declared windows, and reports plausibility / directional-accuracy /
RMSE-vs-naive sanity numbers.

Usage::

    HF_HOME=/Volumes/gamma-systems-2/omega-victoria-data/huggingface_cache/ \
    PYTHONPATH=third_party/kronos \
    python3 scripts/v263_kronos_smoke.py --symbol BTCUSDT --out-dir <dir>

Determinism: torch/numpy seeds are pinned per window (``--seed``), so a re-run
with identical arguments reproduces the sampled path bit-for-bit. ``--greedy``
switches to ``top_k=1`` argmax decoding, which is sampling-free.
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

# Pre-declared smoke windows (anchor = first bar of the 24-bar forecast).
# Chosen to span 2020->2026 and to hit distinct macro regimes; NOT tuned on results.
SMOKE_ANCHORS = [
    ("2020-06-15 00:00:00", "post-covid recovery"),
    ("2021-05-19 00:00:00", "may-2021 crash"),
    ("2022-06-15 00:00:00", "2022 bear / deleveraging"),
    ("2024-08-05 00:00:00", "2024aug crisis window"),
    ("2025-11-03 00:00:00", "recent"),
]


def load_symbol(symbol: str) -> pd.DataFrame:
    """Load the full frozen 1h series for ``symbol`` as a tz-naive UTC DataFrame."""
    sym_dir = CORPUS / symbol / "1h"
    if not sym_dir.is_dir():
        raise SystemExit(f"no frozen 1h corpus for {symbol} at {sym_dir}")

    rows: list[list] = []
    columns: list[str] | None = None
    for month_file in sorted(sym_dir.glob("*.json.gz")):
        with gzip.open(month_file, "rt") as fh:
            payload = json.load(fh)
        if columns is None:
            columns = payload["columns"]
        elif columns != payload["columns"]:
            raise SystemExit(f"column drift in {month_file}: {payload['columns']} != {columns}")
        rows.extend(payload["bars"])

    if not rows:
        raise SystemExit(f"empty corpus for {symbol}")

    df = pd.DataFrame(rows, columns=columns)
    ts_col = columns[0]
    df["timestamps"] = pd.to_datetime(df[ts_col], unit="ms", utc=True).dt.tz_localize(None)
    df = df.drop(columns=[ts_col]).sort_values("timestamps").reset_index(drop=True)
    # Frozen corpus is de-duplicated at freeze time; assert rather than silently dedupe.
    dupes = int(df["timestamps"].duplicated().sum())
    if dupes:
        raise SystemExit(f"{symbol}: {dupes} duplicate 1h timestamps in frozen corpus")
    return df


def build_windows(df: pd.DataFrame, lookback: int, pred_len: int) -> list[dict]:
    """Resolve each pre-declared anchor to a (lookback, forecast) index pair."""
    windows = []
    for anchor_str, label in SMOKE_ANCHORS:
        anchor = pd.Timestamp(anchor_str)
        idx = df.index[df["timestamps"] >= anchor]
        if len(idx) == 0:
            print(f"  SKIP {label}: anchor {anchor} past end of series")
            continue
        start = int(idx[0])
        if start < lookback or start + pred_len > len(df):
            print(f"  SKIP {label}: anchor {anchor} lacks {lookback}+{pred_len} bars")
            continue
        windows.append(
            {
                "label": label,
                "anchor": str(df.loc[start, "timestamps"]),
                "lb_start": start - lookback,
                "lb_end": start,
                "fc_end": start + pred_len,
            }
        )
    return windows


def rolling_windows(
    df: pd.DataFrame, lookback: int, pred_len: int, count: int, stride: int
) -> list[dict]:
    """Evenly-spaced non-overlapping-forecast windows for the directional-accuracy stat."""
    first = lookback
    last = len(df) - pred_len
    if last <= first:
        return []
    span = last - first
    step = max(stride, span // max(count, 1))
    out = []
    pos = first
    while pos < last and len(out) < count:
        out.append(
            {
                "label": f"roll_{len(out):03d}",
                "anchor": str(df.loc[pos, "timestamps"]),
                "lb_start": pos - lookback,
                "lb_end": pos,
                "fc_end": pos + pred_len,
            }
        )
        pos += step
    return out


def forecast(
    predictor,
    df: pd.DataFrame,
    win: dict,
    pred_len: int,
    seed: int,
    greedy: bool,
    sample_count: int = 1,
):
    import torch

    torch.manual_seed(seed)
    np.random.seed(seed)

    hist = df.iloc[win["lb_start"] : win["lb_end"]]
    fut = df.iloc[win["lb_end"] : win["fc_end"]]

    x_df = hist[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
    x_ts = hist["timestamps"].reset_index(drop=True)
    y_ts = fut["timestamps"].reset_index(drop=True)

    t0 = time.time()
    pred = predictor.predict(
        df=x_df,
        x_timestamp=x_ts,
        y_timestamp=y_ts,
        pred_len=pred_len,
        T=1.0,
        top_k=1 if greedy else 0,
        top_p=0.9,
        sample_count=sample_count,
        verbose=False,
    )
    elapsed = time.time() - t0
    return hist, fut, pred, elapsed


def score(hist: pd.DataFrame, fut: pd.DataFrame, pred: pd.DataFrame) -> dict:
    """Sanity metrics for one window. Naive baseline = last observed close, held flat."""
    last_close = float(hist["close"].iloc[-1])
    realized = fut["close"].to_numpy(dtype=float)
    forecast_close = pred["close"].to_numpy(dtype=float)

    naive = np.full_like(realized, last_close)

    def rmse(a, b):
        return float(np.sqrt(np.mean((a - b) ** 2)))

    def mape(a, b):
        return float(np.mean(np.abs((a - b) / b)) * 100.0)

    realized_ret = realized[-1] / last_close - 1.0
    forecast_ret = forecast_close[-1] / last_close - 1.0

    # Volatility-clustering probe: bar-to-bar log-return dispersion, forecast vs realized.
    def barvol(series, anchor):
        path = np.concatenate([[anchor], series])
        return float(np.std(np.diff(np.log(path))))

    return {
        "last_close": last_close,
        "realized_close_end": float(realized[-1]),
        "forecast_close_end": float(forecast_close[-1]),
        "realized_ret": float(realized_ret),
        "forecast_ret": float(forecast_ret),
        "direction_match": bool(np.sign(realized_ret) == np.sign(forecast_ret)),
        "rmse_kronos": rmse(forecast_close, realized),
        "rmse_naive": rmse(naive, realized),
        "mape_kronos": mape(forecast_close, realized),
        "mape_naive": mape(naive, realized),
        "vol_realized": barvol(realized, last_close),
        "vol_forecast": barvol(forecast_close, last_close),
        "has_nan": bool(np.isnan(forecast_close).any()),
        "is_constant": bool(np.allclose(forecast_close, forecast_close[0])),
        "min_ratio": float(forecast_close.min() / last_close),
        "max_ratio": float(forecast_close.max() / last_close),
    }


def plot_window(hist, fut, pred, win, metrics, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ctx = hist.tail(96)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax1.plot(ctx["timestamps"], ctx["close"], color="0.4", lw=1.2, label="history (96h)")
    ax1.plot(fut["timestamps"], fut["close"], color="tab:blue", lw=1.8, label="realized")
    ax1.plot(
        fut["timestamps"],
        pred["close"].to_numpy(),
        color="tab:red",
        lw=1.8,
        label="Kronos forecast",
    )
    ax1.axhline(metrics["last_close"], color="0.7", ls=":", lw=1)
    ax1.axvline(fut["timestamps"].iloc[0], color="0.7", ls="--", lw=1)
    ax1.set_ylabel("close")
    ax1.set_title(
        f"{win['label']} @ {win['anchor']}  |  dir_match={metrics['direction_match']}  "
        f"RMSE {metrics['rmse_kronos']:.1f} vs naive {metrics['rmse_naive']:.1f}"
    )
    ax1.legend(loc="best", fontsize=9)
    ax1.grid(alpha=0.3)

    ax2.plot(ctx["timestamps"], ctx["volume"], color="0.4", lw=1.0)
    ax2.plot(fut["timestamps"], fut["volume"], color="tab:blue", lw=1.5, label="realized")
    ax2.plot(
        fut["timestamps"], pred["volume"].to_numpy(), color="tab:red", lw=1.5, label="forecast"
    )
    ax2.set_ylabel("volume")
    ax2.legend(loc="best", fontsize=9)
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--pred-len", type=int, default=24)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--greedy", action="store_true", help="top_k=1 argmax decoding (sampling-free)"
    )
    ap.add_argument(
        "--sample-count",
        type=int,
        default=1,
        help="paths sampled per window, averaged internally -> approximates the conditional mean. "
        "sample_count=1 is a single draw from the predictive distribution and is NOT a fair "
        "RMSE comparison against a point-forecast baseline.",
    )
    ap.add_argument(
        "--rolling",
        type=int,
        default=0,
        help="extra evenly-spaced windows for the directional stat",
    )
    ap.add_argument("--rolling-stride", type=int, default=24)
    ap.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
    ap.add_argument("--model", default="NeoQuasar/Kronos-small")
    ap.add_argument("--max-context", type=int, default=512)
    ap.add_argument("--device", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()

    out_dir = (
        Path(args.out_dir or os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(REPO / "data")))
        / "v263_kronos_smoke"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    from model import Kronos, KronosPredictor, KronosTokenizer

    print(f"[load] corpus {args.symbol}")
    df = load_symbol(args.symbol)
    print(f"  {len(df):,} bars  {df['timestamps'].iloc[0]} -> {df['timestamps'].iloc[-1]}")

    print(f"[load] {args.tokenizer} + {args.model}")
    tokenizer = KronosTokenizer.from_pretrained(args.tokenizer)
    model = Kronos.from_pretrained(args.model)
    predictor = KronosPredictor(model, tokenizer, device=args.device, max_context=args.max_context)
    print(f"  device={predictor.device}  max_context={args.max_context}")

    windows = build_windows(df, args.lookback, args.pred_len)
    smoke_n = len(windows)
    if args.rolling:
        windows += rolling_windows(
            df, args.lookback, args.pred_len, args.rolling, args.rolling_stride
        )

    results = []
    for i, win in enumerate(windows):
        hist, fut, pred, elapsed = forecast(
            predictor, df, win, args.pred_len, args.seed + i, args.greedy, args.sample_count
        )
        m = score(hist, fut, pred)
        m.update({k: win[k] for k in ("label", "anchor")})
        m["elapsed_s"] = elapsed
        m["is_named_window"] = i < smoke_n
        results.append(m)
        flag = "" if not (m["has_nan"] or m["is_constant"]) else "  <-- DEGENERATE"
        print(
            f"  [{i + 1}/{len(windows)}] {win['label']:<26} {win['anchor']}  "
            f"dir={'HIT ' if m['direction_match'] else 'miss'} "
            f"rmse {m['rmse_kronos']:>9.2f} / naive {m['rmse_naive']:>9.2f}  "
            f"{elapsed:.1f}s{flag}"
        )
        if i < smoke_n and not args.no_plots:
            plot_window(
                hist, fut, pred, win, m, out_dir / f"window_{i + 1}_{win['label'].split()[0]}.png"
            )

    agg = summarize(results, smoke_n)
    payload = {
        "config": vars(args) | {"out_dir": str(out_dir)},
        "corpus": {
            "symbol": args.symbol,
            "bars": len(df),
            "first": str(df["timestamps"].iloc[0]),
            "last": str(df["timestamps"].iloc[-1]),
        },
        "aggregate": agg,
        "windows": results,
    }
    (out_dir / f"smoke_{args.symbol}.json").write_text(json.dumps(payload, indent=2))

    print("\n=== AGGREGATE ===")
    for k, v in agg.items():
        print(f"  {k:<28} {v}")
    print(f"\nartifacts -> {out_dir}")


def summarize(results: list[dict], smoke_n: int) -> dict:
    def block(rows, prefix):
        if not rows:
            return {}
        hits = sum(r["direction_match"] for r in rows)
        k_rmse = np.array([r["rmse_kronos"] for r in rows])
        n_rmse = np.array([r["rmse_naive"] for r in rows])
        wins = int((k_rmse < n_rmse).sum())
        # Two-sided binomial tail for directional accuracy vs a fair coin.
        n = len(rows)
        p = sum(
            math.comb(n, k) * 0.5**n for k in range(n + 1) if abs(k - n / 2) >= abs(hits - n / 2)
        )
        return {
            f"{prefix}_n": n,
            f"{prefix}_dir_acc": round(hits / n, 4),
            f"{prefix}_dir_hits": hits,
            f"{prefix}_dir_binom_p": round(min(p, 1.0), 4),
            f"{prefix}_rmse_beat_naive_frac": round(wins / n, 4),
            f"{prefix}_median_rmse_ratio": round(float(np.median(k_rmse / n_rmse)), 4),
            f"{prefix}_median_mape_kronos": round(
                float(np.median([r["mape_kronos"] for r in rows])), 4
            ),
            f"{prefix}_median_mape_naive": round(
                float(np.median([r["mape_naive"] for r in rows])), 4
            ),
            f"{prefix}_median_vol_ratio": round(
                float(
                    np.median(
                        [
                            r["vol_forecast"] / r["vol_realized"]
                            for r in rows
                            if r["vol_realized"] > 0
                        ]
                    )
                ),
                4,
            ),
        }

    out = {
        "any_nan": any(r["has_nan"] for r in results),
        "any_constant": any(r["is_constant"] for r in results),
        "min_price_ratio": round(min(r["min_ratio"] for r in results), 4),
        "max_price_ratio": round(max(r["max_ratio"] for r in results), 4),
        "median_elapsed_s": round(float(np.median([r["elapsed_s"] for r in results])), 3),
    }
    out |= block(results[:smoke_n], "named")
    out |= block(results, "all")
    return out


if __name__ == "__main__":
    main()
