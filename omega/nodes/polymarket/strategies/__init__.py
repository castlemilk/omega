"""
omega.nodes.polymarket.strategies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Execution strategies for the Polymarket trading node.

Available strategies
--------------------
LatencyArbEngine   — Exploits the 9-16 s Binance→Polymarket repricing lag.
                     Import from omega.nodes.polymarket.strategies.latency_arb.
"""

from omega.nodes.polymarket.strategies.latency_arb import LatencyArbEngine
from omega.nodes.polymarket.strategies.latency_arb_config import LatencyArbConfig

__all__ = ["LatencyArbConfig", "LatencyArbEngine"]
