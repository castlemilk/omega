"""Tests for omega.core.credentials — the intelligent credential store."""

from __future__ import annotations

import os

import pytest

from omega.core.credentials import CredentialStore


@pytest.fixture()
def store() -> CredentialStore:
    """Fresh CredentialStore for each test (not the singleton)."""
    return CredentialStore(
        _cache={},
        _specs={},
        _env_file_loaded=False,
    )


# ── get() from environment ────────────────────────────────────────────────────


def test_get_from_env(store, monkeypatch):
    monkeypatch.setenv("TEST_CRED_XYZ", "secret123")
    assert store.get("TEST_CRED_XYZ") == "secret123"


def test_get_missing_returns_none(store):
    # Ensure not in environment
    os.environ.pop("__OMEGA_NO_SUCH_KEY__", None)
    assert store.get("__OMEGA_NO_SUCH_KEY__") is None


def test_get_cached_after_first_lookup(store, monkeypatch):
    monkeypatch.setenv("TEST_CRED_CACHED", "val1")
    first = store.get("TEST_CRED_CACHED")
    # Remove from env — cached value should still return
    monkeypatch.delenv("TEST_CRED_CACHED")
    second = store.get("TEST_CRED_CACHED")
    assert first == second == "val1"


# ── get() from .env file ──────────────────────────────────────────────────────


def test_get_from_env_file(store, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MY_SECRET=from_file\n")
    monkeypatch.setenv("OMEGA_ENV_FILE", str(env_file))
    # Ensure not in real env
    monkeypatch.delenv("MY_SECRET", raising=False)
    assert store.get("MY_SECRET") == "from_file"


def test_env_file_strips_quotes(store, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('QUOTED_VAL="hello world"\n')
    monkeypatch.setenv("OMEGA_ENV_FILE", str(env_file))
    monkeypatch.delenv("QUOTED_VAL", raising=False)
    assert store.get("QUOTED_VAL") == "hello world"


def test_env_var_takes_priority_over_file(store, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PRIORITY_KEY=from_file\n")
    monkeypatch.setenv("OMEGA_ENV_FILE", str(env_file))
    monkeypatch.setenv("PRIORITY_KEY", "from_env")
    assert store.get("PRIORITY_KEY") == "from_env"


def test_env_file_ignores_comments(store, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# this is a comment\nREAL_KEY=real_value\n")
    monkeypatch.setenv("OMEGA_ENV_FILE", str(env_file))
    monkeypatch.delenv("REAL_KEY", raising=False)
    assert store.get("REAL_KEY") == "real_value"


# ── register() ───────────────────────────────────────────────────────────────


def test_register_tracks_spec(store):
    store.register("MY_KEY", required=True, description="test credential")
    assert "MY_KEY" in store._specs
    spec = store._specs["MY_KEY"]
    assert spec.required is True
    assert spec.description == "test credential"


def test_register_marks_source_after_get(store, monkeypatch):
    monkeypatch.setenv("SRC_TEST_KEY", "val")
    store.register("SRC_TEST_KEY", required=False, description="source test")
    store.get("SRC_TEST_KEY")
    assert store._specs["SRC_TEST_KEY"].source == "env"


# ── status() / summary() ─────────────────────────────────────────────────────


def test_status_configured(store, monkeypatch):
    monkeypatch.setenv("STATUS_KEY", "present")
    store.register("STATUS_KEY", required=False, description="status test")
    items = store.status()
    item = next(i for i in items if i["name"] == "STATUS_KEY")
    assert item["configured"] is True
    assert item["source"] == "env"


def test_status_not_configured(store, monkeypatch):
    monkeypatch.delenv("MISSING_CRED", raising=False)
    store.register("MISSING_CRED", required=False, description="missing")
    items = store.status()
    item = next(i for i in items if i["name"] == "MISSING_CRED")
    assert item["configured"] is False
    assert item["source"] == "not found"


def test_summary_contains_key_name(store, monkeypatch):
    monkeypatch.setenv("SUMMARY_KEY", "value")
    store.register("SUMMARY_KEY", required=False, description="summary test")
    summary = store.summary()
    assert "SUMMARY_KEY" in summary


def test_summary_empty_store(store):
    assert store.summary() == "  No credentials registered"


# ── singleton smoke test ──────────────────────────────────────────────────────


def test_singleton_importable():
    from omega.core.credentials import credentials

    # The singleton exists and has the register/get interface
    assert hasattr(credentials, "register")
    assert hasattr(credentials, "get")
    assert hasattr(credentials, "status")
    assert hasattr(credentials, "summary")
