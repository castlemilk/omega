"""
omega.core.training_preflight
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
StartupPreflight — validates the runtime environment before a training loop
starts.  Logs each check clearly.  Does NOT abort on failure; warns and
continues so training can proceed in a degraded-but-functional state.

Checks performed
----------------
1. DATABASE_URL — set in env and SQLite fallback reachable
2. Exchange API  — tries Binance → Coinbase → CoinGecko in order
3. Python deps   — scipy, sklearn, numpy, ccxt all importable
4. VictoriaNode  — constructable without exception

Usage
-----
    result = StartupPreflight.run()
    # result.ok     → all checks passed
    # result.warnings → list of human-readable warning strings
    # result.details  → dict[check_name, bool | str]
"""

from __future__ import annotations

import importlib
import logging
import os
import sqlite3
import tempfile
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger("omega.core.training_preflight")

# Exchange health-check URLs (lightweight endpoints, no auth needed)
_EXCHANGE_PROBES: list[tuple[str, str]] = [
    ("binance", "https://api.binance.com/api/v3/ping"),
    ("coinbase", "https://api.coinbase.com/v2/time"),
    ("coingecko", "https://api.coingecko.com/api/v3/ping"),
]

_REQUIRED_PACKAGES: list[str] = ["scipy", "sklearn", "numpy", "ccxt"]

_PROBE_TIMEOUT_S: float = 5.0


@dataclass
class PreflightResult:
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)

    def _warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.ok = False
        logger.warning("PREFLIGHT WARN: %s", msg)

    def _info(self, msg: str) -> None:
        logger.info("PREFLIGHT  OK : %s", msg)


class StartupPreflight:
    """Run all preflight checks and return a PreflightResult."""

    @classmethod
    def run(cls) -> PreflightResult:
        result = PreflightResult()
        logger.info("=" * 60)
        logger.info("PREFLIGHT CHECKS — validating runtime environment")
        logger.info("=" * 60)

        cls._check_database(result)
        cls._check_exchange(result)
        cls._check_python_deps(result)
        cls._check_victoria_node(result)

        if result.ok:
            logger.info("PREFLIGHT COMPLETE — all checks passed")
        else:
            logger.warning(
                "PREFLIGHT COMPLETE — %d issue(s) found (training will continue "
                "with degraded capabilities): %s",
                len(result.warnings),
                "; ".join(result.warnings),
            )
        logger.info("=" * 60)
        return result

    # ------------------------------------------------------------------

    @staticmethod
    def _check_database(result: PreflightResult) -> None:
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            result.details["database_url_set"] = True
            result._info(f"DATABASE_URL set ({db_url[:40]}…)")
        else:
            result.details["database_url_set"] = False
            logger.info("PREFLIGHT INFO: DATABASE_URL not set — SQLite fallback will be used")

        # Verify SQLite fallback is reachable (write a temp DB)
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as f:
                tmp_path = f.name
            conn = sqlite3.connect(tmp_path)
            conn.execute("CREATE TABLE _preflight_test (id INTEGER PRIMARY KEY)")
            conn.close()
            os.unlink(tmp_path)
            result.details["sqlite_ok"] = True
            result._info("SQLite reachable (fallback storage operational)")
        except Exception as exc:
            result.details["sqlite_ok"] = False
            result._warn(f"SQLite not writable: {exc}")

    @staticmethod
    def _check_exchange(result: PreflightResult) -> None:
        for name, url in _EXCHANGE_PROBES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "omega-preflight/1.0"})
                with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT_S) as resp:
                    if resp.status < 400:
                        result.details["exchange_ok"] = name
                        result._info(f"Exchange API reachable: {name} ({url})")
                        return
            except Exception:
                result.details[f"exchange_{name}"] = "unreachable"
                logger.debug("PREFLIGHT: %s unreachable (%s)", name, url)

        result._warn(
            "No exchange API responded (tried Binance, Coinbase, CoinGecko). "
            "Trading signals will use stale/cached data."
        )
        result.details["exchange_ok"] = None

    @staticmethod
    def _check_python_deps(result: PreflightResult) -> None:
        missing: list[str] = []
        for pkg in _REQUIRED_PACKAGES:
            try:
                importlib.import_module(pkg)
                result.details[f"dep_{pkg}"] = True
            except ImportError:
                missing.append(pkg)
                result.details[f"dep_{pkg}"] = False

        if missing:
            result._warn(
                f"Missing Python packages: {missing}. "
                "Some signals may be unavailable. Run: pip install -r requirements.txt"
            )
        else:
            result._info(f"All required packages importable: {_REQUIRED_PACKAGES}")

    @staticmethod
    def _check_victoria_node(result: PreflightResult) -> None:
        try:
            from omega.nodes.victoria.victoria_node import VictoriaNode

            node = VictoriaNode()
            _ = node.get_state()
            result.details["victoria_node_ok"] = True
            result._info("VictoriaNode constructable and healthy")
            del node
        except Exception as exc:
            result.details["victoria_node_ok"] = False
            result._warn(f"VictoriaNode construction failed: {exc}")
