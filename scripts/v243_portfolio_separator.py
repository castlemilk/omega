#!/usr/bin/env python3
"""V243 portfolio-level separator — analysis-only, committed-artifacts-only.

Reads the V240 SELECTIVE-UNIVERSE confirm-grid per-trade ledgers (32 walk-forward
windows, round r1) and computes four portfolio-risk-budgeting separators:

  (a) Correlation surface   — cross-name co-movement of realized P&L, by regime
  (b) Variance decomposition — each name's marginal contribution to portfolio risk,
                               with a spotlight on negative-PnL windows
  (c) Kelly fraction         — realized edge (mean/var) per name per regime; sign
  (d) HRP paper backtest     — hierarchical-risk-parity weights vs equal-notional

IMPORTANT METHODOLOGY NOTE
--------------------------
No OHLCV price series is committed (the frozen-cache manifest freezes only
funding / advanced-signals / macro; klines are fetched live at run time). A
literal "60-day price-return correlation matrix" would need live data → out of
scope. So every correlation / variance / Kelly figure below is computed on the
*realized strategy P&L streams* the strategy actually took — i.e. the correlation
of the positions the book carried, aggregated to per-window per-name granularity.
For risk-budgeting the strategy's OWN book this is the decision-relevant object,
not raw buy-and-hold price correlation. All paper-backtest Δ's are IN-SAMPLE
(weights fit on the same windows they are scored on) — an optimistic upper bound
used only as a go/no-go filter for pre-registration. A surviving scheme must then
be re-tested walk-forward (t-1 weights → t returns) in a real grid.

Universe (from the data, authoritative): the V240 selective universe is the
13-name full universe minus blacklist {BTC,DOT,LINK} = 10 names actually traded:
  ETH SOL BNB AVAX XRP SUI MATIC ADA NEAR ARB
(The spawn brief's "6-name SOL/BNB/AVAX/XRP/SUI/MATIC" is superseded by the ledger.)
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np

VOL = "/Volumes/gamma-systems-2/omega-victoria-data"
PAT = os.path.join(VOL, "v240wf_snap_wf_*_universe_selective_*_r1_trades.csv")
FNAME_RE = re.compile(r"v240wf_snap_wf_(\d{8})_universe_selective_([a-z]+)_r1_trades\.csv$")


def load_trades():
    """Return list of trade dicts across all 32 r1 confirm windows (top-level only,
    excluding the *_determinism/ duplicate copies)."""
    rows = []
    seen_windows = {}
    for path in sorted(glob.glob(PAT)):
        # skip the determinism-subdir duplicates: those live one level deeper
        if os.path.basename(os.path.dirname(path)).endswith("_determinism"):
            continue
        m = FNAME_RE.search(os.path.basename(path))
        if not m:
            continue
        window, regime = m.group(1), m.group(2)
        seen_windows[window] = regime
        with open(path) as fh:
            for r in csv.DictReader(fh):
                size = float(r["size"])
                pnl = float(r["pnl"])
                rows.append(
                    {
                        "window": window,
                        "regime": regime,
                        "symbol": r["symbol"].replace("USDT", ""),
                        "side": r["side"],
                        "size": size,           # dollar notional
                        "pnl": pnl,
                        "ret": pnl / size if size else 0.0,  # return on notional
                        "cycle": int(r["cycle"]),
                        "hold": int(r["hold_cycles"]),
                    }
                )
    return rows, seen_windows


def build_matrices(rows, names, windows):
    """window x name matrices of summed PnL, summed notional, and notional-weighted
    return (name window return = sum pnl / sum notional)."""
    nidx = {n: i for i, n in enumerate(names)}
    widx = {w: i for i, w in enumerate(windows)}
    pnl = np.full((len(windows), len(names)), np.nan)
    notl = np.full((len(windows), len(names)), np.nan)
    agg = defaultdict(lambda: [0.0, 0.0])  # (window,name) -> [pnl, notional]
    for r in rows:
        k = (r["window"], r["symbol"])
        agg[k][0] += r["pnl"]
        agg[k][1] += r["size"]
    for (w, n), (p, no) in agg.items():
        pnl[widx[w], nidx[n]] = p
        notl[widx[w], nidx[n]] = no
    ret = np.where(notl > 0, pnl / notl, np.nan)
    return pnl, notl, ret


def pairwise_complete_corr(mat):
    """Correlation matrix over columns using pairwise-complete rows. Returns
    (corr, avg_offdiag_corr) where avg ignores NaN pairs."""
    k = mat.shape[1]
    corr = np.full((k, k), np.nan)
    for i in range(k):
        for j in range(k):
            a, b = mat[:, i], mat[:, j]
            mask = ~np.isnan(a) & ~np.isnan(b)
            if mask.sum() >= 3 and np.std(a[mask]) > 0 and np.std(b[mask]) > 0:
                corr[i, j] = np.corrcoef(a[mask], b[mask])[0, 1]
    off = corr[~np.eye(k, dtype=bool)]
    avg = float(np.nanmean(off)) if np.any(~np.isnan(off)) else float("nan")
    return corr, avg


def analysis_a_correlation(ret, names, windows, win_regime):
    """Per-regime average pairwise correlation of per-name realized returns."""
    out = {"per_regime": {}, "note": "corr of realized per-name window returns (pairwise-complete, >=3 shared windows)"}
    regimes = ["crisis", "trend", "recent"]
    for reg in regimes:
        ridx = [i for i, w in enumerate(windows) if win_regime[w] == reg]
        sub = ret[ridx, :]
        _, avg = pairwise_complete_corr(sub)
        # count usable name-pairs
        out["per_regime"][reg] = {
            "n_windows": len(ridx),
            "avg_pairwise_corr": None if np.isnan(avg) else round(avg, 4),
        }
    _, avg_all = pairwise_complete_corr(ret)
    out["pooled_avg_pairwise_corr"] = None if np.isnan(avg_all) else round(avg_all, 4)
    return out


def analysis_b_variance(pnl, notl, ret, names, windows, win_regime):
    """Variance decomposition: each name's marginal contribution to the variance of
    the EQUAL-WEIGHT and ACTUAL-NOTIONAL-WEIGHT portfolio window-PnL. Spotlight the
    names that dominate variance in the negative-PnL windows of each regime."""
    out = {}
    # per-name window PnL (0 where the name didn't trade — for portfolio aggregation
    # a non-trade contributes 0 P&L, which is the correct portfolio semantics).
    P = np.nan_to_num(pnl, nan=0.0)  # windows x names
    N = np.nan_to_num(notl, nan=0.0)

    def mcr(weights_per_window):
        """Marginal contribution to risk of the portfolio return series.
        weights_per_window: windows x names (row-normalized). Portfolio return per
        window = sum_n w[t,n] * ret[t,n]. We decompose Var(port_ret) via covariance
        of the weighted per-name contributions."""
        Wret = np.where(np.isnan(ret), 0.0, ret) * weights_per_window
        port = Wret.sum(axis=1)
        var_port = np.var(port)
        # contribution of name n = Cov(Wret[:,n], port)
        contrib = np.array([np.cov(Wret[:, n], port)[0, 1] for n in range(len(names))])
        share = contrib / var_port if var_port > 0 else np.full(len(names), np.nan)
        return var_port, share

    # equal weight across names that traded that window
    traded = (~np.isnan(pnl)).astype(float)
    eq_w = np.where(traded.sum(axis=1, keepdims=True) > 0, traded / traded.sum(axis=1, keepdims=True), 0.0)
    var_eq, share_eq = mcr(eq_w)
    # actual notional weight
    act_w = np.where(N.sum(axis=1, keepdims=True) > 0, N / N.sum(axis=1, keepdims=True), 0.0)
    var_act, share_act = mcr(act_w)

    out["variance_share_equal_weight"] = {
        names[i]: round(float(share_eq[i]), 4) for i in range(len(names)) if not np.isnan(share_eq[i])
    }
    out["variance_share_actual_weight"] = {
        names[i]: round(float(share_act[i]), 4) for i in range(len(names)) if not np.isnan(share_act[i])
    }

    # spotlight: in each regime, which name lost the most $ (dominant drag)
    spot = {}
    for reg in ["crisis", "trend", "recent"]:
        ridx = [i for i, w in enumerate(windows) if win_regime[w] == reg]
        name_pnl = P[ridx, :].sum(axis=0)
        order = np.argsort(name_pnl)  # most negative first
        spot[reg] = {
            "total_pnl": round(float(P[ridx, :].sum()), 2),
            "worst_names": [
                {"name": names[i], "pnl": round(float(name_pnl[i]), 2)} for i in order[:3]
            ],
            "best_names": [
                {"name": names[i], "pnl": round(float(name_pnl[i]), 2)} for i in order[::-1][:3]
            ],
        }
    out["regime_pnl_spotlight"] = spot
    return out


def analysis_c_kelly(rows, names):
    """Per name per regime: mean(ret), var(ret), n_trades, Kelly f = mean/var, sign."""
    buckets = defaultdict(list)  # (regime,name) -> [ret,...]
    for r in rows:
        buckets[(r["regime"], r["symbol"])].append(r["ret"])
    out = {}
    for reg in ["crisis", "trend", "recent"]:
        rows_out = {}
        for n in names:
            rs = np.array(buckets.get((reg, n), []))
            if len(rs) == 0:
                continue
            mean = float(np.mean(rs))
            var = float(np.var(rs, ddof=1)) if len(rs) > 1 else float("nan")
            kelly = mean / var if var and not np.isnan(var) and var > 0 else float("nan")
            rows_out[n] = {
                "n": int(len(rs)),
                "mean_ret": round(mean, 5),
                "var_ret": None if np.isnan(var) else round(var, 6),
                "kelly": None if np.isnan(kelly) else round(kelly, 3),
                "sign": "neg" if mean < 0 else "pos",
            }
        out[reg] = rows_out
    return out


# ---- HRP (Lopez de Prado) ----
def _corr_dist(corr):
    return np.sqrt(np.clip((1.0 - corr) / 2.0, 0, None))


def _quasi_diag(link):
    link = link.astype(int)
    sort_ix = [link[-1, 0], link[-1, 1]]
    num_items = link[-1, 3]
    while max(sort_ix) >= num_items:
        new = []
        for it in sort_ix:
            if it < num_items:
                new.append(it)
            else:
                a = link[it - num_items, 0]
                b = link[it - num_items, 1]
                new.extend([a, b])
        sort_ix = new
    return sort_ix


def _ivp(cov):
    ivp = 1.0 / np.diag(cov)
    return ivp / ivp.sum()


def _cluster_var(cov, idx):
    sub = cov[np.ix_(idx, idx)]
    w = _ivp(sub).reshape(-1, 1)
    return float((w.T @ sub @ w)[0, 0])


def hrp_weights(cov, corr):
    try:
        from scipy.cluster.hierarchy import linkage
    except Exception:
        return None
    d = _corr_dist(corr)
    # condensed distance
    from scipy.spatial.distance import squareform

    np.fill_diagonal(d, 0.0)
    link = linkage(squareform(d, checks=False), method="single")
    sort_ix = _quasi_diag(link)
    w = np.ones(len(sort_ix))
    clusters = [sort_ix]
    while clusters:
        clusters = [
            c[j:k]
            for c in clusters
            for j, k in ((0, len(c) // 2), (len(c) // 2, len(c)))
            if len(c) > 1
        ]
        for i in range(0, len(clusters), 2):
            c0, c1 = clusters[i], clusters[i + 1]
            v0, v1 = _cluster_var(cov, c0), _cluster_var(cov, c1)
            alpha = 1.0 - v0 / (v0 + v1)
            for x in c0:
                w[x] *= alpha
            for x in c1:
                w[x] *= 1 - alpha
    return w  # indexed by original name order


def paper_backtest(pnl, notl, ret, names, windows, win_regime, weight_fn, label):
    """Apply a per-regime weight scheme to per-name realized returns and compute Δ$
    vs the executed (actual-notional) baseline. Returns per-regime + pooled mean Δ.

    Scaling model: name window PnL under scheme = name_return * (total_window_notional
    * target_weight_name). Baseline = executed Σ pnl. Returns per-name are held fixed
    (paper; linear, no market impact)."""
    P = np.nan_to_num(pnl, nan=0.0)
    N = np.nan_to_num(notl, nan=0.0)
    R = np.where(np.isnan(ret), 0.0, ret)
    deltas = {"crisis": [], "trend": [], "recent": []}
    per_window = []
    for t, w in enumerate(windows):
        total_notl = N[t].sum()
        if total_notl <= 0:
            continue
        traded_mask = notl[t] > 0
        base_pnl = P[t].sum()
        tw = weight_fn(t, traded_mask, N[t])  # target weights over names (only traded names nonzero)
        if tw is None or tw.sum() <= 0:
            continue
        tw = tw / tw.sum()
        scheme_pnl = float((R[t] * (total_notl * tw)).sum())
        d = scheme_pnl - base_pnl
        deltas[win_regime[w]].append(d)
        per_window.append({"window": w, "regime": win_regime[w], "delta": round(d, 2)})
    summ = {}
    alld = []
    for reg, ds in deltas.items():
        alld.extend(ds)
        summ[reg] = {"mean_delta": round(float(np.mean(ds)), 2) if ds else None, "n": len(ds)}
    summ["pooled"] = {"mean_delta": round(float(np.mean(alld)), 2) if alld else None, "n": len(alld)}
    return {"label": label, "summary": summ, "per_window": per_window}


def main():
    rows, win_regime = load_trades()
    windows = sorted(win_regime.keys())
    names = sorted({r["symbol"] for r in rows})
    print(f"[load] {len(rows)} trades, {len(windows)} windows, {len(names)} names: {names}", file=sys.stderr)

    pnl, notl, ret = build_matrices(rows, names, windows)
    nidx = {n: i for i, n in enumerate(names)}

    a = analysis_a_correlation(ret, names, windows, win_regime)
    b = analysis_b_variance(pnl, notl, ret, names, windows, win_regime)
    c = analysis_c_kelly(rows, names)

    # ---- weight schemes for paper backtest ----
    # Kelly sign lookup per (regime,name)
    kelly_sign = {}
    for reg, d in c.items():
        for n, v in d.items():
            kelly_sign[(reg, n)] = v["kelly"]

    # Baseline = executed actual-notional book. Every scheme is scored against it.
    # w_actual reproduces it exactly (Δ==0), so it is the "no-op" for gated regimes.
    def w_actual(t, mask, Nrow):
        return Nrow.copy() if Nrow.sum() > 0 else None

    def w_inv_vol(t, mask, Nrow):
        # inverse-vol risk parity, per-name vol estimated from that name's regime bucket
        reg = win_regime[windows[t]]
        w = np.zeros(len(names))
        for i, n in enumerate(names):
            if not mask[i]:
                continue
            v = c[reg].get(n, {}).get("var_ret")
            w[i] = 1.0 / np.sqrt(v) if v and v > 0 else 0.0
        return w if w.sum() > 0 else None

    def w_kelly_cap(t, mask, Nrow):
        # in-sample lookahead ceiling: notional proportional to max(kelly,0)
        reg = win_regime[windows[t]]
        w = np.zeros(len(names))
        for i, n in enumerate(names):
            if not mask[i]:
                continue
            k = kelly_sign.get((reg, n))
            w[i] = max(k, 0.0) if k is not None else 0.0
        return w if w.sum() > 0 else Nrow.copy()

    # HRP: per-regime cov/corr from the realized-return matrix, applied in-sample
    def make_hrp_regime():
        cache = {}
        for reg in ["crisis", "trend", "recent"]:
            ridx = [i for i, w in enumerate(windows) if win_regime[w] == reg]
            sub = ret[ridx, :]
            # keep names with >=3 obs in this regime
            keep = [i for i in range(len(names)) if (~np.isnan(sub[:, i])).sum() >= 3]
            if len(keep) < 2:
                cache[reg] = None
                continue
            m = sub[:, keep]
            # fill nan with column mean for cov estimation
            col_mean = np.nanmean(m, axis=0)
            filled = np.where(np.isnan(m), col_mean, m)
            cov = np.cov(filled, rowvar=False)
            corr = np.corrcoef(filled, rowvar=False)
            corr = np.nan_to_num(corr, nan=0.0)
            np.fill_diagonal(corr, 1.0)
            w = hrp_weights(cov, corr)
            cache[reg] = (keep, w) if w is not None else None
        return cache

    hrp_cache = make_hrp_regime()

    def w_hrp(t, mask, Nrow):
        reg = win_regime[windows[t]]
        cached = hrp_cache.get(reg)
        if cached is None:
            return Nrow.copy()
        keep, hw = cached
        w = np.zeros(len(names))
        for pos, i in enumerate(keep):
            if mask[i]:
                w[i] = hw[pos]
        return w if w.sum() > 0 else Nrow.copy()

    # ---- lookahead-free Kelly-cap variants (the honest pre-reg test) ----
    # Per (regime,name) list of (window_index, per-window mean return) so we can
    # exclude the scored window (LOO) or restrict to chronologically-prior windows.
    win_name_ret = defaultdict(dict)  # (regime,name) -> {window_idx: mean_ret_that_window}
    for i, w in enumerate(windows):
        reg = win_regime[w]
        for n in names:
            r = ret[i, nidx[n]]
            if not np.isnan(r):
                win_name_ret[(reg, n)][i] = float(r)

    def kelly_sign_excluding(reg, n, exclude_idx=None, prior_to=None):
        """Sign of the name's mean return in its regime bucket, optionally leaving out
        window `exclude_idx` (LOO) or restricting to windows strictly before `prior_to`
        chronologically (expanding walk-forward)."""
        d = win_name_ret.get((reg, n), {})
        vals = []
        for idx, r in d.items():
            if exclude_idx is not None and idx == exclude_idx:
                continue
            if prior_to is not None and windows[idx] >= windows[prior_to]:
                continue
            vals.append(r)
        if not vals:
            return None  # no prior info -> undefined
        return float(np.mean(vals))

    # Kelly-sign FILTER schemes: start from ACTUAL notional, zero the names whose
    # estimated Kelly sign is negative, renormalize. This isolates the pure
    # drop-bad-edge-names effect (survivors keep their executed relative sizing).
    def w_kelly_loo(t, mask, Nrow):
        reg = win_regime[windows[t]]
        w = Nrow.copy()
        for i, n in enumerate(names):
            if not mask[i]:
                continue
            s = kelly_sign_excluding(reg, n, exclude_idx=t)
            if s is not None and s <= 0:
                w[i] = 0.0
        return w if w.sum() > 0 else Nrow.copy()

    def w_kelly_expanding(t, mask, Nrow):
        reg = win_regime[windows[t]]
        w = Nrow.copy()
        for i, n in enumerate(names):
            if not mask[i]:
                continue
            s = kelly_sign_excluding(reg, n, prior_to=t)
            if s is not None and s <= 0:  # only drop when prior evidence says negative
                w[i] = 0.0
        return w if w.sum() > 0 else Nrow.copy()

    def gate_recent(weight_fn):
        """Apply weight_fn ONLY in recent windows; actual-notional (Δ==0) elsewhere."""
        def inner(t, mask, Nrow):
            if win_regime[windows[t]] != "recent":
                return Nrow.copy()
            return weight_fn(t, mask, Nrow)
        return inner

    # Conservative floor: drop negative-Kelly names but DO NOT redistribute their
    # notional (survivors keep their executed dollar size; book shrinks). Δ here is
    # purely the avoided losses — no winner-amplification. paper_backtest normalizes
    # weights, so to express "shrink the book" we scale survivor returns by the
    # retained-notional fraction: implemented via a dedicated no-renorm path below.
    def paper_backtest_droponly(weight_keep_fn, label):
        P_ = np.nan_to_num(pnl, nan=0.0)
        N = np.nan_to_num(notl, nan=0.0)
        R_ = np.where(np.isnan(ret), 0.0, ret)
        deltas = {"crisis": [], "trend": [], "recent": []}
        per_window = []
        for t, w in enumerate(windows):
            if N[t].sum() <= 0:
                continue
            mask = notl[t] > 0
            keep = weight_keep_fn(t, mask)  # boolean keep vector
            base_pnl = P_[t].sum()
            # survivors keep executed notional; dropped names contribute 0
            scheme_pnl = float((R_[t] * (N[t] * keep)).sum())
            d = scheme_pnl - base_pnl
            deltas[win_regime[w]].append(d)
            per_window.append({"window": w, "regime": win_regime[w], "delta": round(d, 2)})
        summ = {}
        alld = []
        for reg, ds in deltas.items():
            alld.extend(ds)
            summ[reg] = {"mean_delta": round(float(np.mean(ds)), 2) if ds else None, "n": len(ds)}
        summ["pooled"] = {"mean_delta": round(float(np.mean(alld)), 2) if alld else None, "n": len(alld)}
        return {"label": label, "summary": summ, "per_window": per_window}

    def keep_expanding_recentgated(t, mask):
        keep = mask.copy()
        if win_regime[windows[t]] != "recent":
            return keep  # untouched -> Δ 0
        reg = "recent"
        for i, n in enumerate(names):
            if not mask[i]:
                continue
            s = kelly_sign_excluding(reg, n, prior_to=t)
            if s is not None and s <= 0:
                keep[i] = False
        return keep

    # Static recent-blacklist extension (the DEPLOYABLE framing: extend V240's
    # existing universe_selective blacklist {BTC,DOT,LINK} with a regime-conditional
    # recent blacklist). NOTE: the blacklist names are chosen by their recent-regime
    # pooled sign => IN-SAMPLE selection (lookahead), reported as an optimistic ceiling.
    def static_recent_blacklist(black, redistribute):
        blackset = set(black)
        P_ = np.nan_to_num(pnl, nan=0.0)
        N = np.nan_to_num(notl, nan=0.0)
        R_ = np.where(np.isnan(ret), 0.0, ret)
        deltas = {"crisis": [], "trend": [], "recent": []}
        for t, w in enumerate(windows):
            if N[t].sum() <= 0:
                continue
            base = P_[t].sum()
            if win_regime[w] != "recent":
                deltas[win_regime[w]].append(0.0)
                continue
            keep = np.array([0.0 if names[i] in blackset else 1.0 for i in range(len(names))])
            surv_notl = (N[t] * keep)
            if redistribute and surv_notl.sum() > 0:
                surv_notl = surv_notl / surv_notl.sum() * N[t].sum()
            scheme = float((R_[t] * surv_notl).sum())
            deltas["recent"].append(scheme - base)
        summ = {}
        alld = []
        for reg, ds in deltas.items():
            alld.extend(ds)
            summ[reg] = {"mean_delta": round(float(np.mean(ds)), 2) if ds else None, "n": len(ds)}
        summ["pooled"] = {"mean_delta": round(float(np.mean(alld)), 2) if alld else None, "n": len(alld)}
        return summ

    def static_allregime_blacklist(black, redistribute):
        """Drop names in EVERY regime (universe-wide blacklist extension, like the
        existing {BTC,DOT,LINK}). Names chosen by all-regime negative Kelly."""
        blackset = set(black)
        P_ = np.nan_to_num(pnl, nan=0.0)
        N = np.nan_to_num(notl, nan=0.0)
        R_ = np.where(np.isnan(ret), 0.0, ret)
        deltas = {"crisis": [], "trend": [], "recent": []}
        for t, w in enumerate(windows):
            if N[t].sum() <= 0:
                continue
            base = P_[t].sum()
            keep = np.array([0.0 if names[i] in blackset else 1.0 for i in range(len(names))])
            surv = N[t] * keep
            if redistribute and surv.sum() > 0:
                surv = surv / surv.sum() * N[t].sum()
            deltas[win_regime[w]].append(float((R_[t] * surv).sum()) - base)
        summ, alld = {}, []
        for reg, ds in deltas.items():
            alld.extend(ds)
            summ[reg] = {"mean_delta": round(float(np.mean(ds)), 2) if ds else None, "n": len(ds)}
        summ["pooled"] = {"mean_delta": round(float(np.mean(alld)), 2) if alld else None, "n": len(alld)}
        return summ

    static_all = {}
    for black in (["ADA"], ["ADA", "NEAR"], ["ADA", "ARB"], ["ADA", "NEAR", "ARB"]):
        static_all["+".join(black)] = {
            "drop_only_FLOOR": static_allregime_blacklist(black, False),
            "redistribute_CEILING": static_allregime_blacklist(black, True),
        }

    static_bl = {}
    for black in (["ADA"], ["ADA", "NEAR"], ["ADA", "NEAR", "ETH"], ["ADA", "NEAR", "ETH", "AVAX"]):
        key = "+".join(black)
        static_bl[key] = {
            "drop_only_FLOOR": static_recent_blacklist(black, redistribute=False),
            "redistribute_CEILING": static_recent_blacklist(black, redistribute=True),
        }

    baseline = paper_backtest(pnl, notl, ret, names, windows, win_regime, w_actual, "actual_notional_check")
    bt = {
        "inv_vol_risk_parity": paper_backtest(pnl, notl, ret, names, windows, win_regime, w_inv_vol, "inv_vol"),
        "kelly_cap_insample": paper_backtest(pnl, notl, ret, names, windows, win_regime, w_kelly_cap, "kelly_cap_insample"),
        "kelly_sign_LOO": paper_backtest(pnl, notl, ret, names, windows, win_regime, w_kelly_loo, "kelly_sign_LOO"),
        "kelly_sign_expanding_walkforward": paper_backtest(pnl, notl, ret, names, windows, win_regime, w_kelly_expanding, "kelly_sign_expanding_wf"),
        "hrp": paper_backtest(pnl, notl, ret, names, windows, win_regime, w_hrp, "hrp"),
        # regime-gated (recent-only) survivors — the walk-forward signal lives here
        "recentgated_kelly_LOO": paper_backtest(pnl, notl, ret, names, windows, win_regime, gate_recent(w_kelly_loo), "recentgated_kelly_LOO"),
        "recentgated_kelly_expanding_wf": paper_backtest(pnl, notl, ret, names, windows, win_regime, gate_recent(w_kelly_expanding), "recentgated_kelly_expanding_wf"),
        # conservative floor (drop-only, no redistribution) — causal, recent-gated
        "recentgated_kelly_wf_droponly_FLOOR": paper_backtest_droponly(keep_expanding_recentgated, "recentgated_kelly_wf_droponly_FLOOR"),
    }

    # ---- Kelly-sign PERSISTENCE: per name, fraction of its regime windows whose
    #      per-window mean-return sign matches the regime-pooled sign. High => the
    #      sign is stable => walk-forward exploitable. ~0.5 => noise.
    persistence = {}
    for reg in ["crisis", "trend", "recent"]:
        pr = {}
        for n in names:
            d = win_name_ret.get((reg, n), {})
            if len(d) < 3:
                continue
            pooled_sign = np.sign(np.mean(list(d.values())))
            match = np.mean([1.0 if np.sign(v) == pooled_sign else 0.0 for v in d.values()])
            pr[n] = {"pooled_sign": ("neg" if pooled_sign < 0 else "pos"), "n_windows": len(d), "sign_match_frac": round(float(match), 3)}
        persistence[reg] = pr

    # executed baseline $ per regime (reference)
    P = np.nan_to_num(pnl, nan=0.0)
    exec_pnl = {}
    for reg in ["crisis", "trend", "recent"]:
        ridx = [i for i, w in enumerate(windows) if win_regime[w] == reg]
        exec_pnl[reg] = round(float(P[ridx, :].sum()), 2)
    exec_pnl["pooled"] = round(float(P.sum()), 2)

    result = {
        "_meta": {
            "source": "V240 selective-universe confirm grid, round r1, 32 walk-forward windows",
            "universe": names,
            "methodology": "realized strategy-P&L streams (NOT raw price series); no OHLCV committed. In-sample paper Δ = optimistic upper bound.",
            "n_trades": len(rows),
            "windows_by_regime": {
                reg: sorted(w for w in windows if win_regime[w] == reg)
                for reg in ["crisis", "trend", "recent"]
            },
        },
        "executed_baseline_pnl": exec_pnl,
        "a_correlation_surface": a,
        "b_variance_decomposition": b,
        "c_kelly_by_regime": c,
        "c2_kelly_sign_persistence": persistence,
        "d_paper_backtest": bt,
        "d2_static_recent_blacklist": static_bl,
        "d3_static_allregime_blacklist": static_all,
        "sanity_gate": {
            "criteria": "recent mean Δ > +$300 AND pooled mean Δ > +$500 AND no regime worse than −$300",
            "verdict": {},
        },
    }
    for scheme, res in bt.items():
        s = res["summary"]
        rec = s["recent"]["mean_delta"]
        pool = s["pooled"]["mean_delta"]
        worst = min(v["mean_delta"] for k, v in s.items() if k != "pooled" and v["mean_delta"] is not None)
        passes = (
            rec is not None and rec > 300 and pool is not None and pool > 500 and worst >= -300
        )
        result["sanity_gate"]["verdict"][scheme] = {
            "recent_delta": rec,
            "pooled_delta": pool,
            "worst_regime_delta": round(worst, 2),
            "PASS": bool(passes),
        }

    out_path = os.path.join(
        os.path.dirname(__file__), "..", "omega", "nodes", "victoria", "training_log", "V243_PORTFOLIO_SEPARATOR.json"
    )
    out_path = os.path.abspath(out_path)
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"[write] {out_path}", file=sys.stderr)
    # also echo the key tables to stdout for the transcript
    print(json.dumps({
        "executed_baseline_pnl": exec_pnl,
        "a_correlation_surface": a,
        "b_regime_pnl_spotlight": b["regime_pnl_spotlight"],
        "b_variance_share_equal_weight": b["variance_share_equal_weight"],
        "c2_kelly_sign_persistence": persistence,
        "d_paper_backtest_summaries": {k: v["summary"] for k, v in bt.items()},
        "sanity_gate": result["sanity_gate"],
    }, indent=2))


if __name__ == "__main__":
    main()
