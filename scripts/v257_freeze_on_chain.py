#!/usr/bin/env python3
"""
V257 — on-chain data-acquisition freeze pipeline (freeze-once discipline).

Fetches historical per-asset on-chain series from the Coin Metrics **community**
tier (free, no API key) and freezes them into
`data/frozen_series/on_chain/{ASSET}/{metric}.json`, one JSON per series, with a
`.md5` sidecar per file and a shared `MANIFEST.json`. Mirrors
`scripts/v238_freeze_series.py` (one network pull, canonical JSON, MD5-checked,
manifest-updating). This unblocks V256 (on-chain flow primary universe) — see
`omega/nodes/victoria/training_log/V257_EXECUTION_RUNBOOK.md`.

Determinism (V257 falsifier #2 — byte-identical re-run):
  - The per-series JSON files carry **no wall-clock field**; given the same API
    response they serialize byte-identically → stable MD5. (The MANIFEST carries
    a `frozen_at_utc` for provenance and is excluded from the byte-identity diff.)
  - Values are stored as the **raw decimal strings** returned by the API — lossless
    and float-round-trip-independent.
  - Canonical JSON: sorted date keys, compact separators, PYTHONHASHSEED-independent.

Signal → Coin Metrics community metric mapping (verified via catalog-v2,
community:true, daily frequency, 2026-07-15):

  V256 signal #1  net exchange netflow       ← FlowInExNtv, FlowOutExNtv
  V256 signal #2  active-address velocity    ← AdrActCnt
  V256 signal #3  whale-cluster movement     ← SplyExNtv (exchange-held supply;
                                               accumulation/distribution proxy)
  V256 signal #4  transaction volume         ← TxTfrCnt (+ TxCnt supporting)

  (The runbook's assumed names TxTfrValNtv / SplyAct1yr are paid-tier — HTTP 403 —
   and FlowInBTC / FlowOutBTC are not valid metric ids — HTTP 400. The community
   substitutes above cover all 4 V256 signals per-asset. Documented in the manifest.)

Usage:
    python3 scripts/v257_freeze_on_chain.py \
        --symbols BTC,ETH \
        --metrics FlowInExNtv,FlowOutExNtv,AdrActCnt,SplyExNtv,TxTfrCnt,TxCnt \
        --start 2020-01-01 --end 2026-07-14 \
        --out data/frozen_series/on_chain/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
SOURCE = "coinmetrics-community"
UA = {"User-Agent": "omega-victoria-freeze/257"}
SLEEP_S = 0.15  # modest rate-limit courtesy between requests (community ~10 req/6s)
PAGE_SIZE = 10000


def _disp(p: Path) -> str:
    """Repo-relative path for logging, or absolute if outside the repo (scratch)."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)

# metric id → (output filename stem, V256 signal it feeds, unit description)
METRIC_META: dict[str, tuple[str, str, str]] = {
    "FlowInExNtv": (
        "exchange_inflow_native", "net_exchange_netflow",
        "native-unit supply flowing INTO exchanges/day (netflow = in - out)",
    ),
    "FlowOutExNtv": (
        "exchange_outflow_native", "net_exchange_netflow",
        "native-unit supply flowing OUT of exchanges/day (netflow = in - out)",
    ),
    "AdrActCnt": (
        "active_addresses", "active_address_velocity",
        "count of distinct active addresses/day (network-usage momentum)",
    ),
    "SplyExNtv": (
        "exchange_supply_native", "whale_cluster_movement",
        "native-unit supply held on exchanges (accumulation/distribution proxy)",
    ),
    "TxTfrCnt": (
        "transfer_count", "transaction_volume",
        "count of transfers/day (network usage / transaction volume)",
    ),
    "TxCnt": (
        "transaction_count", "transaction_volume",
        "count of transactions/day (supporting network-usage series)",
    ),
}


