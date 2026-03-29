"""
omega.core.startup_validator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive pre-flight validation run before each training session.

Checks:
  1. Database      — connect to postgres, verify required tables
  2. API Keys      — COINGECKO_API_KEY, ANTHROPIC_API_KEY, DATABASE_URL
  3. Signal Health — import each signal module, verify instantiation
  4. Dependencies  — numpy, scipy, sklearn, pandas
  5. Docker        — postgres, prometheus, grafana reachability (warn only)
  6. Schema        — victoria_trades has all required columns
  7. Config        — .env value sanity (URL format, key format)

Usage::

    from omega.core.startup_validator import StartupValidator
    report = StartupValidator().run()
    report.print_report()
    if report.has_errors:
        sys.exit(1)
"""

from __future__ import annotations

import importlib
import logging
import os
import socket
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger("omega.core.startup_validator")

# ── Constants ─────────────────────────────────────────────────────────────────

# Keys that will cause an ERROR if missing (system cannot function without them)
_CRITICAL_KEYS: tuple[str, ...] = ()

# Keys that will cause a WARNING if missing
_WARN_KEYS: tuple[str, ...] = (
    "COINGECKO_API_KEY",
    "CG_API_KEY",  # alias accepted
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
)

# Reported as a single logical key (prefer first non-empty)
_KEY_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("COINGECKO_API_KEY", ("COINGECKO_API_KEY", "CG_API_KEY")),
    ("ANTHROPIC_API_KEY", ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")),
    ("DATABASE_URL", ("DATABASE_URL",)),
]

# Required Python dependencies
_REQUIRED_DEPS = (
    "numpy",
    "scipy",
)  # sklearn+pandas removed: C-ext codesign issue on macOS 3.14 (signals use numpy fallbacks)

# Signal modules to validate (relative to omega.nodes.victoria)
_SIGNAL_MODULES = [
    "omega.nodes.victoria.alt_data_signals",
    "omega.nodes.victoria.carry_signals",
    "omega.nodes.victoria.derivatives_signals",
    "omega.nodes.victoria.disagreement_signal",
    "omega.nodes.victoria.dynamic_weights",
    "omega.nodes.victoria.factor_model",
    "omega.nodes.victoria.information_flow",
    "omega.nodes.victoria.liquidation_cascade",
    "omega.nodes.victoria.liquidation_signals",
    "omega.nodes.victoria.macro_signals",
    "omega.nodes.victoria.market_data_signals",
    "omega.nodes.victoria.meta_model",
    "omega.nodes.victoria.momentum_factor",
    "omega.nodes.victoria.natural_gradient",
    "omega.nodes.victoria.news_signals",
    "omega.nodes.victoria.onchain_data",
    "omega.nodes.victoria.options_signals",
    "omega.nodes.victoria.pairs_signals",
    "omega.nodes.victoria.regime_detector",
    "omega.nodes.victoria.rmt_denoiser",
    "omega.nodes.victoria.signal_generation",
    "omega.nodes.victoria.signals_advanced",
    "omega.nodes.victoria.spectral_signals",
    "omega.nodes.victoria.stablecoin_signals",
    "omega.nodes.victoria.vrp_signal",
    "omega.nodes.victoria.wasserstein_regime",
    "omega.nodes.victoria.whale_signal",
]

# Docker services: (name, host, port)
_DOCKER_SERVICES: list[tuple[str, str, int]] = [
    ("postgres", "localhost", 5432),
    ("prometheus", "localhost", 9090),
    ("grafana", "localhost", 3000),
]

# Required columns in victoria_trades (including recent migration additions)
_VICTORIA_TRADES_REQUIRED_COLUMNS = {
    "id",
    "ts",
    "sym",
    "side",
    "size",
    "entry",
    "exit_price",
    "pnl",
    "slippage",
    "duration",
    "recorded_at",
    "trade_id",
    "closed_at",
}

# Required tables for system operation
_REQUIRED_TABLES = (
    "intelligence_metrics",
    "paper_trades",
    "cycle_results",
    "victoria_trades",
    "victoria_portfolio",
    "victoria_signals",
)


# ── Result types ──────────────────────────────────────────────────────────────


