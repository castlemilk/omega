"""V262-2 — frozen-corpus loaders (LOCKED per V262-2.md §2/§3).

Two responsibilities, both read-only:

1. **1h OHLCV** from ``data/frozen_series/binance_intraday/{SYM}/1h/{YYYY-MM}.json.gz``
   — the V262 corpus, after the V262-2/P0 microsecond re-freeze.
2. **Daily/8h auxiliary feeds** from ``data/frozen_series/*.json`` (``{date: value}``),
   forward-filled onto the 1h grid at the source cadence.

### The forward-fill rule (V262-2.md §3a, no look-ahead)

A daily observation dated *D* becomes in force at ``D+1 00:00Z`` and stays in force
until superseded. A bar inside day *D* therefore sees day *D−1*'s value at the
newest — never day *D*'s, which would not have been published yet.

### The coverage fence

``ffill_onto`` never extends a feed past its own last observation: bars beyond
``last_date + 1 day`` get ``None``, not a stale carry. Combined with the
all-or-nothing composite fence in ``signals.py``, that means the corpus tail
simply carries no composite once the earliest auxiliary feed is exhausted.

### Unit hardening

``load_ohlcv`` asserts every ``open_time_ms`` is milliseconds and inside its own
month — the exact defect V262-2/P0 fixed. A regressed corpus fails loudly here
rather than silently dropping an era (which is how the defect survived F4).
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERIES_DIR = ROOT / "data" / "frozen_series"
INTRADAY_DIR = SERIES_DIR / "binance_intraday"

_HOUR_MS = 3_600_000
# Any epoch >= 1e14 cannot be milliseconds (1e14 ms = year 5138); it is the
# microsecond defect V262-2/P0 corrected. Mirrors _US_CUTOFF in the freeze script.
_US_CUTOFF = 10**14


class CorpusUnitError(ValueError):
    """The frozen corpus carries a bar outside its own month (unit regression)."""


def _month_bounds_ms(month: str) -> tuple[int, int]:
    y, m = (int(x) for x in month.split("-"))
    lo = int(datetime(y, m, 1, tzinfo=UTC).timestamp() * 1000)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return lo, int(datetime(ny, nm, 1, tzinfo=UTC).timestamp() * 1000)


def bar_date(open_ms: int) -> str:
    """UTC ``YYYY-MM-DD`` of a bar's open."""
    return datetime.fromtimestamp(open_ms / 1000.0, UTC).strftime("%Y-%m-%d")


class IntradayLoader:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        base = Path(data_dir) if data_dir is not None else SERIES_DIR
        self._series_dir = base
        self._intraday_dir = base / "binance_intraday"
        self._feed_cache: dict[str, dict[str, float]] = {}
        self.missing_feeds: set[str] = set()

    # ---------------- 1h OHLCV ----------------
    def months(self, symbol: str, interval: str = "1h") -> list[str]:
        d = self._intraday_dir / symbol / interval
        return sorted(p.name[: -len(".json.gz")] for p in d.glob("*.json.gz"))

    def load_ohlcv(
        self, symbol: str, interval: str = "1h"
    ) -> tuple[list[int], dict[str, list[float]]]:
        """Return (open_ms list, {"close": [...], "volume": [...]}) over the full history.

        Bars are strictly increasing in time. Months are concatenated in calendar
        order; genuine exchange outages leave real holes, which callers must respect
        (``sim.py`` requires bar contiguity, never index adjacency).
        """
        times: list[int] = []
        close: list[float] = []
        volume: list[float] = []
        for month in self.months(symbol, interval):
            path = self._intraday_dir / symbol / interval / f"{month}.json.gz"
            doc = json.loads(gzip.decompress(path.read_bytes()))
            lo, hi = _month_bounds_ms(month)
            for row in doc["bars"]:
                t = int(row[0])
                if t >= _US_CUTOFF or not (lo <= t < hi):
                    raise CorpusUnitError(
                        f"{symbol}/{interval}/{month}: open_time {t} outside its month "
                        f"[{lo},{hi}) — the V262-2/P0 microsecond defect has regressed."
                    )
                times.append(t)
                close.append(float(row[4]))
                volume.append(float(row[5]))
        for i in range(len(times) - 1):
            if times[i + 1] <= times[i]:
                raise CorpusUnitError(f"{symbol}/{interval}: non-monotonic at index {i}")
        return times, {"close": close, "volume": volume}

    # ---------------- auxiliary daily feeds ----------------
    def load_feed(self, name: str) -> dict[str, float]:
        """``{YYYY-MM-DD: value}`` for a frozen ``data/frozen_series/{name}.json`` feed.

        A feed with **no frozen file at all** returns ``{}`` and is recorded in
        ``missing_feeds``. That is not swallowed error-handling: ``ffill_onto({})``
        yields ``None`` at every bar, so the all-or-nothing composite fence drops the
        affected symbol entirely and the scorer reports it as feed-blocked. The
        alternative — substituting a neutral 0.0 — would fabricate a signal value, the
        exact failure mode the V235 seam lesson and the V221 epsilon lesson both warn
        against.
        """
        if name not in self._feed_cache:
            path = self._series_dir / f"{name}.json"
            if not path.exists():
                self.missing_feeds.add(name)
                self._feed_cache[name] = {}
            else:
                doc = json.loads(path.read_text())
                self._feed_cache[name] = {
                    str(k): float(v) for k, v in doc["series"].items() if v is not None
                }
        return self._feed_cache[name]

    def ffill_onto(self, feed: dict[str, float], bar_times: list[int]) -> list[float | None]:
        """Forward-fill a daily feed onto 1h bars, with a strict 1-day publication lag.

        The value in force at a bar is the newest observation dated **strictly before
        the bar's own UTC date** (V262-2.md §3a). Returns ``None`` before the feed's
        first usable date and after ``last_date + 1 day`` — never a stale carry past
        the end of coverage.
        """
        if not feed:
            return [None] * len(bar_times)
        dates = sorted(feed)
        last_d = date.fromisoformat(dates[-1])
        out: list[float | None] = []
        # Pointer walks forward with the bars; bar_times is monotonic so this is O(n+m).
        ptr = -1
        n = len(dates)
        for t in bar_times:
            bd = date.fromisoformat(bar_date(t))
            # advance while the NEXT observation is still strictly before this bar's date
            while ptr + 1 < n and date.fromisoformat(dates[ptr + 1]) < bd:
                ptr += 1
            if ptr < 0 or bd > last_d + timedelta(days=1):
                out.append(None)
            else:
                out.append(feed[dates[ptr]])
        return out
