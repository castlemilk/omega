"""
omega.live_paper.feeds
~~~~~~~~~~~~~~~~~~~~~~~~
V250 — live data-feed pollers for the Victoria live-paper harness.

Design: a **live analogue of** ``SeriesProvider`` (the frozen as-of reader). Each
poller fetches the same raw upstream series the frozen store holds
(``data/frozen_series/<name>.json``) — OHLCV close, funding, fear/greed, VIX,
DXY, yields, GDELT tone — and returns it in the **identical frozen schema** so a
downstream consumer sees live and frozen as interchangeable at this seam
(LIVE_PAPER_SCOPE.md §1.2). NB: this module fetches raw series only; it drives no
strategy and touches no strategy file (§ guardrails).

Hard contracts:

- **Live pollers NEVER read a frozen path.** ``assert_live_source`` raises
  ``FrozenPathViolation`` for any ``file://`` URL or any path under
  ``config.FROZEN_ROOTS``. Every fetcher passes its resolved source through it.
- **As-of semantics** match ``SeriesProvider``: ``as_of_pick`` returns the latest
  observation date ``<= as_of``, at most ``max_stale_days`` old; older ⇒ marked
  ``stale``; before-first / after-last ⇒ ``out_of_range``.
- **Reproducibility ("stability of the past")**: ``content_md5`` hashes only the
  ``{name, unit, series}`` payload — never volatile metadata like
  ``fetched_at_utc`` — so re-fetching the same past dates yields an identical
  content hash.
- **Atomic + checksummed cache**: ``write_cache`` writes to a temp file, fsyncs,
  renames into place, and writes a ``.md5`` sidecar over the full file bytes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from omega.live_paper.config import FROZEN_ROOTS, LIVE_PAPER_OHLCV_WINDOW, LivePaperConfig

logger = logging.getLogger("omega.live_paper.feeds")

_UA = {"User-Agent": "omega-victoria-livepaper/1.0"}


class FrozenPathViolation(RuntimeError):  # noqa: N818 — "Violation" is the pre-registered contract name
    """A live poller attempted to resolve a source under a frozen path. NEVER wrap."""


def assert_live_source(source: str) -> str:
    """Guard: refuse any source that resolves to a frozen/local determinism artifact.

    Accepts an http(s) URL (returned unchanged) and rejects ``file://`` URLs or
    any local path resolving under ``config.FROZEN_ROOTS``. This is the
    LIVE_PAPER_SCOPE.md §6 "live path must never read from frozen" contract,
    enforced at the point of fetch.
    """
    s = (source or "").strip()
    lowered = s.lower()
    if lowered.startswith(("http://", "https://")):
        return s
    if lowered.startswith("file://"):
        raise FrozenPathViolation(f"live poller refused file:// source: {source!r}")
    # Any other string is treated as a local path — reject if under a frozen root.
    try:
        resolved = Path(s).resolve()
    except (OSError, ValueError) as exc:
        raise FrozenPathViolation(f"live poller refused unresolvable source: {source!r}") from exc
    for root in FROZEN_ROOTS:
        r = root.resolve()
        if resolved == r or r in resolved.parents:
            raise FrozenPathViolation(
                f"live poller refused frozen-path source {resolved} (under {r})"
            )
    raise FrozenPathViolation(
        f"live poller refused non-http local source: {source!r} (only live http(s) allowed)"
    )


# ── HTTP ────────────────────────────────────────────────────────────────────────


def _http_json(url: str, timeout: float, extra_headers: dict[str, str] | None = None) -> Any:
    assert_live_source(url)
    headers = dict(_UA)
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Series document (frozen schema mirror) ──────────────────────────────────────


def _content_md5(name: str, unit: str, series: dict[str, float]) -> str:
    """Hash of the reproducible payload only — excludes volatile metadata."""
    canonical = json.dumps(
        {"name": name, "unit": unit, "series": {k: series[k] for k in sorted(series)}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def series_doc(name: str, source: str, unit: str, series: dict[str, float]) -> dict[str, Any]:
    """Build a frozen-schema series document (matches SeriesProvider files)."""
    isos = sorted(series)
    return {
        "name": name,
        "source": source,
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "frequency": "daily",
        "first_date": isos[0] if isos else None,
        "last_date": isos[-1] if isos else None,
        "n_obs": len(isos),
        "unit": unit,
        "content_md5": _content_md5(name, unit, series),
        "series": {k: series[k] for k in isos},
    }


# ── As-of pick (SeriesProvider parity) ──────────────────────────────────────────


@dataclass
class AsOf:
    obs_date: str | None
    value: float | None
    staleness_days: int | None
    status: str  # "fresh" | "stale" | "out_of_range" | "empty"


def as_of_pick(series: dict[str, float], as_of: date, max_stale_days: int) -> AsOf:
    """Latest observation <= as_of, at most max_stale_days old (SeriesProvider parity)."""
    if not series:
        return AsOf(None, None, None, "empty")
    dates = sorted(series)
    as_of_ord = as_of.toordinal()
    picked: str | None = None
    for d in dates:
        if date.fromisoformat(d).toordinal() <= as_of_ord:
            picked = d
        else:
            break
    if picked is None:
        return AsOf(None, None, None, "out_of_range")  # as_of predates first obs
    stale = as_of_ord - date.fromisoformat(picked).toordinal()
    status = "fresh" if stale == 0 else ("stale" if stale <= max_stale_days else "out_of_range")
    return AsOf(picked, float(series[picked]), stale, status)


# ── Cache: atomic + checksummed ─────────────────────────────────────────────────


def write_cache(path: Path, doc: dict[str, Any]) -> str:
    """Atomically write ``doc`` as JSON, fsync, rename, and write a .md5 sidecar.

    Returns the md5 of the full file bytes (the cache-integrity checksum, distinct
    from the reproducibility ``content_md5`` inside the doc).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
    file_md5 = hashlib.md5(payload).hexdigest()
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic on POSIX
    path.with_suffix(path.suffix + ".md5").write_text(file_md5 + "\n")
    return file_md5


