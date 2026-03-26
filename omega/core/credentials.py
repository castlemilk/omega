"""Centralised credential loading for Omega integrations."""

from __future__ import annotations

import os


def coingecko_api_key() -> str | None:
    """Return the CoinGecko API key from the environment, or None if unset."""
    return os.environ.get("CG_API_KEY")
