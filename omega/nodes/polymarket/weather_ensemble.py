"""
omega.nodes.polymarket.weather_ensemble
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
GEFS ensemble weather node — computes exceedance probabilities for temperature
thresholds across US cities using Open-Meteo's free ensemble API.

The node fetches GEFS ensemble members (typically 31) and counts how many
exceed a given temperature threshold at a specified hour, producing a
probability estimate suitable for comparison against prediction-market prices.

Supported cities
----------------
NYC, LA, CHICAGO, MIAMI, DALLAS, SEATTLE, DENVER, BOSTON, PHOENIX, ATLANTA,
LONDON, ANKARA, TEL_AVIV

Cache
-----
Results are cached for 10 minutes per (city, threshold, hour) tuple to avoid
hammering the free API tier.

Usage::

    node = WeatherEnsembleNode()
    out = node.execute(NodeInput(
        action="probability",
        parameters={
            "city": "NYC",
            "threshold_c": 30.0,
            "target_hour": 12,
        }
    ))
    # out.result = {"probability": 0.71, "member_count": 31, ...}
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.polymarket.weather_ensemble")

# ---------------------------------------------------------------------------
# City coordinates
# ---------------------------------------------------------------------------

CITIES: dict[str, tuple[float, float]] = {
    "NYC": (40.7128, -74.0060),
    "LA": (34.0522, -118.2437),
    "CHICAGO": (41.8781, -87.6298),
    "MIAMI": (25.7617, -80.1918),
    "DALLAS": (32.7767, -96.7970),
    "SEATTLE": (47.6062, -122.3321),
    "DENVER": (39.7392, -104.9903),
    "BOSTON": (42.3601, -71.0589),
    "PHOENIX": (33.4484, -112.0740),
    "ATLANTA": (33.7490, -84.3880),
    # International cities — active Polymarket weather markets
    "LONDON": (51.5074, -0.1278),
    "ANKARA": (39.9334, 32.8597),
    "TEL_AVIV": (32.0853, 34.7818),
}

OPEN_METEO_ENSEMBLE_URL = (
    "https://ensemble-api.open-meteo.com/v1/ensemble"
    "?latitude={lat}&longitude={lon}"
    "&models=gfs_seamless"
    "&hourly=temperature_2m"
    "&forecast_days=2"
)

CACHE_TTL_SECONDS = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    result: dict[str, Any]
    expires_at: float


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


class WeatherEnsembleNode(Node):
    """
    Fetches GEFS ensemble forecast data and computes exceedance probabilities.

    Actions
    -------
    probability     — P(temperature > threshold_c) at target_hour for city
    ensemble_data   — Raw ensemble time-series for city (no threshold)
    list_cities     — Return supported city names
    """

    skill_tags: ClassVar[list[str]] = ["weather", "prediction_markets"]

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_latency_ms = 0.0
        self._cache: dict[str, _CacheEntry] = {}

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="WeatherEnsembleNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={
                "cache_size": len(self._cache),
                "supported_cities": list(CITIES.keys()),
            },
        )

    def get_capabilities(self) -> list[str]:
        return [
            NodeAction.PROBABILITY.value,
            "ensemble_data",
            "list_cities",
            NodeAction.WEATHER_ENSEMBLE.value,
        ]

    def describe(self) -> str:
        return (
            "Fetches GEFS ensemble weather forecasts from Open-Meteo and computes "
            "temperature exceedance probabilities for US cities. Used to generate "
            "model probabilities for comparison against Polymarket weather market prices."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action.lower()

        result: Any = None
        try:
            if action in (
                NodeAction.PROBABILITY.value,
                NodeAction.WEATHER_ENSEMBLE.value,
                "weatherdata",
            ):
                result = self._compute_probability(inp.parameters)
            elif action == "ensemble_data":
                result = self._fetch_ensemble(inp.parameters)
            elif action == "list_cities":
                result = {"cities": list(CITIES.keys())}
            else:
                raise ValueError(
                    f"Unknown action '{action}'. Supported: {self.get_capabilities()}"
                )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.warning("WeatherEnsembleNode error: %s", exc)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

        elapsed = (time.perf_counter() - t0) * 1000
        self._total_latency_ms += elapsed
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": elapsed},
        )

    def evaluate(self) -> dict[str, float]:
        total_cache = self._cache_hits + self._cache_misses
        return {
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "cache_hit_rate": self._cache_hits / max(1, total_cache),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_key(self, city: str, threshold_c: float, target_hour: int) -> str:
        return f"{city}:{threshold_c}:{target_hour}"

    def _get_cached(self, key: str) -> dict[str, Any] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() > entry.expires_at:
            del self._cache[key]
            return None
        return entry.result

    def _set_cache(self, key: str, result: dict[str, Any]) -> None:
        self._cache[key] = _CacheEntry(
            result=result,
            expires_at=time.time() + CACHE_TTL_SECONDS,
        )

    def _compute_probability(self, params: dict[str, Any]) -> dict[str, Any]:
        city = str(params.get("city", "NYC")).upper()
        threshold_c = float(params.get("threshold_c", 30.0))
        target_hour = int(params.get("target_hour", 12))

        if city not in CITIES:
            raise ValueError(f"Unknown city '{city}'. Supported: {list(CITIES.keys())}")

        cache_key = self._cache_key(city, threshold_c, target_hour)
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached

        self._cache_misses += 1
        raw = self._fetch_raw_ensemble(city)
        result = self._compute_exceedance(raw, threshold_c, target_hour, city)
        self._set_cache(cache_key, result)
        return result

    def _fetch_ensemble(self, params: dict[str, Any]) -> dict[str, Any]:
        city = str(params.get("city", "NYC")).upper()
        if city not in CITIES:
            raise ValueError(f"Unknown city '{city}'. Supported: {list(CITIES.keys())}")

        cache_key = f"raw:{city}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached

        self._cache_misses += 1
        raw = self._fetch_raw_ensemble(city)
        self._set_cache(cache_key, raw)
        return raw

    def _fetch_raw_ensemble(self, city: str) -> dict[str, Any]:
        lat, lon = CITIES[city]
        url = OPEN_METEO_ENSEMBLE_URL.format(lat=lat, lon=lon)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "omega-weather-ensemble/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        return data

    def _compute_exceedance(
        self,
        raw: dict[str, Any],
        threshold_c: float,
        target_hour: int,
        city: str,
    ) -> dict[str, Any]:
        """
        Count ensemble members where temperature at target_hour > threshold_c.

        Open-Meteo returns member data under keys like:
          hourly.temperature_2m_member01, temperature_2m_member02, …
        or a flat list under hourly.temperature_2m (when only one member is
        requested). We handle both shapes.
        """
        hourly = raw.get("hourly", {})
        times = hourly.get("time", [])

        # Find the index corresponding to target_hour in today's forecast
        today = datetime.now().strftime("%Y-%m-%d")
        target_time = f"{today}T{target_hour:02d}:00"
        # If exact match not found, use nearest hour in the series
        if target_time in times:
            idx = times.index(target_time)
        elif times:
            # fall back to closest hour
            idx = min(
                range(len(times)),
                key=lambda i: abs(datetime.fromisoformat(times[i]).hour - target_hour),
            )
        else:
            raise ValueError("No time data in ensemble response")

        # Collect member temperature values at target_hour
        member_temps: list[float] = []
        for key, values in hourly.items():
            if (
                key.startswith("temperature_2m")
                and key != "temperature_2m"
                and isinstance(values, list)
                and idx < len(values)
            ):
                v = values[idx]
                if v is not None:
                    member_temps.append(float(v))

        # Flat single-member fallback
        if not member_temps:
            flat = hourly.get("temperature_2m", [])
            if isinstance(flat, list) and idx < len(flat) and flat[idx] is not None:
                member_temps = [float(flat[idx])]

        if not member_temps:
            raise ValueError("Could not extract member temperature values from API response")

        exceeding = sum(1 for t in member_temps if t > threshold_c)
        probability = exceeding / len(member_temps)

        return {
            "city": city,
            "threshold_c": threshold_c,
            "target_hour": target_hour,
            "probability": round(probability, 4),
            "member_count": len(member_temps),
            "members_exceeding": exceeding,
            "mean_temp_c": round(sum(member_temps) / len(member_temps), 2),
            "fetched_at": datetime.now().isoformat(),
        }
