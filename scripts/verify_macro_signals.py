#!/usr/bin/env python3
"""
scripts/verify_macro_signals.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Verify MacroSignalProvider produces non-zero values over 20 signal cycles.

Mocks the FRED REST API with realistic synthetic data so the test runs
without a live API key.  Prints cycle-by-cycle signal values.

Usage:
    python scripts/verify_macro_signals.py
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Synthetic FRED data helpers
# ---------------------------------------------------------------------------


def _make_fred_response(series_id: str, n: int = 25) -> dict:
    """Return a realistic fake FRED observations response for a given series."""
    import random

    random.seed(hash(series_id) % (2**31))

    # Realistic base values per series
    bases = {
        "M2SL": 21_000.0,  # billions USD
        "FEDFUNDS": 5.33,  # percent
        "DGS10": 4.5,  # percent
        "T10YIE": 2.4,  # percent
        "T10Y2Y": 0.3,  # percent spread
        "DTWEXBGS": 115.0,  # index
        "WALCL": 8_700_000.0,  # millions (= $8.7T)
        "WTREGEN": 800_000.0,  # millions (= $800B TGA)
        "RRPONTSYD": 400.0,  # billions
    }
    drifts = {
        "M2SL": 100.0,
        "FEDFUNDS": 0.02,
        "DGS10": 0.03,
        "T10YIE": 0.02,
        "T10Y2Y": 0.05,
        "DTWEXBGS": 0.3,
        "WALCL": 5_000.0,
        "WTREGEN": 3_000.0,
        "RRPONTSYD": 5.0,
    }
    base = bases.get(series_id, 100.0)
    drift = drifts.get(series_id, 1.0)

    obs = []
    val = base
    from datetime import date, timedelta

    d = date(2024, 1, 1)
    for _i in range(n):
        val += random.gauss(drift * 0.1, drift * 0.5)
        obs.append(
            {
                "realtime_start": str(d),
                "realtime_end": str(d),
                "date": str(d),
                "value": f"{val:.4f}",
            }
        )
        d += timedelta(days=7 if series_id in ("WALCL", "WTREGEN", "M2SL", "FEDFUNDS") else 1)

    # Return in descending order (as FRED does with sort_order=desc)
    return {"observations": list(reversed(obs))}


@contextmanager
def mock_fred_api() -> Generator[None, None, None]:
    """Context manager that patches urllib.request.urlopen with fake FRED data."""

    def fake_urlopen(req: object, timeout: int = 10) -> MagicMock:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        # Extract series_id from query string
        import urllib.parse

        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        series_id = qs.get("series_id", ["UNKNOWN"])[0]
        limit = int(qs.get("limit", ["100"])[0])
        data = _make_fred_response(series_id, n=max(limit, 30))
        payload = json.dumps(data).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with (
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
        patch.dict("os.environ", {"FRED_API_KEY": "test_key_mock"}),
    ):
        yield


# ---------------------------------------------------------------------------
# Cycle runner
# ---------------------------------------------------------------------------


def run_20_cycles() -> None:
    from omega.nodes.victoria.macro_signals import MacroSignalProvider

    print("=" * 60)
    print("MacroSignalProvider — 20-cycle verification")
    print("=" * 60)

    with mock_fred_api():
        provider = MacroSignalProvider()
        assert provider._api_key == "test_key_mock", "API key not resolved"

        non_zero_cycles = 0
        sub_signal_totals: dict[str, list[float]] = {}

        for cycle in range(1, 21):
            sig = provider.compute()

            is_nonzero = abs(sig.value) > 1e-6
            if is_nonzero:
                non_zero_cycles += 1

            # Collect sub-signal values
            for k, v in sig.raw.items():
                if k not in ("composite", "coverage", "sub_signal_count", "error"):
                    sub_signal_totals.setdefault(k, []).append(v)

            status = "✓" if is_nonzero else "✗ ZERO"
            print(
                f"  cycle {cycle:2d}: value={sig.value:+.4f}  conf={sig.confidence:.3f}"
                f"  regime={sig.regime_tag:<20s}  {status}"
            )

        print()
        print(f"Non-zero cycles: {non_zero_cycles}/20")
        print()

        # Print sub-signal summary
        print("Sub-signal averages:")
        for name in ("m2", "fed_funds", "real_yields", "yield_curve", "dxy", "net_liquidity"):
            vals = sub_signal_totals.get(name, [])
            if vals:
                avg = sum(vals) / len(vals)
                print(f"  {name:<20s}: avg={avg:+.4f}  n={len(vals)}")
            else:
                print(f"  {name:<20s}: no data")

        # Assertions
        assert non_zero_cycles == 20, f"Expected 20 non-zero cycles, got {non_zero_cycles}"
        print()
        print("✓ All 20 cycles produced non-zero macro signal values.")


def run_victoria_node_cycles() -> None:
    """Run 20 signal cycles through the full VictoriaNode, verifying macro_signals is present."""
    from omega.core.actions import NodeAction
    from omega.core.node import NodeInput
    from omega.nodes.victoria.victoria_node import VictoriaNode

    print()
    print("=" * 60)
    print("VictoriaNode — 20 compute_signals cycles (macro_signals wiring)")
    print("=" * 60)

    # Minimal market data — enough for technical signals
    def _make_ohlcv(n: int = 60, base: float = 50_000.0, trend: float = 0.001) -> dict:
        prices = [base * (1 + trend) ** i for i in range(n)]
        return {
            "close": prices,
            "adjclose": prices,
            "open": [p * 0.999 for p in prices],
            "high": [p * 1.002 for p in prices],
            "low": [p * 0.998 for p in prices],
            "volume": [1_000_000.0 + i * 1_000 for i in range(n)],
        }

    market_data = {t: _make_ohlcv() for t in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}

    with mock_fred_api():
        node = VictoriaNode()
        macro_present = 0
        macro_nonzero = 0

        for cycle in range(1, 21):
            out = node.execute(
                NodeInput(
                    request_id=str(uuid.uuid4()),
                    action=NodeAction.COMPUTE_SIGNALS.value,
                    parameters={"market_data": market_data},
                    context={},
                )
            )
            assert out.success, f"cycle {cycle} failed: {out.errors}"
            signals = out.result or {}

            macro = signals.get("macro_signals", {})
            if macro:
                macro_present += 1
            val = float(macro.get("value", 0.0)) if macro else 0.0
            if abs(val) > 1e-6:
                macro_nonzero += 1

            # Check weight allocator has macro_signals
            weights = signals.get("_weights", {})
            macro_weight = weights.get("macro_signals", 0.0)

            print(
                f"  cycle {cycle:2d}: macro value={val:+.4f}"
                f"  weight={macro_weight:.4f}"
                f"  regime={macro.get('regime_tag', 'n/a'):<22s}"
                f"  present={'✓' if macro else '✗'}"
            )

        print()
        print(f"macro_signals present: {macro_present}/20")
        print(f"macro_signals non-zero: {macro_nonzero}/20")
        assert macro_present == 20, f"Expected macro_signals in all 20 cycles, got {macro_present}"
        assert macro_nonzero == 20, (
            f"Expected non-zero macro values in all 20 cycles, got {macro_nonzero}"
        )
        print()
        print("✓ macro_signals wired correctly in VictoriaNode for all 20 cycles.")


if __name__ == "__main__":
    run_20_cycles()
    run_victoria_node_cycles()
    print()
    print("All verifications passed.")