def verify_cache(path: Path) -> bool:
    """True iff the .md5 sidecar matches the file's current bytes."""
    sidecar = path.with_suffix(path.suffix + ".md5")
    if not path.is_file() or not sidecar.is_file():
        return False
    actual = hashlib.md5(path.read_bytes()).hexdigest()
    expected = sidecar.read_text().strip()
    return actual == expected


# ── Feed result ─────────────────────────────────────────────────────────────────


@dataclass
class FeedResult:
    name: str
    kind: str  # "crypto" | "macro"
    reachable: bool
    latency_ms: float
    provider_used: str
    failover: bool = False
    error: str | None = None
    doc: dict[str, Any] | None = None
    per_asof: dict[str, AsOf] = field(default_factory=dict)  # iso-date -> AsOf

    @property
    def blocked(self) -> bool:
        return not self.reachable


# ── Individual pollers ──────────────────────────────────────────────────────────
#
# Each poller returns the FULL small dated series it pulled; the smoke harness
# then applies `as_of_pick` per requested date. Pulling a short trailing window
# (rather than one point) is what makes the retrospective reproducibility check
# meaningful — past dates must be byte-stable across fetches.


def _binance_klines_close(symbol: str, timeout: float, end_ms: int, limit: int = LIVE_PAPER_OHLCV_WINDOW) -> dict[str, float]:
    url = (
        "https://api.binance.com/api/v3/klines?"
        + urllib.parse.urlencode({"symbol": symbol, "interval": "1d", "endTime": end_ms, "limit": limit})
    )
    rows = _http_json(url, timeout)
    out: dict[str, float] = {}
    for r in rows:
        d = datetime.fromtimestamp(r[0] / 1000, tz=UTC).date().isoformat()
        out[d] = float(r[4])  # close
    return out


def fetch_ohlcv(cfg: LivePaperConfig, symbol: str, as_of: date) -> FeedResult:
    """OHLCV daily-close series for one symbol (Binance klines, retrospective via endTime)."""
    # endTime = 00:00 UTC of the day AFTER as_of, so the as_of daily bar is included.
    end_ms = int(datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC).timestamp() * 1000) + 86_400_000
    name = f"ohlcv_close_{symbol.lower()}"
    t0 = time.perf_counter()
    provider = "binance"
    failover = False
    try:
        series = _binance_klines_close(symbol, cfg.http_timeout_s, end_ms)
    except Exception as exc:
        # NB: real harness would failover to Bybit/Coinbase/Kraken here; for the
        # smoke a Binance miss is itself a signal (provider weakness) so we record it.
        return FeedResult(name, "crypto", False, (time.perf_counter() - t0) * 1000, provider, error=str(exc))
    doc = series_doc(name, "binance klines 1d close (USDT quote)", "USD close", series)
    return FeedResult(name, "crypto", True, (time.perf_counter() - t0) * 1000, provider, failover, doc=doc)


