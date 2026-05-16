"""Aggregate trade-level forensics across all live + snapshot v17x/v18x runs.

Usage: python3 scripts/gap_analysis.py
Output: stdout summary + docs/research/live-gap-analysis.md
"""
from __future__ import annotations

import csv
import glob
import os
import statistics
from collections import defaultdict
from datetime import datetime


def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def load_all() -> list[dict]:
    rows = []
    patterns = ["data/v17*_trades.csv", "data/v18*_trades.csv"]
    for pat in patterns:
        for path in sorted(glob.glob(pat)):
            version = os.path.basename(path).replace("_trades.csv", "")
            try:
                with open(path) as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        if not r.get("symbol"):
                            continue
                        try:
                            float(r.get("exit_price") or 0)
                            float(r.get("pnl") or 0)
                        except (ValueError, TypeError):
                            continue
                        r["_version"] = version
                        rows.append(r)
            except (OSError, csv.Error):
                continue
    return rows


def safe_float(d: dict, key: str, default: float = 0.0) -> float:
    try:
        v = d.get(key)
        return float(v) if v not in (None, "", "None") else default
    except (ValueError, TypeError):
        return default


def fmt_pct(num: int, den: int) -> str:
    return f"{num}/{den} ({num/max(1,den)*100:.0f}%)"


