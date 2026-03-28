"""
omega.nodes.polymarket
~~~~~~~~~~~~~~~~~~~~~~
Polymarket prediction-market trading node.

Sub-packages
------------
clob_client   — Central Limit Order Book (CLOB) API client
top_traders   — Smart-money consensus derived from order-book flow
strategies    — Execution strategies (latency arb, market making, etc.)
"""

from omega.nodes.polymarket.clob_client import (
    CLOBClient,
    LiveOrderResult,
    MarketInfo,
    OrderBook,
    PaperOrderResult,
)
from omega.nodes.polymarket.top_traders import SmartMoneyConsensus, TopTradersNode, get_consensus

__all__ = [
    "CLOBClient",
    "LiveOrderResult",
    "MarketInfo",
    "OrderBook",
    "PaperOrderResult",
    "SmartMoneyConsensus",
    "TopTradersNode",
    "get_consensus",
]
