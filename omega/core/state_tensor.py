"""
omega.core.state_tensor
~~~~~~~~~~~~~~~~~~~~~~~
State Tensor Protocol — Phase 1 implementation.

A state tensor is a typed, versioned, fixed-width float32 snapshot of a node's
current state. It serves two roles:

1. Runtime routing signal — the attention router reads it to weight this node.
2. Training data — tensors at time T, combined with outcomes at time T+k,
   train the attention routing model.

Public API
----------
- StateTensorDimension  : one typed, named dimension
- StateTensorSchema     : declares shape and semantics for a node type
- StateTensor           : captured snapshot (values + metadata)
- VictoriaStateTensorSchema : the 16-dimensional Victoria reference
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------
# Schema types
# ---------------------------------------------------------------------------


@dataclass
class StateTensorDimension:
    """One named, typed dimension within a state tensor schema."""

    name: str
    description: str
    range_min: float
    range_max: float
    unit: str  # "fraction" | "ms" | "count" | "score" | "bool" | "ordinal"
    is_health: bool = False  # True = contributes to health_score aggregate

    def normalise(self, value: float) -> float:
        """Clamp value to [range_min, range_max] for safe downstream use."""
        return max(self.range_min, min(self.range_max, value))


@dataclass
class StateTensorSchema:
    """
    Shape and semantics of a particular node type's state tensor.

    Versioned independently from node software so that the schema can
    evolve (add dimensions, adjust ranges) without a node code change.
    """

    node_type: str
    schema_version: str
    dimensions: list[StateTensorDimension]

    @property
    def dim_count(self) -> int:
        return len(self.dimensions)

    @property
    def health_dimension_names(self) -> list[str]:
        return [d.name for d in self.dimensions if d.is_health]

    def dim_index(self, name: str) -> int:
        for i, d in enumerate(self.dimensions):
            if d.name == name:
                return i
        raise KeyError(f"Dimension '{name}' not in schema '{self.node_type}'")

    def dim(self, name: str) -> StateTensorDimension:
        for d in self.dimensions:
            if d.name == name:
                return d
        raise KeyError(f"Dimension '{name}' not in schema '{self.node_type}'")


# ---------------------------------------------------------------------------
# StateTensor
# ---------------------------------------------------------------------------


@dataclass
class StateTensor:
    """
    A fixed-width float32 snapshot of node state.

    ``values`` are in dimension order as declared by the schema.
    ``named`` provides sparse access by name for convenience.
    ``health_score`` is a scalar aggregate of the health dimensions.
    """

    node_id: str
    schema_version: str
    captured_at: datetime
    values: list[float]
    named: dict[str, float] = field(default_factory=dict)
    health_score: float = 0.0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialise values as a little-endian float32 array."""
        return struct.pack(f"<{len(self.values)}f", *self.values)

    @classmethod
    def from_bytes(
        cls,
        node_id: str,
        schema_version: str,
        captured_at: datetime,
        data: bytes,
        named: dict[str, float] | None = None,
        health_score: float = 0.0,
    ) -> StateTensor:
        n = len(data) // 4
        values = list(struct.unpack(f"<{n}f", data))
        return cls(
            node_id=node_id,
            schema_version=schema_version,
            captured_at=captured_at,
            values=values,
            named=named or {},
            health_score=health_score,
        )

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, name: str, default: float = 0.0) -> float:
        return self.named.get(name, default)

    def __len__(self) -> int:
        return len(self.values)


# ---------------------------------------------------------------------------
# StateTensorBuilder — constructs tensors from schema + value dict
# ---------------------------------------------------------------------------


class StateTensorBuilder:
    """
    Builds a StateTensor from a schema and a {name: value} dict.

    Values not present in the dict default to 0.0 (or range_min if non-zero).
    Health score is computed as the unweighted mean of is_health dimensions.
    """

    def __init__(self, schema: StateTensorSchema) -> None:
        self._schema = schema

    def build(self, node_id: str, values: dict[str, float]) -> StateTensor:
        dims = self._schema.dimensions
        vec: list[float] = []
        named: dict[str, float] = {}

        for dim in dims:
            raw = values.get(dim.name, 0.0)
            clamped = dim.normalise(raw)
            vec.append(clamped)
            named[dim.name] = clamped

        # Aggregate health score: unweighted mean of health dimensions
        health_vals = [named[n] for n in self._schema.health_dimension_names if n in named]
        health_score = sum(health_vals) / len(health_vals) if health_vals else 0.0

        return StateTensor(
            node_id=node_id,
            schema_version=self._schema.schema_version,
            captured_at=datetime.now(),
            values=vec,
            named=named,
            health_score=health_score,
        )


