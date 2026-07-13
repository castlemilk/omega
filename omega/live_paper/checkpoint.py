"""
omega.live_paper.checkpoint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
V252 — crash-safe checkpoint for the Victoria live-**paper** harness.

**This is the load-bearing new code of V252** (LIVE_PAPER_SCOPE.md §5.2): the
whole "leave it running for 90 days" property rests on a checkpoint that (a)
never leaves a half-written file behind and (b) refuses to load a corrupt one.

Contracts (V252 pre-reg falsifier):

- **Atomic + checksummed write.** ``save`` writes to a temp file, fsyncs, renames
  into place (atomic on POSIX), then writes a ``.md5`` sidecar over the full file
  bytes — the identical pattern the V250 feed cache uses
  (``omega.live_paper.feeds.write_cache``), reused verbatim so there is one
  audited atomic-write path, not two.
- **Fail-loud corruption detection.** ``load`` verifies the ``.md5`` sidecar; any
  mismatch raises :class:`CheckpointCorruption` — the daemon must NOT proceed on
  corrupt state (it re-derives from the last good checkpoint or refuses to start).
- **Idempotency boundary.** ``last_completed_date`` is the single source of truth
  the scheduler consults to avoid a same-day double-run after a restart.
- **Byte-stable serialization.** State is serialized with sorted keys and a fixed
  float repr, so a reload-then-resave of unchanged state is byte-identical — the
  property the crash-recovery test asserts.
- **Retention.** ``prune`` keeps the most recent N daily checkpoints (default 14
  per SCOPE §3.6) and deletes older ``{date}.json`` (+ sidecar) files.

Schema (JSON object, one file per UTC cycle date ``{date}.json``)::

    {
      "cycle_ts": "2026-07-13T04:05:00+00:00",   # UTC instant the cycle fired
      "cycle_date": "2026-07-13",                # UTC calendar date traded
      "last_completed_date": "2026-07-13",       # idempotency boundary
      "equity": 100731.98,                       # marked-to-market equity
      "realised_pnl": 731.98,
      "open_positions": [ {...}, ... ],           # PaperTradingEngine positions
      "closed_trades": [ {...}, ... ],
      "signals_state": { ... },                   # signal_ic / decay / meta blobs
      "seed_state": { ... },                      # anything needed for determinism
      "schema_version": 1
    }

NB: no strategy code imported here — this module only serializes plain dicts the
runner hands it. The engine/signal objects are (de)serialized by the runner.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

# Reuse the ONE audited atomic-write + checksum path from the V250 feed layer.
from omega.live_paper.feeds import verify_cache, write_cache

logger = logging.getLogger("omega.live_paper.checkpoint")

SCHEMA_VERSION = 1


class CheckpointCorruption(RuntimeError):  # noqa: N818 — pre-registered contract name
    """A checkpoint failed its MD5 integrity check. NEVER proceed on corrupt state."""


@dataclass
class CheckpointState:
    """Typed view of one checkpoint. Serialized as the JSON object documented above."""

    cycle_ts: str
    cycle_date: str
    last_completed_date: str
    equity: float
    realised_pnl: float
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    signals_state: dict[str, Any] = field(default_factory=dict)
    seed_state: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CheckpointState:
        return cls(
            cycle_ts=d["cycle_ts"],
            cycle_date=d["cycle_date"],
            last_completed_date=d["last_completed_date"],
            equity=float(d["equity"]),
            realised_pnl=float(d["realised_pnl"]),
            open_positions=list(d.get("open_positions", [])),
            closed_trades=list(d.get("closed_trades", [])),
            signals_state=dict(d.get("signals_state", {})),
            seed_state=dict(d.get("seed_state", {})),
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        )

    @property
    def completed_date(self) -> date:
        return date.fromisoformat(self.last_completed_date)


class Checkpoint:
    """Manages the on-disk daily checkpoint directory (crash-safe, MD5-verified)."""

    def __init__(self, directory: Path, *, keep_days: int = 14) -> None:
        self.dir = Path(directory)
        self.keep_days = int(keep_days)

    # ── paths ────────────────────────────────────────────────────────────────────

    def _path_for(self, cycle_date: str) -> Path:
        return self.dir / f"{cycle_date}.json"

    def list_checkpoints(self) -> list[Path]:
        """All ``{date}.json`` checkpoints, oldest → newest by filename date."""
        if not self.dir.is_dir():
            return []
        out: list[tuple[str, Path]] = []
        for p in self.dir.glob("*.json"):
            stem = p.stem
            try:
                date.fromisoformat(stem)  # only accept YYYY-MM-DD.json files
            except ValueError:
                continue
            out.append((stem, p))
        return [p for _, p in sorted(out)]

    def latest_path(self) -> Path | None:
        ckpts = self.list_checkpoints()
        return ckpts[-1] if ckpts else None

    # ── save (atomic + checksum) ──────────────────────────────────────────────────

    def save(self, state: CheckpointState) -> str:
        """Atomically persist ``state`` as ``{cycle_date}.json`` (+ .md5 sidecar).

        Returns the file-content MD5. Prunes stale checkpoints afterward.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(state.cycle_date)
        file_md5 = write_cache(path, state.to_dict())  # temp→fsync→os.replace→.md5
        logger.info(
            json.dumps(
                {
                    "event": "checkpoint_saved",
                    "cycle_date": state.cycle_date,
                    "path": str(path),
                    "md5": file_md5,
                    "equity": state.equity,
                },
                sort_keys=True,
            )
        )
        self.prune()
        return file_md5

    # ── load (verify or fail loud) ────────────────────────────────────────────────

    def load(self, path: Path | None = None) -> CheckpointState | None:
        """Load the latest (or a specified) checkpoint, verifying MD5.

        Returns ``None`` when no checkpoint exists (clean-start path). Raises
        :class:`CheckpointCorruption` if the file's bytes don't match its sidecar
        — the daemon must treat this as a hard failure, never silently continue.
        """
        target = path or self.latest_path()
        if target is None:
            logger.info(json.dumps({"event": "checkpoint_none", "dir": str(self.dir)}))
            return None
        if not verify_cache(target):
            raise CheckpointCorruption(
                f"checkpoint {target} failed MD5 verification (missing sidecar or byte mismatch)"
            )
        state = CheckpointState.from_dict(json.loads(target.read_bytes()))
        logger.info(
            json.dumps(
                {
                    "event": "checkpoint_loaded",
                    "path": str(target),
                    "cycle_date": state.cycle_date,
                    "last_completed_date": state.last_completed_date,
                    "equity": state.equity,
                },
                sort_keys=True,
            )
        )
        return state

    def last_completed_date(self) -> date | None:
        """Idempotency boundary: the UTC date of the last fully-completed cycle."""
        latest = self.latest_path()
        if latest is None:
            return None
        state = self.load(latest)  # raises on corruption — intentional
        return state.completed_date if state else None

    # ── retention ─────────────────────────────────────────────────────────────────

    def prune(self) -> list[Path]:
        """Delete all but the most recent ``keep_days`` checkpoints (+ sidecars)."""
        ckpts = self.list_checkpoints()
        if len(ckpts) <= self.keep_days:
            return []
        stale = ckpts[: len(ckpts) - self.keep_days]
        removed: list[Path] = []
        for p in stale:
            sidecar = p.with_suffix(p.suffix + ".md5")
            p.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
            removed.append(p)
        if removed:
            logger.info(
                json.dumps(
                    {"event": "checkpoint_pruned", "removed": [str(p) for p in removed]},
                    sort_keys=True,
                )
            )
        return removed


def now_utc_iso() -> str:
    """UTC-now as ISO-8601 (daemon production path). Never used in deterministic tests."""
    return datetime.now(UTC).isoformat()
