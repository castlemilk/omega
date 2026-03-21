"""
omega.eval.signal_adapter
~~~~~~~~~~~~~~~~~~~~~~~~~~
Translates between the different signal formats that flow through the Omega
orchestration pipeline.

Signal formats
--------------
1. **VectoraNode compute_signals ("raw") format** — what ``_do_compute_signals``
   returns::

       {
           "basic_signals": {ticker: {"composite": float, "rsi": float, ...}},
           "order_flow":    {"value": float, "confidence": float, ...},
           "cross_asset":   {"value": float, ...},
           "microstructure": {"value": float, ...},
           "sentiment":     {"value": float, ...},
           "_weights":      {...},
           "_regime":       str,
       }

2. **Orchestrator _step_signals ("wrapped") format** — keyed by node_id::

       {node_id: <VectoraNode compute_signals result>, ...}

3. **Flat ticker format** — what ``StrategyNode._construct_portfolio`` expects::

       {ticker: {"composite": float, ...}, ...}

The :func:`adapt_signals` function accepts any of the above formats and
normalises to format 3.
"""

from __future__ import annotations

from typing import Any

# VectoraNode signal category names used to detect raw vs orchestrator-wrapped.
_VECTORA_CATEGORIES = frozenset(
    ["basic_signals", "order_flow", "cross_asset", "microstructure", "sentiment"]
)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def is_orchestrator_format(signal_data: dict[str, Any]) -> bool:
    """
    Return True if *signal_data* is ``{node_id: compute_signals_result}``.

    Detection heuristic: at least one value must be a dict that contains
    ``"basic_signals"`` as a key whose own value is also a dict.  This
    distinguishes the orchestrator-wrapped format from the ``_weights`` metadata
    entry inside raw VectoraNode output (which contains ``"basic_signals"`` as a
    key but maps it to a *float*, not a dict).
    """
    if not signal_data:
        return False
    for v in signal_data.values():
        if (
            isinstance(v, dict)
            and "basic_signals" in v
            and isinstance(v.get("basic_signals"), dict)
        ):
            return True
    return False


def is_raw_vectora_format(signal_data: dict[str, Any]) -> bool:
    """Return True if *signal_data* is a VectoraNode compute_signals result."""
    if not signal_data:
        return False
    return bool(_VECTORA_CATEGORIES.intersection(signal_data.keys()))


# ---------------------------------------------------------------------------
# Transformation helpers
# ---------------------------------------------------------------------------


def unwrap_orchestrator_signals(signal_data: dict[str, Any]) -> dict[str, Any]:
    """
    Merge ``{node_id: compute_signals_result}`` into a single
    ``compute_signals_result``.

    When multiple nodes produce signals, their dicts are merged (later nodes
    overwrite earlier ones on key collision).
    """
    merged: dict[str, Any] = {}
    for node_signals in signal_data.values():
        if isinstance(node_signals, dict):
            merged.update(node_signals)
    return merged


def flatten_to_ticker_signals(raw_signals: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a VectoraNode compute_signals result to flat ticker format.

    Rules:
    - Keys starting with ``_`` (e.g. ``_weights``, ``_regime``) are skipped.
    - Entries whose value has a ``"value"`` key (scalar signal categories such
      as ``order_flow``) become synthetic ``adv_<name>`` ticker entries.
    - All other entries are assumed to be per-ticker signal dicts; their
      ``"composite"`` (or ``"composite_signal"``) field is normalised to
      ``"composite"``.
    """
    flat: dict[str, dict[str, Any]] = {}

    for key, val in raw_signals.items():
        if key.startswith("_"):
            continue
        if not isinstance(val, dict):
            continue

        if "value" in val:
            # Scalar signal category → synthetic ticker entry
            import contextlib

            with contextlib.suppress(TypeError, ValueError):
                flat[f"adv_{key}"] = {"composite": float(val["value"])}
            continue

        # Per-ticker signal dict (e.g. basic_signals → {ticker: {composite: ...}})
        for ticker, sig in val.items():
            if not isinstance(sig, dict):
                continue
            if "composite" in sig:
                flat[ticker] = sig
            elif "composite_signal" in sig:
                flat[ticker] = {**sig, "composite": sig["composite_signal"]}

    return flat


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def adapt_signals(signal_data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise *any* Omega signal format to ``{ticker: {"composite": float, ...}}``.

    Handles all three known formats:

    - **Orchestrator format** ``{node_id: {basic_signals: {...}, ...}}``
    - **Raw VectoraNode format** ``{basic_signals: {...}, order_flow: {...}, ...}``
    - **Flat ticker format** ``{ticker: {"composite": float}, ...}`` (pass-through)
    """
    if not signal_data:
        return {}

    # Step 1: unwrap orchestrator wrapper if present
    if is_orchestrator_format(signal_data):
        signal_data = unwrap_orchestrator_signals(signal_data)

    # Step 2: if already flat ticker format, pass through
    if not is_raw_vectora_format(signal_data):
        first_val = next(iter(signal_data.values()), None)
        if isinstance(first_val, dict) and "composite" in first_val:
            return signal_data

    # Step 3: flatten raw VectoraNode format → ticker format
    return flatten_to_ticker_signals(signal_data)