def fetch_funding(cfg: LivePaperConfig, symbol: str, as_of: date) -> FeedResult:
    """Perpetual funding rate, daily mean of settlements (Binance fapi, retrospective)."""
    end_ms = int(datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC).timestamp() * 1000) + 86_400_000
    start_ms = end_ms - 12 * 86_400_000
    name = f"binance_funding_{symbol.lower()}"
    t0 = time.perf_counter()
    url = (
        "https://fapi.binance.com/fapi/v1/fundingRate?"
        + urllib.parse.urlencode({"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": 100})
    )
    try:
        rows = _http_json(url, cfg.http_timeout_s)
    except Exception as exc:
        return FeedResult(name, "crypto", False, (time.perf_counter() - t0) * 1000, "binance", error=str(exc))
    # Daily mean of the (typically 3) settlements per UTC day.
    by_day: dict[str, list[float]] = {}
    for e in rows:
        d = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=UTC).date().isoformat()
        by_day.setdefault(d, []).append(float(e["fundingRate"]))
    series = {d: sum(v) / len(v) for d, v in by_day.items()}
    doc = series_doc(name, "binance fapi fundingRate (daily mean of settlements)", "funding rate", series)
    return FeedResult(name, "crypto", True, (time.perf_counter() - t0) * 1000, "binance", doc=doc)


def fetch_fear_greed(cfg: LivePaperConfig, as_of: date) -> FeedResult:
    """Crypto Fear & Greed index (alternative.me, dated history, retrospective)."""
    name = "fng"
    t0 = time.perf_counter()
    url = "https://api.alternative.me/fng/?" + urllib.parse.urlencode({"limit": 15})
    try:
        payload = _http_json(url, cfg.http_timeout_s)
    except Exception as exc:
        return FeedResult(name, "crypto", False, (time.perf_counter() - t0) * 1000, "alternative.me", error=str(exc))
    series: dict[str, float] = {}
    for x in payload.get("data", []):
        d = datetime.fromtimestamp(int(x["timestamp"]), tz=UTC).date().isoformat()
        series[d] = float(x["value"])
    doc = series_doc(name, "alternative.me fear & greed index", "index 0-100", series)
    return FeedResult(name, "crypto", True, (time.perf_counter() - t0) * 1000, "alternative.me", doc=doc)


def _yahoo_daily_close(yahoo_symbol: str, timeout: float, days: int = 15) -> dict[str, float]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}?"
        + urllib.parse.urlencode({"interval": "1d", "range": f"{days}d"})
    )
    payload = _http_json(url, timeout, extra_headers={"User-Agent": "Mozilla/5.0"})
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out: dict[str, float] = {}
    for t, c in zip(ts, closes, strict=False):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz=UTC).date().isoformat()
        out[d] = float(c)
    return out


def _fred_series(series_id: str, timeout: float, n_obs: int = 20) -> dict[str, float]:
    """FRED observations — requires a real FRED_API_KEY (DEMO_KEY is rejected)."""
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FRED_API_KEY not set (DEMO_KEY is rejected by FRED)")
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(
        {"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": n_obs}
    )
    payload = _http_json(url, timeout)
    out: dict[str, float] = {}
    for obs in payload.get("observations", []):
        raw = obs.get("value", ".")
        if raw == ".":
            continue
        try:
            out[obs["date"]] = float(raw)
        except (ValueError, KeyError):
            continue
    return out


