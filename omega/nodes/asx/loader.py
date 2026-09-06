"""ASX data layer — frozen-substrate discipline from day one.

Victoria's campaign spent four versions (V276 -> V282) discovering that an unpinned
substrate silently changes results, and V219 built the md5-manifest abort that catches
it. This module starts where Victoria ended up rather than where it began:

  * bars are FROZEN to disk and hashed, never re-fetched mid-experiment;
  * a manifest records every file, so drift aborts instead of silently biasing;
  * the universe is recorded WITH its construction date, because a universe chosen
    today and applied to history is survivorship bias (V286 §5), and that must be
    visible in the artifact rather than remembered.

METADATA NOTE (measured 2026-08-27, decisive for the architecture): the free data path
exposes **no historical** news, announcements or fundamentals for ASX tickers.
`Ticker.news` returns only ~10 recent items, `calendar` is forward-looking, and `info`
is a point-in-time snapshot of TODAY. Backtesting an announcement strategy on those
would be pure lookahead. So this loader freezes what is genuinely historical (bars,
dividends, splits) and leaves a typed seam for metadata sources that must be ACQUIRED
with real history. See `training_log/V287.md`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.nodes.asx.loader")

ROOT = Path(__file__).resolve().parents[3]
FROZEN_ROOT = ROOT / "data" / "frozen_series" / "asx"
MANIFEST_PATH = FROZEN_ROOT / "MANIFEST.json"


@dataclass
class ASXUniverse:
    """A universe, recorded with the facts that determine whether it is biased.

    `constructed_at` and `survivorship_safe` are not decoration. V286 §5 established
    that a reversion finding measured on today's large caps may be entirely a selection
    artifact, so any artifact derived from this universe must carry that flag forward.
    """

    tickers: list[str]
    label: str
    constructed_at: str
    survivorship_safe: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tickers": sorted(self.tickers),
            "label": self.label,
            "constructed_at": self.constructed_at,
            "survivorship_safe": self.survivorship_safe,
            "note": self.note,
        }


# Starter universe: liquid ASX large caps. DELIBERATELY flagged unsafe — it is
# today's index membership, which is the exact bias V286 §5 names as the main threat
# to its own headline result.
ASX20_TODAY = ASXUniverse(
    tickers=[
        "BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "WBC.AX", "ANZ.AX", "WES.AX",
        "MQG.AX", "TLS.AX", "WOW.AX", "RIO.AX", "FMG.AX", "GMG.AX", "TCL.AX",
        "WDS.AX", "ALL.AX", "REA.AX", "COL.AX", "STO.AX", "QAN.AX",
    ],
    label="asx20_today",
    constructed_at="2026-08-27",
    survivorship_safe=False,
    note=(
        "Today's large caps. Survivorship-BIASED by construction: names that fell and "
        "were delisted are absent, which manufactures a reversion signal. Use for "
        "plumbing and smoke tests only — never for a verdict. See V286_PHASE0_ASX.md §5."
    ),
)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze_universe(
    universe: ASXUniverse,
    period: str = "10y",
    out_root: Path | None = None,
) -> dict[str, Any]:
    """Fetch daily bars once and freeze them, then write a hash manifest.

    Network is touched HERE and nowhere else. Every downstream read goes through
    `load_frozen_bars`, so an experiment can never silently re-fetch and drift.
    """
    import yfinance as yf  # imported lazily: the loader must import without network deps

    root = out_root or FROZEN_ROOT
    bars_dir = root / "bars"
    bars_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for ticker in sorted(universe.tickers):
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            logger.warning("no data for %s — skipped", ticker)
            continue
        payload = {
            "ticker": ticker,
            "period": period,
            "auto_adjust": True,
            "columns": ["date", "open", "high", "low", "close", "volume"],
            "bars": [
                [
                    idx.date().isoformat(),
                    float(r["Open"]), float(r["High"]), float(r["Low"]),
                    float(r["Close"]), float(r["Volume"]),
                ]
                for idx, r in hist.iterrows()
            ],
        }
        path = bars_dir / f"{ticker.replace('.', '_')}.json"
        path.write_text(json.dumps(payload, sort_keys=True) + "\n")
        written.append(str(path.relative_to(root)))

    manifest = {
        "_note": (
            "md5 manifest of the frozen ASX substrate. Verified before any experiment; "
            "mismatch => abort rather than produce an incomparable number (the V219 rule)."
        ),
        "universe": universe.to_dict(),
        "generated_at": datetime.now(UTC).isoformat(),
        "files": {rel: _md5(root / rel) for rel in sorted(written)},
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    logger.info("froze %d tickers -> %s", len(written), root)
    return manifest


def verify_frozen_manifest(out_root: Path | None = None) -> list[str]:
    """Return the list of drifted/missing files. Empty means the substrate is intact."""
    root = out_root or FROZEN_ROOT
    mpath = root / "MANIFEST.json"
    if not mpath.is_file():
        return ["MANIFEST.json: MISSING"]
    manifest = json.loads(mpath.read_text())
    problems: list[str] = []
    for rel, want in sorted(manifest.get("files", {}).items()):
        p = root / rel
        if not p.exists():
            problems.append(f"{rel}: MISSING")
        elif _md5(p) != want:
            problems.append(f"{rel}: {_md5(p)} != {want}")
    return problems


def load_frozen_bars(
    ticker: str, out_root: Path | None = None, strict: bool = True
) -> dict[str, Any]:
    """Read one frozen ticker. `strict` verifies the manifest first (default ON).

    Strict-by-default is deliberate: Victoria's equivalent check was opt-in, and an
    undeclared substrate change cost four versions to diagnose (V282).
    """
    root = out_root or FROZEN_ROOT
    if strict:
        problems = verify_frozen_manifest(root)
        if problems:
            raise RuntimeError(
                f"ASX frozen substrate drifted from its manifest: {problems[:5]}. "
                "Re-freeze deliberately or fix the drift; do not measure on it."
            )
    path = root / "bars" / f"{ticker.replace('.', '_')}.json"
    if not path.is_file():
        raise FileNotFoundError(f"{ticker} not frozen at {path}")
    payload: dict[str, Any] = json.loads(path.read_text())
    return payload


def closes(payload: dict[str, Any]) -> list[float]:
    """Adjusted closes from a frozen payload, in date order."""
    ci = payload["columns"].index("close")
    return [float(b[ci]) for b in payload["bars"]]


def dates(payload: dict[str, Any]) -> list[str]:
    di = payload["columns"].index("date")
    return [str(b[di]) for b in payload["bars"]]
