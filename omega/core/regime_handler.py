"""
omega.core.regime_handler
~~~~~~~~~~~~~~~~~~~~~~~~~~
Enhanced regime handling for the Omega memory system.

Components
----------
  RegimeTransitionHandler : Detects regime changes and manages the transition
                            lifecycle (uncertain → confirmed).
  TransitionBuffer        : Holds recent observations during uncertain transition
                            periods before committing to a new regime.
  RegimeSignalModifier    : Adjusts signal weights based on the current regime label.
  RegimeHistory           : Append-only log of past regime entries/exits with query
                            support.

Design notes
------------
- Pure Python stdlib only.
- Regime labels follow the BOCPDRegimeDetector convention: "normal", "trending",
  "volatile", "crash".
- Transition confidence is computed as an exponential moving average of
  changepoint_prob values; a confirmed transition requires sustained high
  changepoint probability for at least `confirmation_steps` cycles.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.core.regime_handler")

# Known regime labels
REGIMES = frozenset({"normal", "trending", "volatile", "crash"})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RegimeEntry:
    """A record of a single regime's active period."""

    entry_id: str
    regime_label: str
    entered_at: float  # UNIX timestamp
    exited_at: float | None  # None while still active
    cycle_in: int
    cycle_out: int | None  # None while still active
    trigger_changepoint_prob: float  # changepoint_prob that triggered this entry
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float | None:
        if self.exited_at is None:
            return None
        return self.exited_at - self.entered_at

    @property
    def is_active(self) -> bool:
        return self.exited_at is None


@dataclass
class TransitionEvent:
    """Captures a detected (but possibly unconfirmed) transition."""

    event_id: str
    from_regime: str
    to_regime: str
    detected_at: float
    detected_cycle: int
    confirmed: bool = False
    confirmed_at: float | None = None
    confidence: float = 0.0  # EMA of changepoint_prob since detection


# ---------------------------------------------------------------------------
# RegimeHistory
# ---------------------------------------------------------------------------