def fetch_vix(cfg: LivePaperConfig, as_of: date) -> FeedResult:
    """VIX daily close. FRED VIXCLS primary (needs key); Yahoo ^VIX fallback."""
    name = "fred_vixcls"
    t0 = time.perf_counter()
    provider, failover = "fred", False
    try:
        series = _fred_series("VIXCLS", cfg.http_timeout_s)
    except Exception as exc_fred:
        try:
            series = _yahoo_daily_close("^VIX", cfg.http_timeout_s)
            provider, failover = "yahoo:^VIX", True
        except Exception as exc_y:
            return FeedResult(
                name, "macro", False, (time.perf_counter() - t0) * 1000, provider,
                error=f"fred:{exc_fred} | yahoo:{exc_y}",
            )
    doc = series_doc(name, f"VIX daily close via {provider}", "index", series)
    return FeedResult(name, "macro", True, (time.perf_counter() - t0) * 1000, provider, failover, doc=doc)


def fetch_dxy(cfg: LivePaperConfig, as_of: date) -> FeedResult:
    """Dollar index daily close. FRED DTWEXBGS primary (needs key); Yahoo DX-Y.NYB fallback."""
    name = "fred_dtwexbgs"
    t0 = time.perf_counter()
    provider, failover = "fred", False
    try:
        series = _fred_series("DTWEXBGS", cfg.http_timeout_s)
    except Exception as exc_fred:
        try:
            series = _yahoo_daily_close("DX-Y.NYB", cfg.http_timeout_s)
            provider, failover = "yahoo:DX-Y.NYB", True
        except Exception as exc_y:
            return FeedResult(
                name, "macro", False, (time.perf_counter() - t0) * 1000, provider,
                error=f"fred:{exc_fred} | yahoo:{exc_y}",
            )
    doc = series_doc(name, f"dollar index daily close via {provider}", "index", series)
    return FeedResult(name, "macro", True, (time.perf_counter() - t0) * 1000, provider, failover, doc=doc)


def fetch_yield_curve(cfg: LivePaperConfig, as_of: date) -> FeedResult:
    """2y/10y Treasury yields (FRED DGS2/DGS10). No robust keyless fallback for DGS2."""
    name = "fred_dgs2_dgs10"
    t0 = time.perf_counter()
    try:
        dgs2 = _fred_series("DGS2", cfg.http_timeout_s)
        dgs10 = _fred_series("DGS10", cfg.http_timeout_s)
    except Exception as exc:
        return FeedResult(name, "macro", False, (time.perf_counter() - t0) * 1000, "fred", error=str(exc))
    # Combined series = 10y-2y spread on shared dates.
    spread = {d: dgs10[d] - dgs2[d] for d in sorted(set(dgs2) & set(dgs10))}
    doc = series_doc(name, "FRED DGS10-DGS2 spread", "pct spread", spread)
    return FeedResult(name, "macro", True, (time.perf_counter() - t0) * 1000, "fred", doc=doc)


def fetch_gdelt(cfg: LivePaperConfig, as_of: date) -> FeedResult:
    """GDELT geopolitical tone (DOC 2.0). Live-only info feed; may be egress-blocked."""
    name = "gdelt_tone_geopolitical"
    t0 = time.perf_counter()
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        + urllib.parse.urlencode(
            {"query": "geopolitical", "mode": "tonechart", "format": "json", "timespan": "10d"}
        )
    )
    try:
        payload = _http_json(url, cfg.http_timeout_s)
    except Exception as exc:
        return FeedResult(name, "crypto", False, (time.perf_counter() - t0) * 1000, "gdelt", error=str(exc))
    series: dict[str, float] = {}
    # DOC tonechart bins are tone buckets, not dated; a proper daily tone series
    # needs the GKG timeline API.
    _ = payload.get("tonechart", [])
    # Record reachability; leave series shape for the full harness (V251+).
    doc = series_doc(name, "GDELT DOC 2.0 tonechart", "avg tone", series)
    return FeedResult(name, "crypto", True, (time.perf_counter() - t0) * 1000, "gdelt", doc=doc)


# ── Poller registry ─────────────────────────────────────────────────────────────

# (name, kind, callable(cfg, as_of) -> FeedResult) for the non-per-symbol feeds.
MACRO_POLLERS = (
    ("fng", "crypto", fetch_fear_greed),
    ("fred_vixcls", "macro", fetch_vix),
    ("fred_dtwexbgs", "macro", fetch_dxy),
    ("fred_dgs2_dgs10", "macro", fetch_yield_curve),
    ("gdelt_tone_geopolitical", "crypto", fetch_gdelt),
)
