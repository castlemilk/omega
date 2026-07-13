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
# V253: MATIC→POL rebrand 2024-09-10; POL is 1:1 successor, live-continuous. This is
# the FORWARD live-paper fetch universe — POL is what the daemon fetches. It does not
# touch the frozen backtest (which reads snapshot keys, not this tuple), so it is
# orthogonal to reconciliation byte-identity.
_UNIVERSE_ALL = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT", "POLUSDT",
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


# ── V252 scheduler + checkpoint config ──────────────────────────────────────────
#
# The daily UTC tick fires a few minutes after the crypto daily bar closes at
# 00:00 UTC — 04:05 UTC by default (buffer for late-arriving exchange/FRED bars).
# All three knobs are env-overridable so V253 can flip SCHEDULER_ENABLED=1 without
# a code change. Everything here is time-of-day / integer config; it never touches
# a strategy parameter.


def _parse_hms(text: str) -> tuple[int, int, int]:
    """Parse ``"HH:MM:SS"`` (or ``"HH:MM"``) → (h, m, s). Raises on malformed input."""
    parts = text.strip().split(":")
    if len(parts) == 2:
        parts = [*parts, "0"]
    if len(parts) != 3:
        raise ValueError(f"SCHEDULER_TICK_UTC must be HH:MM[:SS], got {text!r}")
    h, m, s = (int(p) for p in parts)
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError(f"SCHEDULER_TICK_UTC out of range: {text!r}")
    return h, m, s


@dataclass(frozen=True)
class SchedulerConfig:
    """Immutable config for the V252 daily UTC scheduler + crash-safe checkpoint.

    Env overrides (read at construction, NOT cached process-wide):
      - ``SCHEDULER_ENABLED``       master gate, **default OFF** (V253 flips ON).
      - ``SCHEDULER_TICK_UTC``      daily fire time, default ``"04:05:00"``.
      - ``SCHEDULER_DRIFT_ALERT_SECONDS``  drift alert threshold, default 60.
    """

    tick_utc: str = "04:05:00"
    drift_alert_seconds: float = 60.0
    # How many days of daily checkpoints to retain before pruning (SCOPE §3.6).
    checkpoint_keep_days: int = 14
    # Bound on a single sleep chunk (seconds). Re-reading the clock every chunk is
    # what makes the scheduler tolerant to NTP slew / container clock jumps: a
    # forward jump is caught within one chunk, a backward jump can't oversleep.
    max_sleep_chunk_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> SchedulerConfig:
        tick = os.environ.get("SCHEDULER_TICK_UTC", "04:05:00").strip() or "04:05:00"
        _parse_hms(tick)  # validate early — fail loud on malformed config
        drift = os.environ.get("SCHEDULER_DRIFT_ALERT_SECONDS", "").strip()
        keep = os.environ.get("SCHEDULER_CHECKPOINT_KEEP_DAYS", "").strip()
        return cls(
            tick_utc=tick,
            drift_alert_seconds=float(drift) if drift else 60.0,
            checkpoint_keep_days=int(keep) if keep else 14,
        )

    @property
    def enabled(self) -> bool:
        """Master gate. The daemon refuses to run its loop unless this is truthy."""
        return os.environ.get("SCHEDULER_ENABLED", "0").strip() not in ("", "0", "false", "False")

    @property
    def tick_hms(self) -> tuple[int, int, int]:
        return _parse_hms(self.tick_utc)


def checkpoint_dir(cfg: LivePaperConfig | None = None) -> Path:
    """Directory holding daily crash-safe checkpoints (SCOPE §3.2)."""
    base = (cfg or LivePaperConfig()).output_dir
    return base / "checkpoint"


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