# ---------------------------------------------------------------------------
# Victoria 16-dimensional reference schema
# ---------------------------------------------------------------------------
#
# Dimension index | Name                    | Range  | Unit     | Health?
# ─────────────────────────────────────────────────────────────────────────
#  0              | signal_quality          | 0-1    | score    | ✓
#  1              | cycle_health            | 0-1    | fraction | ✓
#  2              | data_freshness          | 0-1    | score    | ✓
#  3              | adversarial_score       | 0-1    | score    | ✓
#  4              | improvement_trend       | -1-1   | score    | ✗
#  5              | active_experiments      | 0-20   | count    | ✗
#  6              | last_sharpe             | -3-5   | score    | ✗
#  7              | max_drawdown            | 0-1    | fraction | ✓  (lower=healthier; inverted below)
#  8              | signal_coverage         | 0-1    | fraction | ✗
#  9              | error_rate              | 0-1    | fraction | ✓  (lower=healthier; inverted below)
# 10              | autonomy_level          | 0-2    | ordinal  | ✗
# 11              | regime_label            | 0-3    | ordinal  | ✗
# 12              | trust_score             | 0-1    | score    | ✓
# 13              | memory_utilisation      | 0-1    | fraction | ✗
# 14              | cycles_since_improvement| 0-1    | score    | ✗
# 15              | lm_consultation_rate    | 0-1    | fraction | ✗

_VICTORIA_DIMS: list[StateTensorDimension] = [
    StateTensorDimension(
        "signal_quality",
        "Ensemble signal quality score (current cycle)",
        0.0,
        1.0,
        "score",
        is_health=True,
    ),
    StateTensorDimension(
        "cycle_health",
        "Fraction of pipeline steps that succeeded",
        0.0,
        1.0,
        "fraction",
        is_health=True,
    ),
    StateTensorDimension(
        "data_freshness",
        "1.0 = data < 60s old; 0.0 = data > 1h old",
        0.0,
        1.0,
        "score",
        is_health=True,
    ),
    StateTensorDimension(
        "adversarial_score",
        "1 - max_disagreement from Ring 1",
        0.0,
        1.0,
        "score",
        is_health=True,
    ),
    StateTensorDimension(
        "improvement_trend",
        "EMA of recent improvement deltas",
        -1.0,
        1.0,
        "score",
        is_health=False,
    ),
    StateTensorDimension(
        "active_experiments",
        "Number of active TPE experiments",
        0.0,
        20.0,
        "count",
        is_health=False,
    ),
    StateTensorDimension(
        "last_sharpe",
        "Most recent Sharpe ratio (normalised to [-3, 5])",
        -3.0,
        5.0,
        "score",
        is_health=False,
    ),
    StateTensorDimension(
        "max_drawdown",
        "Current max drawdown (lower = healthier)",
        0.0,
        1.0,
        "fraction",
        is_health=True,
    ),
    StateTensorDimension(
        "signal_coverage",
        "Fraction of universe with valid signals",
        0.0,
        1.0,
        "fraction",
        is_health=False,
    ),
    StateTensorDimension(
        "error_rate",
        "Pipeline error rate (last 20 cycles)",
        0.0,
        1.0,
        "fraction",
        is_health=True,
    ),
    StateTensorDimension(
        "autonomy_level",
        "0 = PICO, 1 = SUPERVISED, 2 = AUTONOMOUS",
        0.0,
        2.0,
        "ordinal",
        is_health=False,
    ),
    StateTensorDimension(
        "regime_label",
        "Current market regime (encoded)",
        0.0,
        3.0,
        "ordinal",
        is_health=False,
    ),
    StateTensorDimension(
        "trust_score",
        "Computed trust score from outcome history",
        0.0,
        1.0,
        "score",
        is_health=True,
    ),
    StateTensorDimension(
        "memory_utilisation",
        "Episodic memory fill rate",
        0.0,
        1.0,
        "fraction",
        is_health=False,
    ),
    StateTensorDimension(
        "cycles_since_improvement",
        "0 = just improved; 1 = > 50 cycles ago",
        0.0,
        1.0,
        "score",
        is_health=False,
    ),
    StateTensorDimension(
        "lm_consultation_rate",
        "Fraction of decisions using LLM brain",
        0.0,
        1.0,
        "fraction",
        is_health=False,
    ),
]

#: The 16-dimensional reference schema for VictoriaNode.
VictoriaStateTensorSchema = StateTensorSchema(
    node_type="victoria",
    schema_version="1.0.0",
    dimensions=_VICTORIA_DIMS,
)

#: Convenience builder bound to the Victoria schema.
VictoriaStateTensorBuilder = StateTensorBuilder(VictoriaStateTensorSchema)
