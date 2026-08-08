#!/usr/bin/env python3
"""V265 — Kronos DISTRIBUTIONAL use: realized-volatility forecasting.

NOT strategy code. NOT a directional signal. Read-only against the frozen V262 1h
corpus. No strategy module (victoria / funding_carry / on_chain / intraday_alpha)
is imported or touched.

Motivation (V264 §3a): fine-tuning taught Kronos our *volatility*, not our
direction -- the fine-tuned model emits higher-dispersion paths that nudged rank
correlation up and made point-forecast RMSE decisively worse. V263 and V264 both
flagged distributional use as the one untested Kronos idea, belonging to the
regime/sizing lane rather than the alpha lane. V265 tests exactly that and
nothing more.

Hypothesis: the cross-sample STANDARD DEVIATION of Kronos's ``sample_count``
forecast paths predicts realized per-bar volatility over the same horizon better
than a naive rolling-std baseline.

Pre-registered gates (locked in V265.md BEFORE this ran; no post-hoc tuning):
    F5-vol    pooled RMSE(kronos) / RMSE(naive) < 0.90
    F5-corr   pooled Spearman rho(spread, realized vol) > +0.20
    F5-regime Kruskal-Wallis across spread-quintile groups, p < 0.01

Estimator definitions (locked with the gates -- see V265.md section 3):

  Let C_0 be the last actual close of the lookback and H the horizon.

  realized  sigma_real = sqrt( mean_{t=1..H} r_t^2 ),  r_t = log(C_t / C_{t-1})
            (RMS per-bar log return; the zero-mean realized-vol estimator, which
            unlike a sample std is defined at H = 1)

  kronos    sigma_hat  = mean_{t=1..H} ( std_s[ log(C_{s,t} / C_0) ] / sqrt(t) )
            (per-timestep cross-sample dispersion, de-trended by sqrt(t) so each
            term is a per-bar vol estimate under a diffusion; this is the brief's
            "mean std over horizon" put in per-bar units so it is directly
            comparable to sigma_real and to the naive baseline)

  naive     sigma_nv   = sqrt( mean of the last 24 squared per-bar log returns
            of the lookback )

All three are per-bar volatilities in log-return units.

Usage::

    PYTHONPATH=third_party/kronos \
    HF_HOME=/Volumes/gamma-systems-2/omega-victoria-data/huggingface_cache/ \
    python3 scripts/v265_kronos_vol_scorer.py --arm finetuned \
        --tokenizer $AUDIT/v264/checkpoints/tokenizer/best_model \
        --model $AUDIT/v264/checkpoints/predictor/best_model
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

# The eight pre-declared V263/V264 cells, carried over unchanged.
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

# Same holdout fence as V264: the whole lookback+forecast span sits after this,
# so no scored window can condition on a bar the fine-tuned model trained on.
HOLDOUT_START = pd.Timestamp("2025-01-01")

NAIVE_WINDOW = 24  # bars of past returns for the naive rolling-vol baseline

# --- pre-registered bars (locked; see V265.md) -------------------------------
F5_VOL_BAR = 0.90  # pooled RMSE ratio must be BELOW this
F5_CORR_BAR = 0.20  # pooled Spearman must be ABOVE this
F5_REGIME_ALPHA = 0.01  # Kruskal-Wallis p must be BELOW this
N_QUINTILES = 5

CLOSE_IDX = 3  # column order is [open, high, low, close, volume, amount]


# --------------------------------------------------------------------------
# corpus
# --------------------------------------------------------------------------
def load_symbol(symbol: str) -> pd.DataFrame:
    """Identical loader to v264_kronos_f4.py (same frozen monthly shards)."""
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
    """Evenly-spaced windows whose FULL span (lookback + forecast) is in holdout."""
    idx = df.index[df["timestamps"] >= HOLDOUT_START]
    if len(idx) == 0:
        raise SystemExit("no holdout bars")
    first = int(idx[0]) + lookback
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


# --------------------------------------------------------------------------
# sample-path extraction
#
# The vendored ``auto_regressive_inference`` averages over the sample axis at
# kronos.py:467 (``np.mean(preds, axis=1)``) and ``predict_batch`` then wraps the
# result in DataFrames -- so the cross-sample dispersion V265 needs is destroyed
# inside the library. The two functions below are faithful ports of the vendored
# decode + batch-preprocessing paths with the mean removed, keeping the sample
# axis intact. Vendored code is NOT modified (same discipline as V264's
# fine-tune port).
# --------------------------------------------------------------------------
def _inference_samples(
    tokenizer, model, x, x_stamp, y_stamp, max_context, pred_len, clip, T, top_k, top_p, sample_count
):
    """Port of model.kronos.auto_regressive_inference, returning (B, S, L, F).

    Byte-faithful to the vendored function through the decode loop; the only
    delta is that ``np.mean(preds, axis=1)`` is not applied.
    """
    import torch

    from model.kronos import sample_from_logits

    with torch.no_grad():
        x = torch.clip(x, -clip, clip)
        device = x.device
        x = x.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, x.size(1), x.size(2)).to(device)
        x_stamp = (
            x_stamp.unsqueeze(1)
            .repeat(1, sample_count, 1, 1)
            .reshape(-1, x_stamp.size(1), x_stamp.size(2))
            .to(device)
        )
        y_stamp = (
            y_stamp.unsqueeze(1)
            .repeat(1, sample_count, 1, 1)
            .reshape(-1, y_stamp.size(1), y_stamp.size(2))
            .to(device)
        )

        x_token = tokenizer.encode(x, half=True)

        initial_seq_len = x.size(1)
        batch_size = x_token[0].size(0)
        total_seq_len = initial_seq_len + pred_len
        full_stamp = torch.cat([x_stamp, y_stamp], dim=1)

        generated_pre = x_token[0].new_empty(batch_size, pred_len)
        generated_post = x_token[1].new_empty(batch_size, pred_len)

        pre_buffer = x_token[0].new_zeros(batch_size, max_context)
        post_buffer = x_token[1].new_zeros(batch_size, max_context)
        buffer_len = min(initial_seq_len, max_context)
        if buffer_len > 0:
            start_idx = max(0, initial_seq_len - max_context)
            pre_buffer[:, :buffer_len] = x_token[0][:, start_idx : start_idx + buffer_len]
            post_buffer[:, :buffer_len] = x_token[1][:, start_idx : start_idx + buffer_len]

        for i in range(pred_len):
            current_seq_len = initial_seq_len + i
            window_len = min(current_seq_len, max_context)

            if current_seq_len <= max_context:
                input_tokens = [pre_buffer[:, :window_len], post_buffer[:, :window_len]]
            else:
                input_tokens = [pre_buffer, post_buffer]

            context_end = current_seq_len
            context_start = max(0, context_end - max_context)
            current_stamp = full_stamp[:, context_start:context_end, :].contiguous()

            s1_logits, context = model.decode_s1(input_tokens[0], input_tokens[1], current_stamp)
            s1_logits = s1_logits[:, -1, :]
            sample_pre = sample_from_logits(
                s1_logits, temperature=T, top_k=top_k, top_p=top_p, sample_logits=True
            )

            s2_logits = model.decode_s2(context, sample_pre)
            s2_logits = s2_logits[:, -1, :]
            sample_post = sample_from_logits(
                s2_logits, temperature=T, top_k=top_k, top_p=top_p, sample_logits=True
            )

            generated_pre[:, i] = sample_pre.squeeze(-1)
            generated_post[:, i] = sample_post.squeeze(-1)

            if current_seq_len < max_context:
                pre_buffer[:, current_seq_len] = sample_pre.squeeze(-1)
                post_buffer[:, current_seq_len] = sample_post.squeeze(-1)
            else:
                pre_buffer.copy_(torch.roll(pre_buffer, shifts=-1, dims=1))
                post_buffer.copy_(torch.roll(post_buffer, shifts=-1, dims=1))
                pre_buffer[:, -1] = sample_pre.squeeze(-1)
                post_buffer[:, -1] = sample_post.squeeze(-1)

        full_pre = torch.cat([x_token[0], generated_pre], dim=1)
        full_post = torch.cat([x_token[1], generated_post], dim=1)

        context_start = max(0, total_seq_len - max_context)
        input_tokens = [
            full_pre[:, context_start:total_seq_len].contiguous(),
            full_post[:, context_start:total_seq_len].contiguous(),
        ]
        z = tokenizer.decode(input_tokens, half=True)
        z = z.reshape(-1, sample_count, z.size(1), z.size(2))
        return z.cpu().numpy()  # (B, S, L, F) -- sample axis PRESERVED


def predict_batch_samples(predictor, df_list, x_ts_list, y_ts_list, pred_len, T, top_k, top_p, sample_count):
    """Port of KronosPredictor.predict_batch returning per-sample paths.

    Same normalisation (per-series z-score over the lookback + clip) and same
    denormalisation as the vendored method; returns (B, S, pred_len, F) in price
    units instead of a list of sample-averaged DataFrames.
    """
    import torch

    from model.kronos import calc_time_stamps

    price_cols = predictor.price_cols
    vol_col, amt_col = predictor.vol_col, predictor.amt_vol

    x_list, x_stamp_list, y_stamp_list, means, stds = [], [], [], [], []
    for df, x_ts, y_ts in zip(df_list, x_ts_list, y_ts_list, strict=True):
        df = df.copy()
        if vol_col not in df.columns:
            df[vol_col] = 0.0
            df[amt_col] = 0.0
        if amt_col not in df.columns:
            df[amt_col] = df[vol_col] * df[price_cols].mean(axis=1)
        cols = price_cols + [vol_col, amt_col]
        if df[cols].isnull().values.any():
            raise ValueError("NaN in input frame")

        x = df[cols].values.astype(np.float32)
        x_mean, x_std = np.mean(x, axis=0), np.std(x, axis=0)
        x_norm = np.clip((x - x_mean) / (x_std + 1e-5), -predictor.clip, predictor.clip)

        x_list.append(x_norm)
        x_stamp_list.append(calc_time_stamps(x_ts).values.astype(np.float32))
        y_stamp_list.append(calc_time_stamps(y_ts).values.astype(np.float32))
        means.append(x_mean)
        stds.append(x_std)

    x_batch = torch.from_numpy(np.stack(x_list).astype(np.float32)).to(predictor.device)
    x_stamp_batch = torch.from_numpy(np.stack(x_stamp_list).astype(np.float32)).to(predictor.device)
    y_stamp_batch = torch.from_numpy(np.stack(y_stamp_list).astype(np.float32)).to(predictor.device)

    raw = _inference_samples(
        predictor.tokenizer,
        predictor.model,
        x_batch,
        x_stamp_batch,
        y_stamp_batch,
        predictor.max_context,
        pred_len,
        predictor.clip,
        T,
        top_k,
        top_p,
        sample_count,
    )
    raw = raw[:, :, -pred_len:, :]  # (B, S, pred_len, F)

    out = np.empty_like(raw)
    for i in range(raw.shape[0]):
        out[i] = raw[i] * (stds[i] + 1e-5) + means[i]
    return out


# --------------------------------------------------------------------------
# estimators (locked with the gates)
# --------------------------------------------------------------------------
def realized_vol(last_close: float, future_closes: np.ndarray) -> float:
    """RMS per-bar log return over the forecast horizon. Defined at H = 1."""
    path = np.concatenate([[last_close], future_closes])
    r = np.diff(np.log(path))
    return float(np.sqrt(np.mean(r**2)))


def naive_vol(lookback_closes: np.ndarray, window: int = NAIVE_WINDOW) -> float:
    """RMS per-bar log return over the trailing `window` bars of the lookback."""
    tail = lookback_closes[-(window + 1) :]
    r = np.diff(np.log(tail))
    return float(np.sqrt(np.mean(r**2)))


def kronos_spread_vol(last_close: float, sample_closes: np.ndarray) -> tuple[float, float]:
    """Cross-sample dispersion -> per-bar vol.

    sample_closes: (S, H) close paths.
    Returns (primary sigma_hat, terminal-only sigma_hat) -- the second is a
    secondary diagnostic, NOT the gated statistic.
    """
    lr = np.log(sample_closes / last_close)  # (S, H), log return from anchor
    # ddof=1: unbiased cross-sample dispersion at finite S.
    disp = lr.std(axis=0, ddof=1)  # (H,)
    t = np.arange(1, sample_closes.shape[1] + 1, dtype=float)
    per_bar = disp / np.sqrt(t)
    return float(np.mean(per_bar)), float(disp[-1] / math.sqrt(t[-1]))


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def _rankdata(x: np.ndarray) -> np.ndarray:
    """Average-tie ranks (1-based), matching scipy.stats.rankdata."""
    order = np.argsort(x, kind="stable")
    r = np.empty(len(x), dtype=float)
    r[order] = np.arange(1, len(x) + 1, dtype=float)
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inv, r)
    return (sums / counts)[inv]


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = _rankdata(a), _rankdata(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = math.sqrt(float((ra**2).sum()) * float((rb**2).sum()))
    return float((ra * rb).sum() / denom) if denom > 0 else 0.0


def spearman_p(rho: float, n: int) -> float:
    """Two-sided normal approximation, same form V263/V264 used."""
    if n < 3:
        return 1.0
    return float(math.erfc(abs(rho * math.sqrt(n - 1)) / math.sqrt(2.0)))


def _chi2_sf(x: float, k: int) -> float:
    """Upper tail of chi-square with k dof (k >= 1), via regularised gamma Q."""
    if x <= 0:
        return 1.0
    a, xx = k / 2.0, x / 2.0
    if xx < a + 1.0:
        # series for P(a, x)
        term = 1.0 / a
        total = term
        n = 0
        while n < 10000:
            n += 1
            term *= xx / (a + n)
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        p = total * math.exp(-xx + a * math.log(xx) - math.lgamma(a))
        return 1.0 - p
    # continued fraction for Q(a, x)
    tiny = 1e-300
    b = xx + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return float(h * math.exp(-xx + a * math.log(xx) - math.lgamma(a)))


def kruskal_wallis(groups: list[np.ndarray]) -> tuple[float, float, int]:
    """Kruskal-Wallis H with tie correction. Returns (H, p, dof)."""
    groups = [g for g in groups if len(g) > 0]
    k = len(groups)
    if k < 2:
        return 0.0, 1.0, 0
    allv = np.concatenate(groups)
    n = len(allv)
    ranks = _rankdata(allv)
    h = 0.0
    pos = 0
    for g in groups:
        rg = ranks[pos : pos + len(g)]
        pos += len(g)
        h += (rg.sum() ** 2) / len(g)
    h = 12.0 / (n * (n + 1)) * h - 3.0 * (n + 1)
    # tie correction
    _, counts = np.unique(allv, return_counts=True)
    ties = float(np.sum(counts**3 - counts))
    if ties > 0 and n > 1:
        h /= 1.0 - ties / (n**3 - n)
    dof = k - 1
    return float(h), _chi2_sf(float(h), dof), dof


def quintile_groups(x: np.ndarray, y: np.ndarray, q: int = N_QUINTILES) -> list[np.ndarray]:
    """Split y by quantile bins of x (rank-based, robust to ties)."""
    r = _rankdata(x)
    edges = np.linspace(0, len(x), q + 1)
    idx = np.clip(np.searchsorted(edges, r - 1e-9, side="right") - 1, 0, q - 1)
    return [y[idx == i] for i in range(q)]


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def cell_stats(rows: list[dict]) -> dict:
    fk = np.array([r["kronos_vol"] for r in rows], dtype=float)
    fn = np.array([r["naive_vol"] for r in rows], dtype=float)
    y = np.array([r["realized_vol"] for r in rows], dtype=float)
    n = len(rows)

    rk, rn = rmse(fk, y), rmse(fn, y)
    rho_k, rho_n = spearman(fk, y), spearman(fn, y)

    # Secondary, explicitly NOT gated: scale-calibrated RMSE. Kronos-spread is a
    # dispersion statistic and may be right in shape but wrong in level; a single
    # in-sample global scalar separates "no information" from "wrong units".
    scale = float(np.median(y) / np.median(fk)) if np.median(fk) > 0 else 0.0
    rk_cal = rmse(fk * scale, y)

    h, p_kw, dof = kruskal_wallis(quintile_groups(fk, y))
    h_n, p_kw_n, _ = kruskal_wallis(quintile_groups(fn, y))
    qmeans = [float(g.mean()) if len(g) else float("nan") for g in quintile_groups(fk, y)]

    return {
        "n": n,
        "mean_kronos_vol": round(float(fk.mean()), 6),
        "mean_naive_vol": round(float(fn.mean()), 6),
        "mean_realized_vol": round(float(y.mean()), 6),
        "rmse_kronos": round(rk, 6),
        "rmse_naive": round(rn, 6),
        "rmse_ratio": round(rk / rn, 4) if rn > 0 else float("nan"),
        "rmse_kronos_calibrated": round(rk_cal, 6),
        "rmse_ratio_calibrated": round(rk_cal / rn, 4) if rn > 0 else float("nan"),
        "calib_scale": round(scale, 4),
        "spearman_kronos": round(rho_k, 4),
        "spearman_kronos_p": round(spearman_p(rho_k, n), 6),
        "spearman_naive": round(rho_n, 4),
        "kw_H": round(h, 3),
        "kw_p": p_kw,
        "kw_dof": dof,
        "kw_naive_H": round(h_n, 3),
        "kw_naive_p": p_kw_n,
        "quintile_mean_realized": [round(v, 6) for v in qmeans],
    }


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def run_cell(predictor, df, symbol, pred_len, args) -> dict:
    import torch

    wins = holdout_windows(df, args.lookback, pred_len, args.count)
    rows: list[dict] = []
    t0 = time.time()

    for b0 in range(0, len(wins), args.batch):
        chunk = wins[b0 : b0 + args.batch]
        # Deterministic function of the window index -- identical args reproduce.
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

        paths = predict_batch_samples(
            predictor, df_list, x_ts, y_ts, pred_len, args.temperature, args.top_k, args.top_p, args.sample_count
        )  # (B, S, H, F)

        for w, hist, fut, p in zip(chunk, hists, futs, paths, strict=True):
            lb_close = hist["close"].to_numpy(dtype=float)
            last_close = float(lb_close[-1])
            fut_close = fut["close"].to_numpy(dtype=float)
            sample_closes = p[:, :, CLOSE_IDX].astype(float)  # (S, H)

            sigma_hat, sigma_terminal = kronos_spread_vol(last_close, sample_closes)
            rows.append(
                {
                    "anchor": w["anchor"],
                    "kronos_vol": sigma_hat,
                    "kronos_vol_terminal": sigma_terminal,
                    "naive_vol": naive_vol(lb_close),
                    "realized_vol": realized_vol(last_close, fut_close),
                    "has_nan": bool(np.isnan(sample_closes).any()),
                }
            )

        done = min(b0 + args.batch, len(wins))
        print(
            f"    {symbol} h{pred_len}: {done}/{len(wins)} windows "
            f"({(time.time() - t0) / done:.2f}s/window)",
            flush=True,
        )

    stats = cell_stats(rows) | {
        "cell": f"{symbol}_h{pred_len}",
        "symbol": symbol,
        "horizon": pred_len,
        "any_nan": any(r["has_nan"] for r in rows),
        "first_anchor": rows[0]["anchor"],
        "last_anchor": rows[-1]["anchor"],
        "elapsed_s": round(time.time() - t0, 1),
    }
    return {"stats": stats, "windows": rows}


def pooled_report(cells: list[dict], all_rows: dict[str, list[dict]]) -> dict:
    """Pooled statistics + the three pre-registered gate verdicts.

    Pooling convention is V264's: mean across cells, so no cell dominates by
    virtue of a larger price scale or a longer horizon. Global (window-level)
    variants are reported alongside as secondary colour.
    """
    ratios = [c["rmse_ratio"] for c in cells]
    rhos = [c["spearman_kronos"] for c in cells]

    pooled_ratio = float(np.mean(ratios))
    pooled_rho = float(np.mean(rhos))

    # Pooled KW: standardise within cell (rank-normalise realized vol, bin by
    # within-cell spread quintile) so cells with different vol levels can be
    # combined without the between-cell level difference manufacturing an effect.
    grp: list[list[float]] = [[] for _ in range(N_QUINTILES)]
    for cell, rows in all_rows.items():
        fk = np.array([r["kronos_vol"] for r in rows], dtype=float)
        y = np.array([r["realized_vol"] for r in rows], dtype=float)
        yn = _rankdata(y) / (len(y) + 1.0)
        for i, g in enumerate(quintile_groups(fk, yn)):
            grp[i].extend(g.tolist())
    kw_H, kw_p, kw_dof = kruskal_wallis([np.array(g) for g in grp])

    return {
        "pooled_rmse_ratio": round(pooled_ratio, 4),
        "pooled_rmse_ratio_calibrated": round(float(np.mean([c["rmse_ratio_calibrated"] for c in cells])), 4),
        "pooled_spearman": round(pooled_rho, 4),
        "pooled_spearman_naive": round(float(np.mean([c["spearman_naive"] for c in cells])), 4),
        "pooled_kw_H": round(kw_H, 3),
        "pooled_kw_p": kw_p,
        "pooled_kw_dof": kw_dof,
        "pooled_kw_quintile_mean_rank": [round(float(np.mean(g)), 4) for g in grp],
        "f5_vol_bar": F5_VOL_BAR,
        "f5_vol_pass": bool(pooled_ratio < F5_VOL_BAR),
        "f5_corr_bar": F5_CORR_BAR,
        "f5_corr_pass": bool(pooled_rho > F5_CORR_BAR),
        "f5_regime_alpha": F5_REGIME_ALPHA,
        "f5_regime_pass": bool(kw_p < F5_REGIME_ALPHA),
        "cells_beating_naive_rmse": sum(1 for r in ratios if r < 1.0),
        "cells_beating_naive_rho": sum(
            1 for c in cells if c["spearman_kronos"] > c["spearman_naive"]
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["finetuned", "zeroshot"], default="finetuned")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
    ap.add_argument("--model", default="NeoQuasar/Kronos-small")
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--count", type=int, default=405, help="windows per cell (V263/V264 parity)")
    ap.add_argument("--sample-count", type=int, default=16, help="paths per window (V265 spread)")
    ap.add_argument("--batch", type=int, default=4, help="batch x sample_count concurrent sequences")
    ap.add_argument("--max-context", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--cells", default=None, help="comma-separated SYMBOL:HORIZON subset")
    ap.add_argument("--resume", action="store_true", help="reuse already-written windows_*.json")
    ap.add_argument("--rescore-only", action="store_true", help="recompute stats from stored windows; no inference")
    args = ap.parse_args()

    selected = CELLS
    if args.cells:
        want = {(s, int(h)) for s, h in (c.split(":") for c in args.cells.split(","))}
        selected = [c for c in CELLS if c in want]
        if len(selected) != len(want):
            raise SystemExit(f"unknown cell(s): {want - set(CELLS)}")

    tag = args.tag or args.arm
    root = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(REPO / "data"))) / "v265"
    out_dir = Path(args.out_dir) if args.out_dir else root / "vol" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[v265] arm={args.arm} tokenizer={args.tokenizer} model={args.model}")
    print(f"[v265] sample_count={args.sample_count} cells={[f'{s}_h{h}' for s, h in selected]}")

    predictor = None
    corpus_cache: dict[str, pd.DataFrame] = {}
    cells: list[dict] = []
    all_rows: dict[str, list[dict]] = {}

    for symbol, horizon in selected:
        name = f"{symbol}_h{horizon}"
        wpath = out_dir / f"windows_{name}.json"
        if (args.resume or args.rescore_only) and wpath.exists():
            rows = json.loads(wpath.read_text())
            stats = cell_stats(rows) | {
                "cell": name,
                "symbol": symbol,
                "horizon": horizon,
                "any_nan": any(r["has_nan"] for r in rows),
                "first_anchor": rows[0]["anchor"],
                "last_anchor": rows[-1]["anchor"],
                "resumed": True,
            }
            cells.append(stats)
            all_rows[name] = rows
            print(f"  [cell] {name}  rho={stats['spearman_kronos']:+.4f}  (resumed)", flush=True)
            continue
        if args.rescore_only:
            raise SystemExit(f"--rescore-only but {wpath} missing")

        if predictor is None:
            from model import Kronos, KronosPredictor, KronosTokenizer

            tokenizer = KronosTokenizer.from_pretrained(args.tokenizer)
            model = Kronos.from_pretrained(args.model)
            predictor = KronosPredictor(model, tokenizer, device=args.device, max_context=args.max_context)
            print(f"[v265] device={predictor.device}  holdout >= {HOLDOUT_START}")
        if symbol not in corpus_cache:
            corpus_cache[symbol] = load_symbol(symbol)

        res = run_cell(predictor, corpus_cache[symbol], symbol, horizon, args)
        cells.append(res["stats"])
        all_rows[name] = res["windows"]
        wpath.write_text(json.dumps(res["windows"]))
        print(f"  [cell] {name}  rho={res['stats']['spearman_kronos']:+.4f}", flush=True)

    pooled = pooled_report(cells, all_rows)
    summary = {
        "version": "V265",
        "arm": args.arm,
        "tag": tag,
        "tokenizer": args.tokenizer,
        "model": args.model,
        "holdout_start": str(HOLDOUT_START),
        "naive_window_bars": NAIVE_WINDOW,
        "config": vars(args),
        "cells": cells,
    } | pooled
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    hdr = (
        f"{'cell':<16}{'n':>5}{'fcVol':>10}{'naiveVol':>10}{'realVol':>10}"
        f"{'rmseR':>8}{'rmseRcal':>10}{'rho':>9}{'p(rho)':>10}{'KWp':>11}"
    )
    print("\n" + hdr)
    print("-" * len(hdr))
    for c in cells:
        print(
            f"{c['cell']:<16}{c['n']:>5}{c['mean_kronos_vol']:>10.5f}{c['mean_naive_vol']:>10.5f}"
            f"{c['mean_realized_vol']:>10.5f}{c['rmse_ratio']:>8.3f}{c['rmse_ratio_calibrated']:>10.3f}"
            f"{c['spearman_kronos']:>+9.3f}{c['spearman_kronos_p']:>10.4f}{c['kw_p']:>11.2e}"
        )

    print(
        f"\nF5-vol    pooled RMSE ratio = {pooled['pooled_rmse_ratio']:.4f}  "
        f"(bar < {F5_VOL_BAR})  -> {'PASS' if pooled['f5_vol_pass'] else 'FAIL'}"
    )
    print(
        f"F5-corr   pooled Spearman   = {pooled['pooled_spearman']:+.4f}  "
        f"(bar > +{F5_CORR_BAR})  -> {'PASS' if pooled['f5_corr_pass'] else 'FAIL'}"
    )
    print(
        f"F5-regime pooled KW p       = {pooled['pooled_kw_p']:.3e}  "
        f"(bar < {F5_REGIME_ALPHA})  -> {'PASS' if pooled['f5_regime_pass'] else 'FAIL'}"
    )
    print(
        f"\n[secondary] calibrated pooled RMSE ratio = {pooled['pooled_rmse_ratio_calibrated']:.4f}"
        f"   naive pooled rho = {pooled['pooled_spearman_naive']:+.4f}"
    )
    print(f"summary -> {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