def _get(url: str, timeout: float = 120.0, retries: int = 4) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 — retry all transient failures
            last_exc = exc
            time.sleep(2.0 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def fetch_series(asset: str, metric: str, start: str, end: str) -> dict[str, str]:
    """Fetch one (asset, metric) daily series, following cursor pagination.

    Returns date(YYYY-MM-DD) -> raw decimal string value (verbatim from API).
    """
    params = {
        "assets": asset,
        "metrics": metric,
        "start_time": start,
        "end_time": end,
        "frequency": "1d",
        "page_size": str(PAGE_SIZE),
    }
    url: str | None = API + "?" + urllib.parse.urlencode(params)
    series: dict[str, str] = {}
    pages = 0
    while url:
        body = json.loads(_get(url))
        for row in body.get("data", []):
            val = row.get(metric)
            if val is None:
                continue  # metric missing for this day (rare community gap)
            date = row["time"][:10]
            series[date] = str(val)
        pages += 1
        url = body.get("next_page_url")
        time.sleep(SLEEP_S)
    if not series:
        raise SystemExit(
            f"{asset}/{metric}: empty series over {start}..{end} "
            f"({pages} page(s)) — refusing to freeze"
        )
    return series


def write_series(out_root: Path, asset: str, metric: str,
                 series: dict[str, str]) -> tuple[Path, str]:
    stem, signal, unit = METRIC_META.get(
        metric, (metric.lower(), "unmapped", "raw Coin Metrics value")
    )
    dates = sorted(series)
    doc = {
        "name": f"{asset.lower()}_{stem}",
        "asset": asset.upper(),
        "metric": metric,
        "v256_signal": signal,
        "source": SOURCE,
        "frequency": "daily",
        "unit": unit,
        "first_date": dates[0],
        "last_date": dates[-1],
        "n_obs": len(dates),
        "series": {d: series[d] for d in dates},
    }
    asset_dir = out_root / asset.upper()
    asset_dir.mkdir(parents=True, exist_ok=True)
    out = asset_dir / f"{stem}.json"
    # Canonical, deterministic serialization (no wall-clock in the hashed file).
    payload = json.dumps(doc, separators=(",", ":"), sort_keys=True) + "\n"
    out.write_text(payload)
    md5 = hashlib.md5(out.read_bytes()).hexdigest()
    (asset_dir / f"{stem}.json.md5").write_text(f"{md5}  {stem}.json\n")
    print(
        f"  {asset.upper():4} {stem:24} {len(dates):5}obs "
        f"[{dates[0]} .. {dates[-1]}] md5={md5[:8]} -> {_disp(out)}"
    )
    return out, md5


def update_manifest(out_root: Path, entries: dict[str, dict]) -> None:
    from datetime import UTC, datetime

    manifest = out_root / "MANIFEST.json"
    man = {
        "_built_by": "scripts/v257_freeze_on_chain.py",
        "_note": (
            "V257 on-chain freeze (Coin Metrics community tier). Replay reads these "
            "files only (never the network). Per-series JSON is wall-clock-free and "
            "byte-identical on re-run; frozen_at_utc below is provenance only."
        ),
        "source": SOURCE,
        "frozen_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": entries,
    }
    manifest.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
    print(f"  manifest: {len(entries)} files -> {_disp(manifest)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="V257 on-chain freeze (Coin Metrics community)")
    ap.add_argument("--symbols", default="BTC,ETH")
    ap.add_argument(
        "--metrics",
        default="FlowInExNtv,FlowOutExNtv,AdrActCnt,SplyExNtv,TxTfrCnt,TxCnt",
    )
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-07-14")
    ap.add_argument("--out", default="data/frozen_series/on_chain/")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    out_root = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    print(
        f"[v257] freeze {len(symbols)} assets x {len(metrics)} metrics "
        f"[{args.start} .. {args.end}] -> {out_root}"
    )
    entries: dict[str, dict] = {}
    for asset in symbols:
        for metric in metrics:
            series = fetch_series(asset, metric, args.start, args.end)
            path, md5 = write_series(out_root, asset, metric, series)
            stem, signal, unit = METRIC_META.get(metric, (metric.lower(), "unmapped", ""))
            entries[str(path.relative_to(out_root))] = {
                "md5": md5,
                "bytes": path.stat().st_size,
                "asset": asset,
                "metric": metric,
                "v256_signal": signal,
                "n_obs": len(series),
                "first_date": min(series),
                "last_date": max(series),
            }
    update_manifest(out_root, entries)
    print(f"[v257] done: {len(entries)} series frozen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
