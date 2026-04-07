"""
Exchange flow signal stub for Victoria — tracks net BTC/ETH flows to/from exchanges.

## What this measures

Net exchange inflow/outflow is one of the most reliable on-chain leading indicators:
  - Exchange inflow spike  → holders moving coins to sell → bearish pressure
  - Exchange outflow spike → coins leaving exchanges (self-custody/staking) → bullish
  - Net flow z-score > 0  → above-average selling pressure → short signal
  - Net flow z-score < 0  → above-average withdrawal → long signal

## Data sources (in preference order)

1. **Glassnode** (https://api.glassnode.com)
   - Endpoint: GET /v1/metric/transactions/transfers_volume_exchanges_net
   - Params: a=BTC (or ETH), i=24h, api_key=<GLASSNODE_API_KEY>
   - Returns: [{"t": <unix_ts>, "v": <net_usd>}, ...]
   - Auth: free tier supports 1d granularity; paid gets 1h
   - Rate limit: 60 req/min on free, 600/min on paid
   - Env var: GLASSNODE_API_KEY

2. **CryptoQuant** (https://api.cryptoquant.com)
   - Endpoint: GET /v1/btc/exchange-flows/netflow
   - Params: window=day, exchange=all, limit=30
   - Auth: Bearer token — env var CRYPTOQUANT_API_KEY
   - Rate limit: 100 req/day on free tier
   - Docs: https://cryptoquant.com/docs

3. **Coinglass** (https://coinglass.com/api)
   - Endpoint: GET /api/pro/v1/bitcoin/exchange-balance
   - Auth: COINGLASS-API-KEY header — env var COINGLASS_API_KEY
   - Returns 24h exchange balance changes across major venues

## Current status: STUB — returns 0.0

This class documents the API contracts but does not make live requests.
Wire up one of the APIs above once an API key is available:
  1. Add key to .env.example
  2. Fetch the last 30 days of daily net flow
  3. Z-score normalize with rolling 30-period mean/std
  4. Return clamped to [-1, 1]

## Integration

Add to signal_generation.py alongside FundingRateSignal:
  from omega.nodes.victoria.signals.exchange_flow import ExchangeFlowSignal
  _exchange_flow = ExchangeFlowSignal()
  ...
  exchange_flow_val = _exchange_flow.compute(symbol, market_data)
"""

import logging

logger = logging.getLogger("omega.nodes.victoria.signals.exchange_flow")


class ExchangeFlowSignal:
    """
    Stub exchange flow signal.

    Returns 0.0 until a Glassnode/CryptoQuant/Coinglass API key is wired in.
    See module docstring for full API contracts and integration steps.
    """

    def __init__(self) -> None:
        self._warned = False

    def compute(self, symbol: str, market_data: dict) -> float:
        """
        Return net exchange flow z-score for `symbol`, clamped to [-1, 1].

        Positive → above-average inflow (bearish).
        Negative → above-average outflow (bullish).
        Returns 0.0 (neutral) until API is wired in.
        """
        if not self._warned:
            logger.debug(
                "ExchangeFlowSignal is a stub — returning 0.0 for %s. "
                "Wire up Glassnode/CryptoQuant API to activate.",
                symbol,
            )
            self._warned = True
        return 0.0
