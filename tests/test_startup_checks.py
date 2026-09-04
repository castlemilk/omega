"""Tests for omega.core.startup_checks."""
import os

import pytest

from omega.core.startup_checks import StartupChecker, StartupReport


def test_report_has_required_fields():
    r = StartupReport()
    assert hasattr(r, "db_ok")
    assert hasattr(r, "env_ok")
    assert hasattr(r, "api_reachable")
    assert hasattr(r, "warnings")
    assert hasattr(r, "errors")
    assert isinstance(r.warnings, list)
    assert isinstance(r.errors, list)


def test_env_check_passes_with_minimum_keys(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://x:y@localhost/db")
    checker = StartupChecker()
    report = StartupReport()
    checker._check_env(report)
    assert report.env_ok is True


def test_env_check_warns_missing_optional_keys(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://x:y@localhost/db")
    monkeypatch.delenv("CG_API_KEY", raising=False)
    checker = StartupChecker()
    report = StartupReport()
    checker._check_env(report)
    # Missing CG_API_KEY is a warning, not a fatal error
    assert report.env_ok is True
    assert any("CG_API_KEY" in w for w in report.warnings)


def test_env_check_warns_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    checker = StartupChecker()
    report = StartupReport()
    checker._check_env(report)
    # Missing DATABASE_URL → in-memory mode (warning, not fatal)
    assert report.env_ok is True
    assert any("DATABASE_URL" in w for w in report.warnings)


def test_run_returns_report(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://x:y@localhost/db")
    checker = StartupChecker(skip_db=True, skip_api=True)
    report = checker.run()
    assert isinstance(report, StartupReport)
    assert report.env_ok is True
