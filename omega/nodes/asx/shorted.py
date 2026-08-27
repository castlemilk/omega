"""Shorted API client — ASIC short-position data for the ASX.

Source: https://shorted.com.au/docs/api (read 2026-08-27). Connect-RPC over JSON POST,
the same framework this repo already speaks.

  base    https://shorts-uiekqxovma-km.a.run.app
  auth    Authorization: Bearer <token>
  method  POST <base>/shorts.v1alpha1.ShortedStocksService/<Method>

TOKEN IS MANDATORY HERE, BY POLICY NOT BY ERROR. The published usage policy states
"Automated access requires a valid API token" and "Scraping without authentication is
prohibited". An anonymous tier exists for browser traffic, but this module is automated
access, so it refuses to issue a request without a token rather than quietly relying on
the anonymous allowance. The token is read from OMEGA_SHORTED_API_KEY and is never
logged, never written to an artifact, and never committed.

Rate limits (per the docs): free 60/min & 1,000/month; $20 tier 120/min & 10,000/month.
The monthly cap is the binding one for a backtest — 20 tickers of history is comfortable,
a daily-refreshed ASX-300 universe is not.

WHY THE TIME SERIES MATTERS: `GetStockData` is a PRIVATE endpoint and is the only one
returning history. `GetStock`/`GetTopShorts` return today's snapshot, which for a
backtest is the same point-in-time trap V287 §1 found in the yfinance metadata — usable
for live signals, useless (and actively misleading) for measuring the past.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

logger = logging.getLogger("omega.nodes.asx.shorted")

BASE_URL = "https://shorts-uiekqxovma-km.a.run.app"
SERVICE = "shorts.v1alpha1.ShortedStocksService"
USER_AGENT = "omega-asx/0.1 (+research; contact via repo owner)"

# Documented methods. `private` mirrors the docs' Public/Private split.
METHODS = {
    "GetTopShorts": {"private": False, "body": {"limit": 10, "offset": 0}},
    "GetStock": {"private": False, "body": {"productCode": "BHP"}},
    "SearchStocks": {"private": False, "body": {}},
    "GetStockDetails": {"private": False, "body": {"productCode": "BHP"}},
    "GetIndustryTreeMap": {"private": False, "body": {}},
    "GetStockData": {"private": True, "body": {"productCode": "BHP"}},
}


class ShortedAuthError(RuntimeError):
    """No API token available. Deliberate: automated access requires one."""


class ShortedRateLimitError(RuntimeError):
    """429 received and retries exhausted."""


@dataclass
class ShortedClient:
    """Minimal Connect-RPC client. Stdlib only — no new dependency."""

    token: str | None = None
    base_url: str = BASE_URL
    timeout_s: float = 30.0
    max_retries: int = 3

    def __post_init__(self) -> None:
        self.token = self.token or os.environ.get("OMEGA_SHORTED_API_KEY") or None

    def call(self, method: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise ShortedAuthError(
                "OMEGA_SHORTED_API_KEY is not set. The Shorted usage policy requires a "
                "valid API token for automated access ('Scraping without authentication "
                "is prohibited'), and GetStockData — the only endpoint returning history "
                "— is private. Mint a token at https://shorted.com.au/docs/api and export "
                "it; it is read from the environment and never persisted."
            )
        url = f"{self.base_url}/{SERVICE}/{method}"
        payload = json.dumps(body or {}).encode()
        for attempt in range(self.max_retries):
            req = request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("User-Agent", USER_AGENT)   # docs: missing UA may be blocked
            req.add_header("Authorization", f"Bearer {self.token}")
            try:
                with request.urlopen(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read().decode())
            except error.HTTPError as exc:
                if exc.code == 429:
                    wait = int(exc.headers.get("Retry-After", "60"))
                    logger.warning(
                        "shorted: 429, sleeping %ss (attempt %d/%d)",
                        wait, attempt + 1, self.max_retries,
                    )
                    time.sleep(wait)
                    continue
                # Never echo the response body verbatim — it can carry request context.
                raise RuntimeError(f"shorted {method}: HTTP {exc.code}") from None
        raise ShortedRateLimitError(f"{method}: rate limited after {self.max_retries} attempts")


def freeze_short_positions(
    product_codes: list[str],
    out_root: Path | None = None,
    client: ShortedClient | None = None,
) -> dict[str, Any]:
    """Freeze short-position history per ticker, with the V219 manifest discipline.

    Mirrors `loader.freeze_universe`: this is the ONLY function here that touches the
    network, and every downstream read goes through the frozen artifact so an experiment
    can never silently re-fetch.

    `fetched_at` is recorded per ticker because short positions are a REPORTED series —
    ASIC revises, and a series pulled today is not necessarily the series pulled last
    month. That provenance has to live in the artifact (the V282 lesson: an undeclared
    input change is indistinguishable from a result).
    """
    from omega.nodes.asx.loader import _md5

    cl = client or ShortedClient()
    root = (out_root or Path(__file__).resolve().parents[3] / "data" / "frozen_series" / "asx") / "shorts"
    root.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for code in sorted(product_codes):
        data = cl.call("GetStockData", {"productCode": code})
        path = root / f"{code}.json"
        path.write_text(
            json.dumps(
                {"productCode": code, "fetched_at": datetime.now(UTC).isoformat(),
                 "source": f"{SERVICE}/GetStockData", "payload": data},
                sort_keys=True,
            ) + "\n"
        )
        written.append(path.name)

    manifest = {
        "_note": (
            "md5 manifest of frozen Shorted short-position series. Short positions are a "
            "REPORTED and revisable series, so fetched_at is provenance, not decoration."
        ),
        "source": BASE_URL,
        "generated_at": datetime.now(UTC).isoformat(),
        "files": {n: _md5(root / n) for n in sorted(written)},
    }
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    logger.info("froze %d short series -> %s", len(written), root)
    return manifest
