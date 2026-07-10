#!/usr/bin/env python3
"""
V240 Track C — gdelt frozen-series builder (freeze-once discipline, V215/V238).

Fetches daily GDELT DOC 2.0 timeline aggregates for the five V138 query
definitions (omega/nodes/victoria/signals/geopolitical.py::_QUERIES) and
freezes them into data/frozen_series/ in the V238 schema:

  gdelt_vol_<query>.json   mode=timelinevol  — daily volume intensity
                           (fraction of global coverage matching the query;
                           0.0 = no matching coverage that day)
  gdelt_tone_<query>.json  mode=timelinetone — daily mean article tone
                           (0.0 on no-coverage days; tone and absence are
                           conflated by the API — consumers must weight tone
                           by same-day volume)

Coverage: the DOC 2.0 API serves 2017-01 → present; we freeze 2019-12-01 →
today, covering every walk_forward_manifest window (2020→2026) with the 31-bar
warmup. One API call per (query, mode) — 10 calls, ~15s apart (the API
rate-limits at 1 request / 5 s and intermittently harder; non-JSON responses
are retried with backoff).

Replay reads ONLY the frozen files (series_provider.py); this script is the
single place the network is touched. MANIFEST.json gets md5 + provenance per
file, same as scripts/v238_freeze_series.py.

Usage:
    python3 scripts/v240_freeze_gdelt.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT_DIR = ROOT / "data" / "frozen_series"
MANIFEST = OUT_DIR / "MANIFEST.json"
UA = {"User-Agent": "omega-victoria-freeze/1.0"}

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
START = "20191201000000"

# Mirror of signals/geopolitical.py::_QUERIES (kept in sync by
# tests-by-inspection; the signal module is imported to assert identity).
from omega.nodes.victoria.signals.geopolitical import _QUERIES  # noqa: E402


def _get_json(url: str, retries: int = 5) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            return json.loads(raw)
        except Exception as exc:  # includes rate-limit HTML -> JSONDecodeError
            last = exc
            wait = 60.0 * (attempt + 1)
            print(f"    retry {attempt + 1}/{retries} in {wait:.0f}s ({exc})")
            time.sleep(wait)
    raise last  # type: ignore[misc]


def _write_series(name: str, source: str, series: dict[str, float]) -> Path:
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
        "series": {d: series[d] for d in dates},
    }
    out = OUT_DIR / f"{name}.json"
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    _update_manifest(out, source)
    print(f"  {name}: {len(dates)} obs [{doc['first_date']} .. {doc['last_date']}] -> {out.name}")
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


def freeze_gdelt() -> None:
    end = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    for q_name, q_text in _QUERIES.items():
        for mode, prefix in (("timelinevol", "gdelt_vol"), ("timelinetone", "gdelt_tone")):
            if (OUT_DIR / f"{prefix}_{q_name}.json").is_file():
                print(f"skip {prefix}_{q_name} (already frozen)", flush=True)
                continue
            url = (
                f"{GDELT_BASE}?query={urllib.parse.quote(q_text)}"
                f"&mode={mode}&startdatetime={START}&enddatetime={end}&format=json"
            )
            print(f"fetch {prefix}_{q_name} ({mode})", flush=True)
            doc = _get_json(url)
            timeline = doc.get("timeline") or []
            if not timeline or not timeline[0].get("data"):
                raise RuntimeError(f"empty timeline for {q_name}/{mode}")
            series: dict[str, float] = {}
            for obs in timeline[0]["data"]:
                d = obs["date"][:8]
                iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                series[iso] = float(obs["value"])
            _write_series(
                f"{prefix}_{q_name}",
                f"api.gdeltproject.org/api/v2/doc/doc mode={mode} query={q_text!r}",
                series,
            )
            time.sleep(30.0)  # rate-limit headroom (429s observed well above 1/5s)


if __name__ == "__main__":
    freeze_gdelt()
    print("done — commit data/frozen_series/gdelt_*.json + MANIFEST.json")
