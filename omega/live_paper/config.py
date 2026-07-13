"""
omega.live_paper.config
~~~~~~~~~~~~~~~~~~~~~~~~
V250 — configuration for the Victoria live-**paper** data-feed harness.

Platform-layer, project-agnostic where it can be; the universe/blacklist below
mirror the V240-selective standing baseline (blacklist {BTC,DOT,LINK} → 10 names).

Guardrails encoded here (see LIVE_PAPER_SCOPE.md §6/§7):

- ``LIVE_PAPER_ENABLED`` — master gate, **default OFF**. Nothing in this module
  performs a live fetch unless the caller explicitly enables it (the smoke
  harness sets it for its own run). This keeps the eval/backtest path byte-
  identical: the frozen determinism fences are untouched and unreachable code.
- ``FROZEN_ROOTS`` — the set of on-disk paths a *live* poller must NEVER read.
  ``feeds.assert_live_source`` raises if any fetch resolves to one of these
  (the "live path must never read from frozen" contract, LIVE_PAPER_SCOPE.md §6).
- All cache/log output is routed under ``OMEGA_AUDIT_OUTPUT_DIR`` /
  ``live_paper`` on the gamma volume — never into the git tree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ── Repo layout ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

# Paths a LIVE poller must never touch. Any resolved fetch path under one of
# these is a determinism-safety violation (frozen data leaking into the live
# path) and `feeds.assert_live_source` raises `FrozenPathViolation`.
FROZEN_ROOTS: tuple[Path, ...] = (
    DATA_DIR / "frozen_series",
    DATA_DIR / "snapshots",
    DATA_DIR / "macro_cache.db",
    DATA_DIR / "frozen_advanced_signals.json",
    DATA_DIR / "frozen_funding_cache.json",
)

# V240-selective standing universe: 13 tracked names minus blacklist {BTC,DOT,LINK}.
_UNIVERSE_ALL = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    "NEARUSDT", "SUIUSDT", "ARBUSDT",
)
_BLACKLIST = frozenset({"BTCUSDT", "DOTUSDT", "LINKUSDT"})
SELECTIVE_UNIVERSE: tuple[str, ...] = tuple(p for p in _UNIVERSE_ALL if p not in _BLACKLIST)


def _default_output_dir() -> Path:
    base = os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "").strip()
    if base:
        return Path(base) / "live_paper"
    # Fall back to a gitignored local dir if the gamma volume isn't mounted.
    return DATA_DIR / "live_paper"


@dataclass(frozen=True)
class LivePaperConfig:
    """Immutable config for one live-paper harness invocation."""

    universe: tuple[str, ...] = SELECTIVE_UNIVERSE
    initial_capital: float = 100_000.0
    cadence: str = "1d"  # daily bars — LIVE_PAPER_SCOPE.md §1.3 (fidelity with frozen)
    output_dir: Path = field(default_factory=_default_output_dir)
    # Longest tolerated as-of lookback for a daily series before it's "stale",
    # matching SeriesProvider.MAX_STALE_DAYS so live and frozen agree on staleness.
    max_stale_days: int = 7
    http_timeout_s: float = 15.0

    @property
    def enabled(self) -> bool:
        """Master gate. Live fetches only run when this is truthy."""
        return os.environ.get("LIVE_PAPER_ENABLED", "0").strip() not in ("", "0", "false", "False")

    @property
    def cache_dir(self) -> Path:
        return self.output_dir / "cache"

    @property
    def log_dir(self) -> Path:
        return self.output_dir / "logs"

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
