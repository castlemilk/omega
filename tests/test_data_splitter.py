"""Tests for omega.eval.data_splitter — DataSplitter."""

from __future__ import annotations

from datetime import date

import pytest

from omega.eval.data_splitter import DataSplitter, DateSplit


class TestDataSplitterConstruction:
    def test_valid_construction(self):
        ds = DataSplitter("2020-01-01", "2022-12-31")
        assert ds is not None

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="end must be after start"):
            DataSplitter("2022-01-01", "2020-01-01")

    def test_end_equal_start_raises(self):
        with pytest.raises(ValueError, match="end must be after start"):
            DataSplitter("2022-01-01", "2022-01-01")

    def test_invalid_ratios_raise(self):
        with pytest.raises(ValueError, match="ratios must sum to 1"):
            DataSplitter("2020-01-01", "2022-12-31", ratios=(0.5, 0.3, 0.3))

    def test_valid_custom_ratios(self):
        ds = DataSplitter("2020-01-01", "2022-12-31", ratios=(0.7, 0.15, 0.15))
        assert ds is not None


class TestDateSplitProperties:
    def setup_method(self):
        self.ds = DataSplitter("2020-01-01", "2022-12-31")
        self.split = self.ds.split()

    def test_returns_date_split(self):
        assert isinstance(self.split, DateSplit)

    def test_has_all_fields(self):
        s = self.split
        for attr in ("train_start", "train_end", "validate_start", "validate_end", "test_start", "test_end"):
            assert hasattr(s, attr)

    def test_windows_non_overlapping(self):
        s = self.split
        assert s.train_end < s.validate_start
        assert s.validate_end < s.test_start

    def test_windows_cover_full_range(self):
        s = self.split
        assert s.train_start == "2020-01-01"
        assert s.test_end == "2022-12-31"

    def test_strict_temporal_order(self):
        s = self.split
        assert (
            s.train_start
            < s.train_end
            < s.validate_start
            < s.validate_end
            < s.test_start
            < s.test_end
        )


class TestSplitProportions:
    def test_default_60_20_20(self):
        ds = DataSplitter("2020-01-01", "2022-12-31")
        s = ds.split()
        total = (date.fromisoformat("2022-12-31") - date.fromisoformat("2020-01-01")).days

        train_days = (date.fromisoformat(s.train_end) - date.fromisoformat(s.train_start)).days
        validate_days = (date.fromisoformat(s.validate_end) - date.fromisoformat(s.validate_start)).days
        test_days = (date.fromisoformat(s.test_end) - date.fromisoformat(s.test_start)).days

        assert abs(train_days / total - 0.60) < 0.02
        assert abs(validate_days / total - 0.20) < 0.02
        assert abs(test_days / total - 0.20) < 0.02

    def test_custom_70_15_15(self):
        ds = DataSplitter("2020-01-01", "2023-12-31", ratios=(0.7, 0.15, 0.15))
        s = ds.split()
        total = (date.fromisoformat("2023-12-31") - date.fromisoformat("2020-01-01")).days
        train_days = (date.fromisoformat(s.train_end) - date.fromisoformat(s.train_start)).days
        assert abs(train_days / total - 0.70) < 0.02

    def test_two_year_range(self):
        ds = DataSplitter("2022-01-01", "2023-12-31")
        s = ds.split()
        # validate window should be roughly 20% of 2 years ≈ 146 days
        validate_days = (date.fromisoformat(s.validate_end) - date.fromisoformat(s.validate_start)).days
        assert 120 < validate_days < 180

    def test_no_data_leakage_validate_after_train(self):
        """Validate window must start the day after train ends."""
        ds = DataSplitter("2020-01-01", "2024-12-31")
        s = ds.split()
        train_end = date.fromisoformat(s.train_end)
        validate_start = date.fromisoformat(s.validate_start)
        from datetime import timedelta
        assert validate_start == train_end + timedelta(days=1)

    def test_no_data_leakage_test_after_validate(self):
        """Test window must start the day after validate ends."""
        ds = DataSplitter("2020-01-01", "2024-12-31")
        s = ds.split()
        validate_end = date.fromisoformat(s.validate_end)
        test_start = date.fromisoformat(s.test_start)
        from datetime import timedelta
        assert test_start == validate_end + timedelta(days=1)

    def test_split_is_immutable(self) -> None:
        """DateSplit is frozen — cannot be accidentally mutated."""
        ds = DataSplitter("2020-01-01", "2022-12-31")
        s = ds.split()
        with pytest.raises((AttributeError, TypeError)):
            s.train_start = "2000-01-01"  # type: ignore[misc]