def report(rows: list[dict]) -> str:
    out = []
    out.append("# Gap analysis — live + snapshot v17x/v18x trades\n")
    out.append(f"Total closed trades aggregated: **{len(rows)}**\n")

    pnls = [safe_float(r, "pnl") for r in rows]
    wins = sum(1 for p in pnls if p > 0)
    total_pnl = sum(pnls)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / max(1e-9, gross_loss)
    avg = total_pnl / max(1, len(rows))
    out.append(f"- Total PnL: ${total_pnl:+,.0f}")
    out.append(f"- Win rate: {fmt_pct(wins, len(rows))}")
    out.append(f"- Profit factor: {pf:.2f}")
    out.append(f"- Average PnL per trade: ${avg:+.2f}")
    out.append("")

    # By symbol
    out.append("## By symbol\n")
    by_sym: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(safe_float(r, "pnl"))
    out.append("| Symbol | Trades | PnL | Avg | WR | PF |")
    out.append("|---|---|---|---|---|---|")
    for sym in sorted(by_sym, key=lambda s: -sum(by_sym[s])):
        ps = by_sym[sym]
        if not ps:
            continue
        w = sum(1 for p in ps if p > 0)
        gp = sum(p for p in ps if p > 0)
        gl = abs(sum(p for p in ps if p < 0))
        pf_s = gp / max(1e-9, gl)
        out.append(f"| {sym} | {len(ps)} | ${sum(ps):+,.0f} | ${sum(ps)/len(ps):+.1f} | {w/len(ps)*100:.0f}% | {pf_s:.2f} |")
    out.append("")

    # By side
    out.append("## By side\n")
    by_side: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_side[r["side"].lower()].append(safe_float(r, "pnl"))
    out.append("| Side | Trades | PnL | WR | PF |")
    out.append("|---|---|---|---|---|")
    for side, ps in by_side.items():
        w = sum(1 for p in ps if p > 0)
        gp = sum(p for p in ps if p > 0)
        gl = abs(sum(p for p in ps if p < 0))
        out.append(f"| {side} | {len(ps)} | ${sum(ps):+,.0f} | {w/len(ps)*100:.0f}% | {gp/max(1e-9,gl):.2f} |")
    out.append("")

    # By regime
    out.append("## By regime\n")
    by_reg: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_reg[r.get("regime", "unknown")].append(safe_float(r, "pnl"))
    out.append("| Regime | Trades | PnL | WR | PF |")
    out.append("|---|---|---|---|---|")
    for reg, ps in sorted(by_reg.items(), key=lambda x: -sum(x[1])):
        w = sum(1 for p in ps if p > 0)
        gp = sum(p for p in ps if p > 0)
        gl = abs(sum(p for p in ps if p < 0))
        out.append(f"| {reg} | {len(ps)} | ${sum(ps):+,.0f} | {w/len(ps)*100:.0f}% | {gp/max(1e-9,gl):.2f} |")
    out.append("")

    # By hour of day (UTC)
    out.append("## By hour of day (UTC)\n")
    by_hour: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        ts = parse_ts(r.get("timestamp", ""))
        if ts is None:
            continue
        by_hour[ts.hour].append(safe_float(r, "pnl"))
    out.append("| Hour | Trades | PnL | WR |")
    out.append("|---|---|---|---|")
    for h in sorted(by_hour):
        ps = by_hour[h]
        w = sum(1 for p in ps if p > 0)
        out.append(f"| {h:02d}:00 | {len(ps)} | ${sum(ps):+,.0f} | {w/len(ps)*100:.0f}% |")
    out.append("")

    # Hold time
    out.append("## By hold time (cycles)\n")
    holds = [int(float(r.get("hold_cycles") or 0)) for r in rows]
    by_hold: dict[str, list[float]] = defaultdict(list)
    for h, p in zip(holds, pnls):
        key = "1-2" if h <= 2 else "3-5" if h <= 5 else "6-10" if h <= 10 else "10+"
        by_hold[key].append(p)
    out.append("| Hold (cycles) | Trades | PnL | Avg | WR |")
    out.append("|---|---|---|---|---|")
    for k in ["1-2", "3-5", "6-10", "10+"]:
        ps = by_hold.get(k, [])
        if not ps:
            continue
        w = sum(1 for p in ps if p > 0)
        out.append(f"| {k} | {len(ps)} | ${sum(ps):+,.0f} | ${sum(ps)/len(ps):+.1f} | {w/len(ps)*100:.0f}% |")
    out.append("")

    # MFE / MAE asymmetry for losers
    losers = [r for r in rows if safe_float(r, "pnl") < 0]
    losers_with_mfe = [r for r in losers if safe_float(r, "mfe") > 0]
    out.append("## Loser MFE pattern (catchable with tighter trail)\n")
    out.append(f"- Total losers: {len(losers)}")
    out.append(f"- Losers that touched positive MFE before reversing: "
               f"{len(losers_with_mfe)} ({len(losers_with_mfe)/max(1,len(losers))*100:.0f}%)")
    if losers_with_mfe:
        mfes = [safe_float(r, "mfe") for r in losers_with_mfe]
        out.append(f"- Their mean MFE: ${statistics.mean(mfes):.2f}")
        out.append(f"- Their mean realized PnL: ${statistics.mean([safe_float(r,'pnl') for r in losers_with_mfe]):.2f}")
    out.append("")

    # Conviction inversion check (split by conviction bucket × regime)
    out.append("## Conviction × regime (was conviction inversion real?)\n")
    out.append("| Bucket | Regime | Trades | PnL | WR |")
    out.append("|---|---|---|---|---|")
    bucket: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        c = abs(safe_float(r, "conviction"))
        b = "low(<.15)" if c < 0.15 else "mid(.15-.25)" if c < 0.25 else "high(>=.25)"
        bucket[(b, r.get("regime", "unknown"))].append(safe_float(r, "pnl"))
    for (b, reg), ps in sorted(bucket.items()):
        if len(ps) < 5:
            continue
        w = sum(1 for p in ps if p > 0)
        out.append(f"| {b} | {reg} | {len(ps)} | ${sum(ps):+,.0f} | {w/len(ps)*100:.0f}% |")
    out.append("")

    # Per-version aggregate
    out.append("## By version (top 15 by trade count)\n")
    by_ver: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_ver[r["_version"]].append(safe_float(r, "pnl"))
    out.append("| Version | Trades | PnL | WR |")
    out.append("|---|---|---|---|")
    for ver in sorted(by_ver, key=lambda v: -len(by_ver[v]))[:15]:
        ps = by_ver[ver]
        w = sum(1 for p in ps if p > 0)
        out.append(f"| {ver} | {len(ps)} | ${sum(ps):+,.0f} | {w/len(ps)*100:.0f}% |")
    out.append("")

    return "\n".join(out)


if __name__ == "__main__":
    rows = load_all()
    text = report(rows)
    print(text)
    os.makedirs("docs/research", exist_ok=True)
    with open("docs/research/live-gap-analysis.md", "w") as f:
        f.write(text)
    print(f"\n[Wrote docs/research/live-gap-analysis.md, {len(rows)} trades aggregated]")