class RegimeHistory:
    """
    Append-only log of RegimeEntry objects.

    Supports queries by label, time range, and cycle range.
    """

    def __init__(self) -> None:
        self._entries: list[RegimeEntry] = []
        self._active: RegimeEntry | None = None

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def enter(
        self,
        regime_label: str,
        cycle: int,
        changepoint_prob: float,
        now: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RegimeEntry:
        if now is None:
            now = time.time()

        # Close out the previous active entry
        if self._active is not None:
            self._active.exited_at = now
            self._active.cycle_out = cycle

        entry = RegimeEntry(
            entry_id=str(uuid.uuid4()),
            regime_label=regime_label,
            entered_at=now,
            exited_at=None,
            cycle_in=cycle,
            cycle_out=None,
            trigger_changepoint_prob=changepoint_prob,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        self._active = entry
        logger.info(
            "Regime entered: %s at cycle %d (cp_prob=%.3f)",
            regime_label,
            cycle,
            changepoint_prob,
        )
        return entry

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def current(self) -> RegimeEntry | None:
        return self._active

    @property
    def current_label(self) -> str:
        return self._active.regime_label if self._active else "unknown"

    def by_label(self, label: str) -> list[RegimeEntry]:
        return [e for e in self._entries if e.regime_label == label]

    def by_time_range(self, start: float, end: float) -> list[RegimeEntry]:
        result = []
        for e in self._entries:
            if e.exited_at is None:
                # still active — overlaps if it started before end
                if e.entered_at <= end:
                    result.append(e)
            else:
                if e.entered_at <= end and e.exited_at >= start:
                    result.append(e)
        return result

    def by_cycle_range(self, cycle_start: int, cycle_end: int) -> list[RegimeEntry]:
        result = []
        for e in self._entries:
            cout = e.cycle_out if e.cycle_out is not None else cycle_end + 1
            if e.cycle_in <= cycle_end and cout >= cycle_start:
                result.append(e)
        return result

    def transitions(self) -> list[tuple[RegimeEntry, RegimeEntry]]:
        """Returns consecutive (from, to) pairs for all completed transitions."""
        pairs = []
        for i in range(1, len(self._entries)):
            pairs.append((self._entries[i - 1], self._entries[i]))
        return pairs

    def stats(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for e in self._entries:
            counts[e.regime_label] = counts.get(e.regime_label, 0) + 1
        return {
            "total_entries": len(self._entries),
            "regime_counts": counts,
            "current_regime": self.current_label,
        }


# ---------------------------------------------------------------------------
# TransitionBuffer
# ---------------------------------------------------------------------------


class TransitionBuffer:
    """
    Holds recent observations during uncertain transition periods.

    While a transition is unconfirmed, incoming data is buffered here
    rather than being committed to the main memory store.  Once the
    transition is confirmed (or rejected), the buffer is drained.
    """

    def __init__(self, max_size: int = 100) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._pending_event: TransitionEvent | None = None
        self._max_size = max_size

    def start_buffering(self, event: TransitionEvent) -> None:
        if self._pending_event is not None:
            logger.warning(
                "TransitionBuffer: overwriting pending event %s with %s",
                self._pending_event.event_id[:8],
                event.event_id[:8],
            )
        self._pending_event = event
        self._buffer.clear()
        logger.debug(
            "TransitionBuffer: started buffering for transition %s → %s",
            event.from_regime,
            event.to_regime,
        )

    def push(self, observation: dict[str, Any]) -> None:
        if self._pending_event is not None:
            self._buffer.append(observation)

    def drain(self) -> list[dict[str, Any]]:
        """Return all buffered observations and clear the buffer."""
        items = list(self._buffer)
        self._buffer.clear()
        self._pending_event = None
        return items

    def reject(self) -> list[dict[str, Any]]:
        """Reject the pending transition and drain the buffer."""
        if self._pending_event is not None:
            logger.debug(
                "TransitionBuffer: rejecting transition %s → %s",
                self._pending_event.from_regime,
                self._pending_event.to_regime,
            )
        return self.drain()

    @property
    def is_buffering(self) -> bool:
        return self._pending_event is not None

    @property
    def pending_event(self) -> TransitionEvent | None:
        return self._pending_event

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)


# ---------------------------------------------------------------------------
# RegimeSignalModifier
# ---------------------------------------------------------------------------


class RegimeSignalModifier:
    """
    Adjusts signal weights based on the current regime label.

    The multiplier table is domain-specific and must be injected at
    construction.  The framework provides no defaults — a trading domain
    injects its own table (see omega/nodes/victoria/domain_config.py).

    multiplier_table : dict[str, dict[str, float]]
        Mapping of {regime_label: {signal_name: multiplier}}.
        Signals not present in the table for a given regime pass through at 1.0.
        Regimes not present in the table leave all signals unchanged.

    Example::

        mod = RegimeSignalModifier(multiplier_table={
            "volatile": {"momentum": 0.5, "trend_follow": 0.4},
            "crash":    {"momentum": 0.2, "risk_off": 2.0},
        })
        adjusted = mod.modify({"momentum": 1.0, "mean_reversion": 1.0}, "volatile")
        # => {"momentum": 0.5, "mean_reversion": 1.0}

    Callers supply a dict of {signal_name: raw_weight} and receive a dict
    of {signal_name: adjusted_weight}.  Unknown signals pass through unchanged.
    """

    def __init__(
        self,
        multiplier_table: dict[str, dict[str, float]] | None = None,
        # Legacy parameter name — accepted for backward compatibility
        multiplier_overrides: dict[str, dict[str, float]] | None = None,
    ) -> None:
        # multiplier_table wins; fall back to multiplier_overrides for compat
        source = multiplier_table if multiplier_table is not None else multiplier_overrides
        self._multipliers: dict[str, dict[str, float]] = dict(source) if source else {}

    def modify(
        self,
        signals: dict[str, float],
        current_regime: str,
    ) -> dict[str, float]:
        """
        Apply regime-specific multipliers to signal weights.

        Returns a new dict (original is not mutated).
        """
        table = self._multipliers.get(current_regime, {})
        result = {}
        for name, weight in signals.items():
            multiplier = table.get(name, 1.0)
            result[name] = weight * multiplier
        return result

    def get_multiplier(self, signal_type: str, regime: str) -> float:
        return self._multipliers.get(regime, {}).get(signal_type, 1.0)

    def set_multiplier(self, regime: str, signal_type: str, value: float) -> None:
        if regime not in self._multipliers:
            self._multipliers[regime] = {}
        self._multipliers[regime][signal_type] = value


# ---------------------------------------------------------------------------
# RegimeTransitionHandler
# ---------------------------------------------------------------------------


class RegimeTransitionHandler:
    """
    Detects and manages regime transitions.

    Lifecycle
    ---------
    1. Update the handler with the latest BOCPD state (regime_label, changepoint_prob).
    2. If changepoint_prob > detection_threshold, a TransitionEvent is raised.
    3. The TransitionBuffer begins buffering incoming observations.
    4. Over the next `confirmation_steps` updates, an EMA of changepoint_prob is
       maintained.
    5. If EMA stays above confirmation_threshold, the transition is confirmed and
       RegimeHistory is updated.
    6. If EMA drops below rejection_threshold, the transition is rejected and the
       buffer is drained back to the caller.
    """

    def __init__(
        self,
        detection_threshold: float = 0.5,
        confirmation_threshold: float = 0.6,
        rejection_threshold: float = 0.2,
        confirmation_steps: int = 3,
        ema_alpha: float = 0.5,
        buffer_max_size: int = 200,
    ) -> None:
        self._detect_thresh = detection_threshold
        self._confirm_thresh = confirmation_threshold
        self._reject_thresh = rejection_threshold
        self._confirm_steps = confirmation_steps
        self._ema_alpha = ema_alpha

        self.history = RegimeHistory()
        self.buffer = TransitionBuffer(max_size=buffer_max_size)
        self.modifier = RegimeSignalModifier()

        self._current_regime: str = "normal"
        self._candidate_regime: str | None = None
        self._ema: float = 0.0
        self._steps_since_detection: int = 0
        self._cycle: int = 0

        # Pending transition event (if any)
        self._pending: TransitionEvent | None = None

        # Completed / rejected events for audit
        self._events: list[TransitionEvent] = []

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(
        self,
        regime_label: str,
        changepoint_prob: float,
        observation: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> TransitionEvent | None:
        """
        Feed a new BOCPD observation into the handler.

        Returns a confirmed TransitionEvent if a transition was just confirmed,
        otherwise None.
        """
        if now is None:
            now = time.time()
        self._cycle += 1

        # Push to buffer if we're in a transition period
        if self.buffer.is_buffering and observation is not None:
            self.buffer.push(observation)

        # --- Not currently tracking a transition ---
        if self._pending is None:
            if changepoint_prob >= self._detect_thresh and regime_label != self._current_regime:
                self._pending = TransitionEvent(
                    event_id=str(uuid.uuid4()),
                    from_regime=self._current_regime,
                    to_regime=regime_label,
                    detected_at=now,
                    detected_cycle=self._cycle,
                    confidence=changepoint_prob,
                )
                self._ema = changepoint_prob
                self._steps_since_detection = 1
                self._candidate_regime = regime_label
                self.buffer.start_buffering(self._pending)
                logger.debug(
                    "Possible regime transition: %s → %s (cp=%.3f)",
                    self._current_regime,
                    regime_label,
                    changepoint_prob,
                )
            return None

        # --- Tracking a pending transition ---
        self._steps_since_detection += 1

        # Update EMA
        self._ema = self._ema_alpha * changepoint_prob + (1 - self._ema_alpha) * self._ema
        self._pending.confidence = self._ema

        # Check for rejection
        if self._ema < self._reject_thresh:
            rejected = self._pending
            self.buffer.reject()
            self._pending = None
            self._candidate_regime = None
            self._steps_since_detection = 0
            self._ema = 0.0
            logger.debug(
                "Transition %s → %s rejected (ema=%.3f)",
                rejected.from_regime,
                rejected.to_regime,
                rejected.confidence,
            )
            self._events.append(rejected)
            return None

        # Check for confirmation
        if (
            self._steps_since_detection >= self._confirm_steps
            and self._ema >= self._confirm_thresh
        ):
            confirmed = self._pending
            confirmed.confirmed = True
            confirmed.confirmed_at = now

            # Update regime
            prev = self._current_regime
            self._current_regime = confirmed.to_regime

            # Commit to history
            self.history.enter(
                regime_label=confirmed.to_regime,
                cycle=self._cycle,
                changepoint_prob=changepoint_prob,
                now=now,
            )

            # Drain buffer
            self.buffer.drain()

            self._pending = None
            self._candidate_regime = None
            self._steps_since_detection = 0
            self._ema = 0.0

            self._events.append(confirmed)
            logger.info(
                "Transition confirmed: %s → %s (ema=%.3f)",
                prev,
                confirmed.to_regime,
                confirmed.confidence,
            )
            return confirmed

        return None

    # ------------------------------------------------------------------
    # Signal modification helpers
    # ------------------------------------------------------------------

    def modify_signals(self, signals: dict[str, float]) -> dict[str, float]:
        return self.modifier.modify(signals, self._current_regime)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def current_regime(self) -> str:
        return self._current_regime

    @property
    def is_transitioning(self) -> bool:
        return self._pending is not None

    @property
    def pending_transition(self) -> TransitionEvent | None:
        return self._pending

    def all_events(self) -> list[TransitionEvent]:
        return list(self._events)

    def stats(self) -> dict[str, Any]:
        return {
            "current_regime": self._current_regime,
            "is_transitioning": self.is_transitioning,
            "candidate_regime": self._candidate_regime,
            "transition_ema": self._ema,
            "steps_since_detection": self._steps_since_detection,
            "total_events": len(self._events),
            "confirmed_events": sum(1 for e in self._events if e.confirmed),
            "history": self.history.stats(),
        }
