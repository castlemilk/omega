"""V261 — frozen on-chain + spot-index price loader (parallel book).

Reads the V257 frozen Coin Metrics community series
(``data/frozen_series/on_chain/{BTC,ETH}/{metric}.json``) and the V255.D spot-index
price (``data/frozen_series/binance_futures/{SYMBOL}/index_price.json``). All series
are ``{date -> stringified-value}`` maps under a ``series`` key; values are parsed to
float here (the JSON stores raw decimal strings, lossless). Never imports Victoria
code. No network — replay reads frozen files only.
"""

from __future__ import annotations

import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")

# V257 asset (on-chain dir name) -> Binance spot symbol (price dir name)
ASSET_TO_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}

# on-chain metric file names under frozen_series/on_chain/{ASSET}/
_ONCHAIN_FILES = {
    "exchange_inflow_native": "exchange_inflow_native.json",   # FlowInExNtv
    "exchange_outflow_native": "exchange_outflow_native.json",  # FlowOutExNtv
    "active_addresses": "active_addresses.json",               # AdrActCnt
    "exchange_supply_native": "exchange_supply_native.json",   # SplyExNtv
    "transfer_count": "transfer_count.json",                   # TxTfrCnt
}


def _load_series(path: str) -> dict[str, float]:
    with open(path) as fh:
        raw = json.load(fh)["series"]
    return {str(k): float(v) for k, v in raw.items()}


class OnChainLoader:
    """Loads frozen on-chain metrics + spot-index price for the V261 universe."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR

    def _onchain_dir(self, asset: str) -> str:
        return os.path.join(self.data_dir, "frozen_series", "on_chain", asset)

    def _price_path(self, symbol: str) -> str:
        return os.path.join(
            self.data_dir, "frozen_series", "binance_futures", symbol, "index_price.json"
        )

    def load_onchain(self, asset: str) -> dict[str, dict[str, float]]:
        """Returns ``{metric_key -> {date -> value}}`` for one asset (5 metrics)."""
        base = self._onchain_dir(asset)
        out: dict[str, dict[str, float]] = {}
        for key, fname in _ONCHAIN_FILES.items():
            out[key] = _load_series(os.path.join(base, fname))
        return out

    def load_price(self, asset: str) -> dict[str, float]:
        """Spot-index price ``{date -> close}`` for one asset."""
        return _load_series(self._price_path(ASSET_TO_SYMBOL[asset]))

    def assets(self) -> list[str]:
        return sorted(ASSET_TO_SYMBOL)
