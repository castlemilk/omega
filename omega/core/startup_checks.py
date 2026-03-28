"""
omega.core.startup_checks
~~~~~~~~~~~~~~~~~~~~~~~~~
Pre-flight checks run once at startup before the cycle loop begins.

Checks performed:
  1. Env — DATABASE_URL present; warns on missing optional keys.
  2. DB  — connects to Postgres, verifies key tables exist.
  3. API — checks that at least one market data provider is reachable.

Usage::

    from omega.core.startup_checks import StartupChecker
    report = StartupChecker().run()
    report.print_summary()
    if not report.ok:
        sys.exit(1)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.core.startup_checks")

# No required env keys — DATABASE_URL absence means in-memory mode (supported).
_REQUIRED_ENV: tuple[str, ...] = ()

# Optional env keys — missing triggers a warning, not failure
_OPTIONAL_ENV = (
    "DATABASE_URL",
    "CG_API_KEY",
    "FRED_API_KEY",
    "ANTHROPIC_API_KEY",
    "BINANCE_API_KEY",
)

# Tables that must exist for the system to function
_REQUIRED_TABLES = (
    "intelligence_metrics",
    "paper_trades",
    "cycle_results",
)


@dataclass
class StartupReport:
    db_ok: bool = False
    env_ok: bool = False
    api_reachable: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when there are no fatal errors (env must be valid; DB/API failures are degraded)."""
        return self.env_ok

    def print_summary(self) -> None:
        width = 62
        print("=" * width)
        print("  Omega Startup Check")
        print("=" * width)
        print(f"  Env keys       : {'OK' if self.env_ok else 'FAIL'}")
        print(f"  Database       : {'OK' if self.db_ok else 'DEGRADED (in-memory mode)'}")
        print(f"  Market data API: {'OK' if self.api_reachable else 'DEGRADED (no live prices)'}")
        if self.warnings:
            print()
            print("  Warnings:")
            for w in self.warnings:
                print(f"    !  {w}")
        if self.errors:
            print()
            print("  Errors:")
            for e in self.errors:
                print(f"    x  {e}")
        print("=" * width)


class StartupChecker:
    """Runs pre-flight checks and returns a StartupReport."""

    def __init__(
        self,
        skip_db: bool = False,
        skip_api: bool = False,
    ) -> None:
        self._skip_db = skip_db
        self._skip_api = skip_api

    def run(self) -> StartupReport:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass  # python-dotenv not installed; env must be set externally
        report = StartupReport()
        self._check_env(report)
        if not self._skip_db:
            self._check_db(report)
        if not self._skip_api:
            self._check_api(report)
        return report

    # ── internal checks (also callable independently for testing) ────────────

    def _check_env(self, report: StartupReport | None = None) -> StartupReport:
        r = report if report is not None else StartupReport()
        ok = True
        for key in _REQUIRED_ENV:
            if not os.environ.get(key):
                r.errors.append(f"Missing required env var: {key}")
                ok = False
        for key in _OPTIONAL_ENV:
            if not os.environ.get(key):
                r.warnings.append(
                    f"Optional env var not set: {key} (degraded mode for that source)"
                )
        r.env_ok = ok
        return r

    def _check_db(self, report: StartupReport) -> None:
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            report.warnings.append("DATABASE_URL not set — DB checks skipped, running in-memory")
            report.db_ok = False
            return
        try:
            import psycopg

            conn = psycopg.connect(db_url, connect_timeout=5)
            with conn.cursor() as cur:
                for table in _REQUIRED_TABLES:
                    cur.execute(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = %s)",
                        (table,),
                    )
                    row = cur.fetchone()
                    exists = row[0] if row else False
                    if not exists:
                        report.warnings.append(
                            f"Table '{table}' missing — will be created by migrations"
                        )
            conn.close()
            report.db_ok = True
            logger.info("Startup: DB connection OK")
        except Exception as exc:
            report.db_ok = False
            report.warnings.append(f"DB unreachable: {exc} — running in-memory mode")
            logger.warning("Startup: DB check failed: %s", exc)

    def _check_api(self, report: StartupReport) -> None:
        """Check that at least one market data provider responds."""
        from omega.nodes.victoria.data_providers import BinanceProvider, CoinGeckoProvider

        providers: list[Any] = [BinanceProvider(), CoinGeckoProvider()]
        reachable = False
        for p in providers:
            try:
                if p.is_available():
                    reachable = True
                    break
            except Exception:
                pass
        report.api_reachable = reachable
        if not reachable:
            report.warnings.append(
                "No market data APIs reachable — signals will use cached/fallback data"
            )
        else:
            logger.info("Startup: market data API reachable")
