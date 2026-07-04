#!/usr/bin/env python3
"""
V238 — frozen-series feed builder (freeze-once discipline).

Fetches the historical series that activate the six info-class signals and
freezes them into `data/frozen_series/` as committed, provenance-stamped JSON.
Every external fetch happens ONCE via this script; the replay layer
(`omega/nodes/victoria/series_provider.py`) reads only the frozen files and
never touches the network (V215 guard stays authoritative).

Sources (all verified reachable from US, 2026-07-04):
  fng        alternative.me Fear & Greed (?limit=0 → full history since 2018-02)
  fred       fredgraph.csv (keyless): VIXCLS, DTWEXBGS, DGS10, DGS2
  dvol       Deribit public/get_volatility_index_data (BTC+ETH, 1D, 2021-03+)
  stables    DefiLlama stablecoincharts/all (total stablecoin supply, daily)
  binance    data.binance.vision bulk dumps (S3 listing — NOT geo-blocked,
             unlike the API): monthly fundingRate + daily metrics (OI/taker)
             for the 13-symbol universe. Raw zips + full CSVs land on the
             gamma external volume; compact daily aggregates are committed.

Frozen file schema (one JSON per series):
  {"name": ..., "source": ..., "fetched_at_utc": ..., "frequency": "daily",
   "first_date": "YYYY-MM-DD", "last_date": ..., "n_obs": ...,
   "series": {"YYYY-MM-DD": float, ...}}

data/frozen_series/MANIFEST.json records md5 + provenance for every frozen
file; the gamma raw store gets its own MD5SUMS manifest.

Usage:
    python3 scripts/v238_freeze_series.py fng fred          # Phase A
    python3 scripts/v238_freeze_series.py binance           # Phase B (slow)
    python3 scripts/v238_freeze_series.py dvol stables      # Phase C
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import fsum
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "frozen_series"
MANIFEST = OUT_DIR / "MANIFEST.json"
GAMMA_RAW = Path("/Volumes/gamma-systems-2/omega-victoria-data/frozen_series/binance_futures")

UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    "NEARUSDT", "SUIUSDT", "ARBUSDT",
]

FRED_SERIES = ["VIXCLS", "DTWEXBGS", "DGS10", "DGS2"]

S3_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BV_DL = "https://data.binance.vision/"

UA = {"User-Agent": "omega-victoria-freeze/238"}


def _get(url: str, timeout: float = 120.0, retries: int = 3) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last_exc = exc
            time.sleep(2.0 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _write_series(name: str, source: str, series: dict[str, float], extra: dict | None = None) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted(series)
    doc = {
        "name": name,
        "source": source,
        "fetched_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "frequency": "daily",
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "n_obs": len(dates),
        **(extra or {}),
        "series": {d: series[d] for d in dates},
    }
    out = OUT_DIR / f"{name}.json"
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    _update_manifest(out, source)
    print(f"  {name}: {len(dates)} obs [{doc['first_date']} .. {doc['last_date']}] → {out.name}")
    return out


def _update_manifest(path: Path, source: str) -> None:
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {
        "_built_by": "scripts/v238_freeze_series.py",
        "_note": "freeze-once V238; replay reads these files only (never the network)",
        "files": {},
    }
    man["files"][path.name] = {
        "md5": hashlib.md5(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "source": source,
        "frozen_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    MANIFEST.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")


# ── Phase A ──────────────────────────────────────────────────────────────

def freeze_fng() -> None:
    url = "https://api.alternative.me/fng/?limit=0"
    body = json.loads(_get(url))
    series: dict[str, float] = {}
    for entry in body.get("data", []):
        try:
            d = datetime.fromtimestamp(int(entry["timestamp"]), tz=UTC).date().isoformat()
            series[d] = float(entry["value"])
        except (KeyError, ValueError, TypeError):
            continue
    if len(series) < 1000:
        raise SystemExit(f"fng: implausibly small history n={len(series)} — refusing to freeze")
    _write_series("fng", url, series)


def freeze_fred() -> None:
    # fred.stlouisfed.org TLS-fingerprints python urllib (connects then stalls);
    # curl is served normally — shell out to it for this source only.
    import subprocess

    for sid in FRED_SERIES:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
        text = subprocess.run(
            ["curl", "-sS", "--max-time", "120", url],
            capture_output=True, check=True,
        ).stdout.decode()
        series: dict[str, float] = {}
        for row in csv.DictReader(io.StringIO(text)):
            date = row.get("observation_date") or row.get("DATE")
            val = row.get(sid, "")
            if not date or val in ("", ".", None):
                continue  # FRED marks holidays/gaps as "."
            try:
                series[date] = float(val)
            except ValueError:
                continue
        if len(series) < 1000:
            raise SystemExit(f"fred {sid}: implausibly small n={len(series)}")
        _write_series(f"fred_{sid.lower()}", url, series)
        time.sleep(1.0)


# ── Phase C ──────────────────────────────────────────────────────────────

def freeze_dvol() -> None:
    for ccy in ("BTC", "ETH"):
        series: dict[str, float] = {}
        # DVOL launched 2021-03-24; paginate forward in ~2-year chunks.
        start_ms = int(datetime(2021, 3, 1, tzinfo=UTC).timestamp() * 1000)
        end_ms = int(time.time() * 1000)
        cursor = start_ms
        while cursor < end_ms:
            chunk_end = min(cursor + 730 * 86400_000, end_ms)
            url = (
                "https://www.deribit.com/api/v2/public/get_volatility_index_data"
                f"?currency={ccy}&start_timestamp={cursor}&end_timestamp={chunk_end}&resolution=1D"
            )
            body = json.loads(_get(url))
            rows = (body.get("result") or {}).get("data") or []
            for ts_ms, _o, _h, _l, close in rows:
                d = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat()
                series[d] = float(close)
            cursor = chunk_end
            time.sleep(0.5)
        if len(series) < 500:
            raise SystemExit(f"dvol {ccy}: implausibly small n={len(series)}")
        _write_series(
            f"dvol_{ccy.lower()}",
            "https://www.deribit.com/api/v2/public/get_volatility_index_data (1D close)",
            series,
            extra={"unit": "annualized IV points (e.g. 53.0 = 53%)"},
        )


def freeze_stables() -> None:
    url = "https://stablecoins.llama.fi/stablecoincharts/all"
    body = json.loads(_get(url))
    series: dict[str, float] = {}
    for row in body:
        try:
            d = datetime.fromtimestamp(int(row["date"]), tz=UTC).date().isoformat()
            total = row.get("totalCirculatingUSD") or {}
            val = float(total.get("peggedUSD") or 0.0)
            if val > 0:
                series[d] = val
        except (KeyError, ValueError, TypeError):
            continue
    if len(series) < 1000:
        raise SystemExit(f"stables: implausibly small n={len(series)}")
    _write_series("stablecoin_total_usd", url, series,
                  extra={"unit": "total stablecoin circulating USD"})


# ── Phase B ──────────────────────────────────────────────────────────────

def _s3_list(prefix: str) -> list[str]:
    """List all keys under prefix via the S3 XML listing API (paginated)."""
    keys: list[str] = []
    marker = ""
    while True:
        url = f"{S3_LIST}?prefix={prefix}"
        if marker:
            url += f"&marker={marker}"
        root = ElementTree.fromstring(_get(url))
        ns = {"s3": root.tag.split("}")[0].strip("{")}
        page = [el.text for el in root.findall(".//s3:Contents/s3:Key", ns) if el.text]
        keys.extend(k for k in page if k.endswith(".zip"))
        truncated = root.findtext("s3:IsTruncated", default="false", namespaces=ns)
        if truncated != "true" or not page:
            break
        marker = page[-1] if page[-1] else ""
        if not marker:
            break
    return keys


def _download_zips(keys: list[str], dest_root: Path) -> list[Path]:
    """Download zips (skip existing), return local paths."""
    paths: list[Path] = []

    def one(key: str) -> Path | None:
        rel = key.split("data/futures/um/", 1)[-1]
        local = dest_root / rel
        if local.exists() and local.stat().st_size > 0:
            return local
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            local.write_bytes(_get(BV_DL + key, timeout=120))
            return local
        except Exception as exc:
            print(f"    MISS {key}: {exc}", file=sys.stderr)
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {pool.submit(one, k): k for k in keys}
        for i, fut in enumerate(as_completed(futs), 1):
            p = fut.result()
            if p is not None:
                paths.append(p)
            if i % 200 == 0:
                print(f"    ... {i}/{len(keys)} fetched")
    return paths


def _read_zip_csv(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8")
            first = text.readline()
            cols = [c.strip() for c in first.split(",")]
            # Some dumps ship without a header row (first cell is numeric).
            if cols and cols[0].replace(".", "").isdigit():
                return []  # headerless variant not expected for funding/metrics
            return list(csv.DictReader(io.StringIO(first + text.read()), fieldnames=None))


def freeze_binance() -> None:
    if not GAMMA_RAW.parent.parent.exists():
        raise SystemExit(f"gamma volume not mounted: {GAMMA_RAW}")
    GAMMA_RAW.mkdir(parents=True, exist_ok=True)
    coverage: dict[str, dict] = {}

    for sym in UNIVERSE:
        print(f"  {sym}:")
        # -- monthly funding rate --------------------------------------
        fr_keys = _s3_list(f"data/futures/um/monthly/fundingRate/{sym}/")
        fr_paths = _download_zips(fr_keys, GAMMA_RAW / sym)
        daily_rates: dict[str, list[float]] = defaultdict(list)
        for p in sorted(fr_paths):
            for row in _read_zip_csv(p):
                try:
                    ts_ms = int(row["calc_time"])
                    rate = float(row["last_funding_rate"])
                except (KeyError, ValueError, TypeError):
                    continue
                d = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat()
                daily_rates[d].append(rate)
        funding = {d: fsum(v) / len(v) for d, v in daily_rates.items() if v}
        if funding:
            _write_series(
                f"binance_funding_{sym.lower()}",
                f"data.binance.vision futures/um/monthly/fundingRate/{sym} (daily mean of settlements)",
                funding,
            )
        # -- daily metrics (5-min rows → daily aggregates) --------------
        m_keys = _s3_list(f"data/futures/um/daily/metrics/{sym}/")
        m_paths = _download_zips(m_keys, GAMMA_RAW / sym)
        oi: dict[str, float] = {}
        taker: dict[str, float] = {}
        for p in sorted(m_paths):
            rows = _read_zip_csv(p)
            if not rows:
                continue
            oi_vals = []
            taker_vals = []
            day = None
            for row in rows:
                ct = (row.get("create_time") or "").strip()
                if day is None and ct:
                    day = ct[:10]
                with contextlib.suppress(KeyError, ValueError, TypeError):
                    oi_vals.append(float(row["sum_open_interest_value"]))
                with contextlib.suppress(KeyError, ValueError, TypeError):
                    taker_vals.append(float(row["sum_taker_long_short_vol_ratio"]))
            if day:
                if oi_vals:
                    oi[day] = oi_vals[-1]  # last 5-min reading = daily close OI (USD)
                if taker_vals:
                    taker[day] = fsum(taker_vals) / len(taker_vals)
        if oi:
            _write_series(
                f"binance_oi_{sym.lower()}",
                f"data.binance.vision futures/um/daily/metrics/{sym} (daily last sum_open_interest_value)",
                oi,
                extra={"unit": "USD notional open interest"},
            )
        if taker:
            _write_series(
                f"binance_taker_ratio_{sym.lower()}",
                f"data.binance.vision futures/um/daily/metrics/{sym} (daily mean sum_taker_long_short_vol_ratio)",
                taker,
            )
        coverage[sym] = {
            "funding_months": len(fr_paths), "funding_days": len(funding),
            "metrics_days_downloaded": len(m_paths), "oi_days": len(oi), "taker_days": len(taker),
        }

    # MD5 manifest of the gamma raw store
    md5_lines = []
    for p in sorted(GAMMA_RAW.rglob("*.zip")):
        md5_lines.append(f"{hashlib.md5(p.read_bytes()).hexdigest()}  {p.relative_to(GAMMA_RAW)}")
    (GAMMA_RAW / "MD5SUMS").write_text("\n".join(md5_lines) + "\n")
    (GAMMA_RAW / "COVERAGE.json").write_text(json.dumps(coverage, indent=2) + "\n")
    print(f"  gamma raw manifest: {len(md5_lines)} zips → {GAMMA_RAW / 'MD5SUMS'}")


PHASES = {
    "fng": freeze_fng,
    "fred": freeze_fred,
    "dvol": freeze_dvol,
    "stables": freeze_stables,
    "binance": freeze_binance,
}


def main() -> int:
    args = sys.argv[1:] or ["fng", "fred", "dvol", "stables", "binance"]
    for a in args:
        if a not in PHASES:
            raise SystemExit(f"unknown phase {a!r}; choose from {list(PHASES)}")
    for a in args:
        print(f"[freeze] {a}")
        PHASES[a]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
