"""omega.eval.data_splitter — Temporal train/validate/test split utility.

All date arithmetic lives here. No other module should compute split boundaries.

Usage::

    from omega.eval.data_splitter import DataSplitter

    ds = DataSplitter("2020-01-01", "2024-12-31")
    split = ds.split()
    # split.validate_start / split.validate_end  → TPE objective window
    # split.test_start    / split.test_end        → held-out, never seen by TPE
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DateSplit:
    """Three non-overlapping temporal windows. All dates are ISO-8601 strings."""

    train_start: str
    train_end: str
    validate_start: str
    validate_end: str
    test_start: str
    test_end: str


class DataSplitter:
    """
    Splits [start, end] into train / validate / test windows by day count.

    Parameters
    ----------
    start  : ISO-8601 date string — inclusive lower bound of the full range.
    end    : ISO-8601 date string — inclusive upper bound of the full range.
    ratios : (train, validate, test) fractions; must sum to 1.0 ± 0.001.

    The three windows are strictly non-overlapping and ordered temporally:
        train_end < validate_start < validate_end < test_start

    Example
    -------
    >>> ds = DataSplitter("2020-01-01", "2024-12-31")
    >>> split = ds.split()
    >>> split.validate_start  # first day TPE is allowed to see
    >>> split.test_start      # first day held out from TPE entirely
    """

    def __init__(
        self,
        start: str,
        end: str,
        ratios: tuple[float, float, float] = (0.6, 0.2, 0.2),
    ) -> None:
        self._start = date.fromisoformat(start)
        self._end = date.fromisoformat(end)
        if self._end <= self._start:
            raise ValueError(
                f"end must be after start: got start={start!r}, end={end!r}"
            )
        if abs(sum(ratios) - 1.0) > 0.001:
            raise ValueError(
                f"ratios must sum to 1, got {sum(ratios):.6f} from {ratios}"
            )
        self._ratios = ratios

    def split(self) -> DateSplit:
        """Return the three non-overlapping windows as a DateSplit."""
        total_days = (self._end - self._start).days  # exclusive end → total span
        train_days = round(total_days * self._ratios[0])
        validate_days = round(total_days * self._ratios[1])

        # Windows are [start, end] inclusive, so end = start + (days - 1)
        train_end = self._start + timedelta(days=train_days - 1)
        validate_start = train_end + timedelta(days=1)
        validate_end = validate_start + timedelta(days=validate_days - 1)
        test_start = validate_end + timedelta(days=1)

        return DateSplit(
            train_start=self._start.isoformat(),
            train_end=train_end.isoformat(),
            validate_start=validate_start.isoformat(),
            validate_end=validate_end.isoformat(),
            test_start=test_start.isoformat(),
            test_end=self._end.isoformat(),
        )
