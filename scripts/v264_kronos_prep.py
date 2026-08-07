#!/usr/bin/env python3
"""V264 Phase 1 — prepare the frozen V262 1h corpus in Kronos fine-tune format.

NOT strategy code. Read-only against ``data/frozen_series/binance_intraday/``.

Upstream's ``finetune_csv/CustomKlineDataset`` reads ONE csv and splits it by row
*ratio*. Neither property is acceptable here:

  * one csv for 14 symbols would let a sliding window straddle a symbol boundary
    (BTC history -> SOL forecast), which is pure contamination;
  * a ratio split is not the pre-registered V264 split.

So this script emits a per-symbol, date-split payload instead. The split is
strictly temporal and disjoint by calendar date:

    train : bars with ts <  2024-01-01
    val   : bars with 2024-01-01 <= ts < 2025-01-01
    test  : bars with ts >= 2025-01-01     (holdout, F4-ft is scored here only)

Anti-leakage is structural rather than asserted: every training/validation window
is drawn from within a single symbol's slice of a single split, so no window can
contain a bar from a later split. The script asserts the boundary invariants
anyway (``max(train) < min(val) < min(test)``) and refuses to write on violation.

Feature layout matches upstream exactly so the fine-tuned weights stay compatible
with ``KronosPredictor``:

    features    = [open, high, low, close, volume, amount]
    time feats  = [minute, hour, weekday, day, month]
    amount      = volume * mean(open, high, low, close)   (kronos.py:532)

Usage::

    python3 scripts/v264_kronos_prep.py --out-dir <dir>
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "data" / "frozen_series" / "binance_intraday"

FEATURE_LIST = ["open", "high", "low", "close", "volume", "amount"]
TIME_FEATURE_LIST = ["minute", "hour", "weekday", "day", "month"]

# Pre-registered temporal split boundaries (locked, V264.md).
VAL_START = pd.Timestamp("2024-01-01")
TEST_START = pd.Timestamp("2025-01-01")


def load_symbol(symbol: str) -> pd.DataFrame:
    """Load a symbol's full frozen 1h series as a tz-naive UTC DataFrame."""
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
    if not rows:
        raise SystemExit(f"empty corpus for {symbol}")

    df = pd.DataFrame(rows, columns=columns)
    ts_col = columns[0]
    df["timestamps"] = pd.to_datetime(df[ts_col], unit="ms", utc=True).dt.tz_localize(None)
    df = df.drop(columns=[ts_col]).sort_values("timestamps").reset_index(drop=True)

    dupes = int(df["timestamps"].duplicated().sum())
    if dupes:
        raise SystemExit(f"{symbol}: {dupes} duplicate 1h timestamps in frozen corpus")

    # Upstream derives amount when absent; do it here so the trained feature space
    # matches what KronosPredictor.predict feeds at inference time.
    df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)

    ts = df["timestamps"]
    df["minute"] = ts.dt.minute
    df["hour"] = ts.dt.hour
    df["weekday"] = ts.dt.weekday
    df["day"] = ts.dt.day
    df["month"] = ts.dt.month
    return df


def split_symbol(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ts = df["timestamps"]
    return {
        "train": df[ts < VAL_START].reset_index(drop=True),
        "val": df[(ts >= VAL_START) & (ts < TEST_START)].reset_index(drop=True),
        "test": df[ts >= TEST_START].reset_index(drop=True),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out-dir",
        default=None,
        help="destination for the pickles (default $OMEGA_AUDIT_OUTPUT_DIR/v264/kronos_finetune)",
    )
    ap.add_argument(
        "--min-bars", type=int, default=500, help="drop split slices shorter than this"
    )
    args = ap.parse_args()

    root = Path(args.out_dir or os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(REPO / "data")))
    out_dir = root / "v264" / "kronos_finetune" if args.out_dir is None else Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = sorted(p.name for p in CORPUS.iterdir() if (p / "1h").is_dir())
    print(f"[prep] {len(symbols)} symbols: {', '.join(symbols)}")

    payload: dict[str, dict[str, dict]] = {"train": {}, "val": {}, "test": {}}
    manifest: dict = {
        "split_boundaries": {"val_start": str(VAL_START), "test_start": str(TEST_START)},
        "feature_list": FEATURE_LIST,
        "time_feature_list": TIME_FEATURE_LIST,
        "symbols": {},
    }

    for symbol in symbols:
        df = load_symbol(symbol)
        parts = split_symbol(df)
        entry = {}
        for split, part in parts.items():
            if len(part) < args.min_bars:
                entry[split] = {"bars": len(part), "kept": False}
                continue
            payload[split][symbol] = {
                "features": part[FEATURE_LIST].to_numpy(dtype=np.float32),
                "time_features": part[TIME_FEATURE_LIST].to_numpy(dtype=np.float32),
                "first": str(part["timestamps"].iloc[0]),
                "last": str(part["timestamps"].iloc[-1]),
            }
            entry[split] = {
                "bars": len(part),
                "kept": True,
                "first": str(part["timestamps"].iloc[0]),
                "last": str(part["timestamps"].iloc[-1]),
            }
        manifest["symbols"][symbol] = entry
        desc = "  ".join(
            f"{s}={entry[s]['bars']:>6,}{'' if entry[s]['kept'] else '(drop)'}"
            for s in ("train", "val", "test")
        )
        print(f"  {symbol:<10} {desc}")

    # --- anti-leakage assertions -------------------------------------------------
    for split, other, rel in (("train", "val", "<"), ("val", "test", "<")):
        for symbol, blocks in payload[split].items():
            if symbol not in payload[other]:
                continue
            a_last = pd.Timestamp(blocks["last"])
            b_first = pd.Timestamp(payload[other][symbol]["first"])
            if not a_last < b_first:
                raise SystemExit(
                    f"LEAKAGE: {symbol} {split}.last={a_last} not {rel} {other}.first={b_first}"
                )
    for symbol, blocks in payload["test"].items():
        if pd.Timestamp(blocks["first"]) < TEST_START:
            raise SystemExit(f"LEAKAGE: {symbol} test starts {blocks['first']} < {TEST_START}")
    print("[prep] anti-leakage assertions PASS (train < val < test, test >= 2025-01-01)")

    totals = {}
    for split in ("train", "val", "test"):
        n_sym = len(payload[split])
        n_bars = sum(int(v["features"].shape[0]) for v in payload[split].values())
        totals[split] = {"symbols": n_sym, "bars": n_bars}
        path = out_dir / f"{split}_data.pkl"
        with open(path, "wb") as fh:
            pickle.dump(payload[split], fh, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"[prep] {split:<5} {n_sym:>2} symbols  {n_bars:>7,} bars -> {path}")

    manifest["totals"] = totals
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[prep] manifest -> {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