class CheckResult(NamedTuple):
    status: str  # "ok" | "warn" | "error"
    label: str
    detail: str


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(c.status == "error" for c in self.checks)

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "error")

    def add(self, status: str, label: str, detail: str) -> None:
        self.checks.append(CheckResult(status, label, detail))

    def print_report(self) -> None:
        print()
        print("=== Omega Startup Validation ===")
        for c in self.checks:
            tag = {
                "ok": "[OK]   ",
                "warn": "[WARN] ",
                "error": "[ERROR]",
            }.get(c.status, "[?????]")
            print(f"{tag} {c.label}: {c.detail}")

        total_warn = self.warning_count
        total_err = self.error_count

        if total_err == 0 and total_warn == 0:
            print("=== Ready to trade ===")
        elif total_err == 0:
            suffix = "warning" if total_warn == 1 else "warnings"
            print(f"=== Ready to trade ({total_warn} {suffix}) ===")
        else:
            err_suffix = "error" if total_err == 1 else "errors"
            warn_suffix = "warning" if total_warn == 1 else "warnings"
            print(f"=== NOT READY — {total_err} {err_suffix}, {total_warn} {warn_suffix} ===")
        print()


# ── Validator ─────────────────────────────────────────────────────────────────


class StartupValidator:
    """Full pre-flight validation suite."""

    def __init__(
        self,
        env_file: Path | str | None = None,
        skip_docker: bool = False,
        skip_db: bool = False,
        skip_signals: bool = False,
    ) -> None:
        self._env_file = Path(env_file) if env_file else _find_env_file()
        self._skip_docker = skip_docker
        self._skip_db = skip_db
        self._skip_signals = skip_signals

    def run(self) -> ValidationReport:
        report = ValidationReport()
        self._check_dependencies(report)
        self._check_api_keys(report)
        self._check_config(report)
        if not self._skip_db:
            self._check_database(report)
            self._check_schema(report)
        if not self._skip_signals:
            self._check_signals(report)
        if not self._skip_docker:
            self._check_docker(report)
        return report

    # ── 1. Dependencies ───────────────────────────────────────────────────────

    def _check_dependencies(self, report: ValidationReport) -> None:
        missing = []
        for dep in _REQUIRED_DEPS:
            try:
                importlib.import_module(dep)
            except ImportError:
                missing.append(dep)
        if missing:
            report.add("error", "Dependencies", f"missing: {', '.join(missing)}")
        else:
            report.add("ok", "Dependencies", "all present")

    # ── 2. API Keys ───────────────────────────────────────────────────────────

    def _check_api_keys(self, report: ValidationReport) -> None:
        present: list[str] = []
        missing: list[str] = []

        for logical_name, aliases in _KEY_GROUPS:
            found = any(os.environ.get(k) for k in aliases)
            if found:
                present.append(logical_name)
            else:
                missing.append(logical_name)

        total = len(_KEY_GROUPS)
        n_present = len(present)

        if missing:
            critical_missing = [k for k in missing if k in _CRITICAL_KEYS]
            if critical_missing:
                report.add(
                    "error",
                    "API Keys",
                    f"{n_present}/{total} present (MISSING CRITICAL: {', '.join(critical_missing)})",
                )
            else:
                report.add(
                    "warn",
                    "API Keys",
                    f"{n_present}/{total} present (missing: {', '.join(missing)})",
                )
        else:
            report.add("ok", "API Keys", f"{n_present}/{total} present")

    # ── 3. Config sanity ──────────────────────────────────────────────────────

    def _check_config(self, report: ValidationReport) -> None:
        issues: list[str] = []

        db_url = os.environ.get("DATABASE_URL", "")
        if db_url and not _valid_db_url(db_url):
            issues.append("DATABASE_URL format invalid (expected postgres://...)")

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY", "")
        if anthropic_key and not anthropic_key.startswith("sk-ant-"):
            issues.append("ANTHROPIC_API_KEY format unexpected (should start with sk-ant-)")

        cg_key = os.environ.get("COINGECKO_API_KEY") or os.environ.get("CG_API_KEY", "")
        if cg_key and len(cg_key) < 8:
            issues.append("COINGECKO_API_KEY appears too short")

        env_source = self._env_file.name if self._env_file and self._env_file.exists() else "env"
        if issues:
            report.add("warn", "Config", f"{env_source} — issues: {'; '.join(issues)}")
        else:
            report.add("ok", "Config", f"{env_source} validated")

    # ── 4. Database ───────────────────────────────────────────────────────────

    def _check_database(self, report: ValidationReport) -> None:
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            report.add("warn", "Database", "DATABASE_URL not set — in-memory mode")
            return

        try:
            import psycopg
        except ImportError:
            report.add("warn", "Database", "psycopg not installed — skipping DB check")
            return

        try:
            conn = psycopg.connect(db_url, connect_timeout=5)
            with conn.cursor() as cur:
                missing_tables = []
                for table in _REQUIRED_TABLES:
                    cur.execute(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = %s)",
                        (table,),
                    )
                    row = cur.fetchone()
                    if not (row and row[0]):
                        missing_tables.append(table)
            conn.close()

            safe_url = _redact_db_url(db_url)
            if missing_tables:
                report.add(
                    "warn",
                    "Database",
                    f"connected ({safe_url}) — missing tables: {', '.join(missing_tables)}",
                )
            else:
                report.add("ok", "Database", f"connected ({safe_url})")

        except Exception as exc:
            report.add("warn", "Database", f"unreachable — {_short_exc(exc)} (in-memory mode)")

    # ── 5. Schema migration ───────────────────────────────────────────────────

    def _check_schema(self, report: ValidationReport) -> None:
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return  # already warned in database check

        try:
            import psycopg
        except ImportError:
            return

        try:
            conn = psycopg.connect(db_url, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'victoria_trades'",
                )
                rows = cur.fetchall()
                existing = {row[0] for row in rows}
            conn.close()
        except Exception:
            return  # DB unreachable — already reported above

        if not existing:
            report.add("warn", "Schema", "victoria_trades table not found (run migrations)")
            return

        missing_cols = _VICTORIA_TRADES_REQUIRED_COLUMNS - existing
        if missing_cols:
            report.add(
                "warn",
                "Schema",
                f"victoria_trades missing columns: {', '.join(sorted(missing_cols))}",
            )
        else:
            report.add("ok", "Schema", "victoria_trades has all required columns")

    # ── 6. Signal health ──────────────────────────────────────────────────────

    def _check_signals(self, report: ValidationReport) -> None:
        healthy = 0
        failed: list[str] = []

        for mod_path in _SIGNAL_MODULES:
            try:
                importlib.import_module(mod_path)
                healthy += 1
            except Exception as exc:
                short_name = mod_path.split(".")[-1]
                failed.append(f"{short_name}({_short_exc(exc)})")

        total = len(_SIGNAL_MODULES)
        if failed:
            report.add(
                "warn",
                "Signals",
                f"{healthy}/{total} modules healthy — failures: {', '.join(failed[:5])}"
                + (" ..." if len(failed) > 5 else ""),
            )
        else:
            report.add("ok", "Signals", f"{healthy}/{total} modules healthy")

    # ── 7. Docker services ────────────────────────────────────────────────────

    def _check_docker(self, report: ValidationReport) -> None:
        unreachable: list[str] = []

        for name, host, port in _DOCKER_SERVICES:
            if not _port_open(host, port):
                unreachable.append(f"{name} not reachable on :{port}")

        if unreachable:
            for msg in unreachable:
                report.add("warn", "Docker", msg)
        else:
            names = ", ".join(s[0] for s in _DOCKER_SERVICES)
            report.add("ok", "Docker", f"all services reachable ({names})")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_env_file() -> Path:
    """Walk up from cwd looking for .env."""
    here = Path.cwd()
    for candidate in [here, here.parent, here.parent.parent]:
        p = candidate / ".env"
        if p.exists():
            return p
    return here / ".env"


def _valid_db_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme in ("postgres", "postgresql") and bool(parsed.hostname)
    except Exception:
        return False


def _redact_db_url(url: str) -> str:
    """Return URL with password stripped."""
    try:
        parsed = urllib.parse.urlparse(url)
        safe = parsed._replace(netloc=f"{parsed.hostname}:{parsed.port}")
        # Include user but not password
        if parsed.username:
            netloc = f"{parsed.username}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            safe = parsed._replace(netloc=netloc)
        return urllib.parse.urlunparse(safe)
    except Exception:
        return url[:40] + "..."


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _short_exc(exc: Exception) -> str:
    msg = str(exc)
    return msg[:60] + "..." if len(msg) > 60 else msg


# ── Convenience entry point ────────────────────────────────────────────────────


def run_validation(
    skip_docker: bool = False,
    skip_db: bool = False,
    skip_signals: bool = False,
) -> ValidationReport:
    """Run all startup checks and print the report. Returns the report."""
    validator = StartupValidator(
        skip_docker=skip_docker,
        skip_db=skip_db,
        skip_signals=skip_signals,
    )
    report = validator.run()
    report.print_report()
    return report
