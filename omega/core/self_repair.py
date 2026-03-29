"""
omega.core.self_repair
~~~~~~~~~~~~~~~~~~~~~~
Daily self-repair loop — checks system health, analyzes error logs, and
attempts to auto-repair failed components.

Repair actions
--------------
- DB_TIMEOUT    : re-test DATABASE_URL connection (warns, does not reconnect
                  running psycopg connections — those reconnect on next call)
- SIGNAL_IMPORT : re-import failed signal modules via importlib
- CRITICAL_EVENT: detected error spike → logs a CRITICAL alert

Notification
------------
1. Always logs at CRITICAL level.
2. If env var ``OMEGA_WEBHOOK_URL`` is set, POSTs a JSON payload there
   (best-effort, silently ignored on failure).

Usage::

    loop = SelfRepairLoop()
    report = loop.check_and_repair(log_file="/var/log/omega/omega.log")
    if not report.healthy:
        print(report.to_dict())
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.core.self_repair")

# Error patterns that trigger repair actions
_ERROR_PATTERNS = [
    (re.compile(r"(database|psycopg|postgres|db)", re.IGNORECASE), "DB_TIMEOUT"),
    (re.compile(r"(signal.*(import|failed)|importerror)", re.IGNORECASE), "SIGNAL_IMPORT"),
    (re.compile(r"(critical|fatal|panic)", re.IGNORECASE), "CRITICAL_EVENT"),
]

# Signal modules we know how to re-import
_REPAIRABLE_SIGNAL_MODULES = [
    "omega.nodes.victoria.alt_data_signals",
    "omega.nodes.victoria.carry_signals",
    "omega.nodes.victoria.momentum_factor",
    "omega.nodes.victoria.market_data_signals",
    "omega.nodes.victoria.regime_detector",
    "omega.nodes.victoria.signal_generation",
]


@dataclass
class LogError:
    """A single error parsed from the log file."""

    line_number: int
    severity: str
    message: str
    error_type: str  # DB_TIMEOUT | SIGNAL_IMPORT | CRITICAL_EVENT


@dataclass
class RepairReport:
    """Result of a check_and_repair() run."""

    healthy: bool = True
    errors_found: int = 0
    repairs_attempted: int = 0
    repairs_succeeded: int = 0
    details: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "errors_found": self.errors_found,
            "repairs_attempted": self.repairs_attempted,
            "repairs_succeeded": self.repairs_succeeded,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class SelfRepairLoop:
    """
    Self-monitoring and repair loop.

    Parameters
    ----------
    skip_db:
        Skip database connectivity checks (useful in test environments).
    skip_signals:
        Skip signal module re-import checks.
    webhook_url:
        Optional URL to POST repair reports to.  Defaults to
        ``OMEGA_WEBHOOK_URL`` env var.
    """

    def __init__(
        self,
        skip_db: bool = False,
        skip_signals: bool = False,
        webhook_url: str | None = None,
    ) -> None:
        self._skip_db = skip_db
        self._skip_signals = skip_signals
        self._webhook_url = webhook_url or os.environ.get("OMEGA_WEBHOOK_URL", "")

    # ── Public API ─────────────────────────────────────────────────────────────

    def check_and_repair(
        self,
        log_file: str | None = None,
        last_n_lines: int = 1000,
    ) -> RepairReport:
        """
        Run a full check cycle and attempt repairs.

        Steps:
        1. Run StartupValidator (skip slow checks if configured).
        2. Parse ``log_file`` for recent errors.
        3. For each detected error type, attempt a repair.
        4. Notify if unhealthy.
        """
        report = RepairReport()

        # ── 1. StartupValidator ────────────────────────────────────────────────
        try:
            from omega.core.startup_validator import StartupValidator

            validator = StartupValidator(
                skip_docker=True,
                skip_db=self._skip_db,
                skip_signals=self._skip_signals,
            )
            val_report = validator.run()
            if val_report.has_errors:
                report.healthy = False
                report.errors_found += val_report.error_count
                for c in val_report.checks:
                    if c.status == "error":
                        report.details.append(f"[startup] {c.label}: {c.detail}")
            for c in val_report.checks:
                if c.status == "warn":
                    report.details.append(f"[startup_warn] {c.label}: {c.detail}")
        except Exception as exc:
            logger.warning("SelfRepairLoop: StartupValidator failed: %s", exc)

        # ── 2. Log analysis ────────────────────────────────────────────────────
        log_errors: list[LogError] = []
        if log_file:
            log_errors = self._parse_log_errors(log_file, last_n_lines)
            if log_errors:
                report.healthy = False
                report.errors_found += len(log_errors)
                error_types = set(e.error_type for e in log_errors)
                report.details.append(
                    f"[log] {len(log_errors)} errors found, types: {sorted(error_types)}"
                )

        # ── 3. Repair actions ──────────────────────────────────────────────────
        error_types_found = {e.error_type for e in log_errors}

        if "DB_TIMEOUT" in error_types_found and not self._skip_db:
            report.repairs_attempted += 1
            if self._repair_db():
                report.repairs_succeeded += 1
                report.details.append("[repair] DB connectivity restored")
            else:
                report.details.append("[repair] DB connectivity check failed")

        if "SIGNAL_IMPORT" in error_types_found and not self._skip_signals:
            report.repairs_attempted += 1
            n_fixed = self._repair_signals()
            report.repairs_succeeded += 1
            report.details.append(f"[repair] Re-imported {n_fixed} signal module(s)")

        # ── 4. Notify ──────────────────────────────────────────────────────────
        if not report.healthy:
            self._notify(report)

        return report

    # ── Log parsing ────────────────────────────────────────────────────────────

    def _parse_log_errors(
        self, log_file: str, last_n_lines: int = 1000
    ) -> list[LogError]:
        """
        Parse the last ``last_n_lines`` lines of ``log_file`` for errors.
        Returns a list of LogError objects.
        """
        path = Path(log_file)
        if not path.exists():
            return []

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            logger.warning("SelfRepairLoop: cannot read log %s: %s", log_file, exc)
            return []

        recent = lines[-last_n_lines:] if len(lines) > last_n_lines else lines
        errors: list[LogError] = []

        for i, line in enumerate(recent):
            upper = line.upper()
            severity = ""
            if " ERROR " in upper or upper.startswith("ERROR"):
                severity = "ERROR"
            elif " CRITICAL " in upper or upper.startswith("CRITICAL"):
                severity = "CRITICAL"
            else:
                continue

            error_type = "CRITICAL_EVENT"
            for pattern, etype in _ERROR_PATTERNS:
                if pattern.search(line):
                    error_type = etype
                    break

            errors.append(
                LogError(
                    line_number=len(lines) - len(recent) + i + 1,
                    severity=severity,
                    message=line.strip(),
                    error_type=error_type,
                )
            )

        return errors

    # ── Repair actions ─────────────────────────────────────────────────────────

    def _repair_db(self) -> bool:
        """
        Attempt to reconnect to the database and verify connectivity.
        Returns True if connection succeeds.
        """
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            logger.warning("SelfRepairLoop._repair_db: DATABASE_URL not set")
            return False
        try:
            import psycopg

            conn = psycopg.connect(db_url, connect_timeout=5)
            conn.close()
            logger.info("SelfRepairLoop._repair_db: DB connection OK")
            return True
        except Exception as exc:
            logger.error("SelfRepairLoop._repair_db: DB still unreachable: %s", exc)
            return False

    def _repair_signals(self) -> int:
        """
        Re-import all known signal modules to recover from import errors.
        Returns count of successfully (re-)imported modules.
        """
        fixed = 0
        for mod_path in _REPAIRABLE_SIGNAL_MODULES:
            try:
                if mod_path in sys.modules:
                    importlib.reload(sys.modules[mod_path])
                else:
                    importlib.import_module(mod_path)
                fixed += 1
            except Exception as exc:
                logger.warning(
                    "SelfRepairLoop._repair_signals: failed to re-import %s: %s",
                    mod_path,
                    exc,
                )
        logger.info(
            "SelfRepairLoop._repair_signals: fixed %d/%d modules",
            fixed,
            len(_REPAIRABLE_SIGNAL_MODULES),
        )
        return fixed

    # ── Notification ───────────────────────────────────────────────────────────

    def _notify(self, report: RepairReport) -> None:
        """
        Emit CRITICAL log and optionally POST to webhook.
        """
        logger.critical(
            "SelfRepairLoop: system unhealthy — errors_found=%d repairs=%d/%d details=%s",
            report.errors_found,
            report.repairs_succeeded,
            report.repairs_attempted,
            report.details[:3],
        )

        webhook = self._webhook_url
        if webhook:
            try:
                data = json.dumps(report.to_dict()).encode("utf-8")
                req = urllib.request.Request(
                    webhook,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
                logger.info("SelfRepairLoop: webhook notified at %s", webhook)
            except Exception as exc:
                logger.warning("SelfRepairLoop: webhook failed: %s", exc)
