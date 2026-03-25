"""
Offline training for the AttentionRouter from coordination outcomes.

Reads 1,146+ rows from coordination_outcomes, computes per-node EMA of
outcome_quality weighted by success, and outputs a JSON weight file that
the Go router can load via LoadWeights().

Weight file format (data/router_weights.json):
  {
    "trained_at":    <ISO timestamp>,
    "n_outcomes":    <int>,
    "node_weights":  { "<node_name>": <ema_quality float> },
    "goal_type_bias": [<5 floats, one per GoalType enum>],
    "meta": { ... summary stats ... }
  }

The Go side reads node_weights to scale attention scores at startup.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import UTC, datetime
from typing import Any

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://omega:omega@localhost:5432/omega")

EMA_DECAY = 0.95  # weight on history; 0.05 weight on new observation
MIN_OBSERVATIONS = 3  # nodes with fewer obs get 0.5 (neutral) prior


def _connect() -> Any:
    try:
        import psycopg2

        return psycopg2.connect(DATABASE_URL)
    except ImportError:
        pass
    try:
        import psycopg

        return psycopg.connect(DATABASE_URL)
    except ImportError:
        pass
    raise RuntimeError(
        "Neither psycopg2 nor psycopg is installed. "
        "Run: pip install psycopg2-binary  or  pip install psycopg[binary]"
    )


def _load_outcomes(conn: Any) -> list[dict[str, Any]]:
    sql = """
        SELECT goal_id, goal_type, outcome_quality, routing_json, state_snapshot
        FROM coordination_outcomes
        ORDER BY captured_at
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _parse_routing(routing_json: Any) -> list[dict[str, Any]]:
    """Parse routing_json — stored as text or already a list."""
    if routing_json is None:
        return []
    if isinstance(routing_json, list):
        return routing_json
    if isinstance(routing_json, str):
        try:
            parsed: list[dict[str, Any]] = json.loads(routing_json)
            return parsed
        except json.JSONDecodeError:
            return []
    return []


def _compute_ema(scores: list[float], decay: float = EMA_DECAY) -> float:
    """Compute EMA from chronological list of quality scores."""
    if not scores:
        return 0.5
    ema = 0.5  # neutral prior
    for s in scores:
        ema = decay * ema + (1.0 - decay) * s
    return ema


def train() -> dict:
    print(f"Connecting to {DATABASE_URL.split('@')[-1]} ...")
    with _connect() as conn:
        rows = _load_outcomes(conn)

    n = len(rows)
    print(f"Loaded {n} outcome records")
    if n == 0:
        print("No outcomes found — nothing to train on.")
        sys.exit(1)

    # Per-node quality sequences (chronological)
    node_qualities: dict[str, list[float]] = {}
    # Per-GoalType quality sequences
    goal_type_qualities: dict[int, list[float]] = {}
    # Failure tracking
    failures = 0

    for row in rows:
        quality = float(row["outcome_quality"])
        goal_type = int(row["goal_type"])
        routing = _parse_routing(row["routing_json"])

        if quality == 0:
            failures += 1

        goal_type_qualities.setdefault(goal_type, []).append(quality)

        # Each step in the routing list that succeeded contributes quality
        for step in routing:
            name = step.get("name") or step.get("node_name") or step.get("primaryNode")
            if not name:
                continue
            success = step.get("success", True)
            if not success:
                # Failed steps get penalised: associate quality=0
                node_qualities.setdefault(name, []).append(0.0)
            else:
                node_qualities.setdefault(name, []).append(quality)

    # Compute EMA per node
    node_weights: dict[str, float] = {}
    node_stats: dict[str, dict] = {}
    for node, scores in sorted(node_qualities.items()):
        ema = _compute_ema(scores)
        count = len(scores)
        if count < MIN_OBSERVATIONS:
            ema = 0.5 * ema + 0.5 * 0.5  # blend toward neutral prior
        node_weights[node] = round(ema, 6)
        node_stats[node] = {
            "ema": round(ema, 6),
            "n": count,
            "mean": round(statistics.mean(scores), 6),
            "min": round(min(scores), 6),
            "max": round(max(scores), 6),
        }

    # GoalType bias vector (5 dims, GoalType enum 0-4)
    goal_type_bias: list[float] = []
    for gt in range(5):
        scores = goal_type_qualities.get(gt, [])
        ema = _compute_ema(scores) if scores else 0.5
        goal_type_bias.append(round(ema, 6))

    # Summary
    all_qualities = [r["outcome_quality"] for r in rows]
    meta = {
        "n_outcomes": n,
        "n_failures": failures,
        "mean_quality": round(statistics.mean(all_qualities), 6),
        "median_quality": round(statistics.median(all_qualities), 6),
        "n_nodes": len(node_weights),
        "ema_decay": EMA_DECAY,
        "goal_type_bias": goal_type_bias,
    }

    output = {
        "trained_at": datetime.now(UTC).isoformat(),
        "n_outcomes": n,
        "node_weights": node_weights,
        "goal_type_bias": goal_type_bias,
        "meta": meta,
        "node_stats": node_stats,
    }

    os.makedirs("data", exist_ok=True)
    out_path = "data/router_weights.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    return output


def _print_report(result: dict) -> None:
    meta = result["meta"]
    print()
    print("=" * 60)
    print("  AttentionRouter Training Results")
    print("=" * 60)
    print(f"  Outcomes trained on : {meta['n_outcomes']}")
    print(f"  Failures (quality=0): {meta['n_failures']}")
    print(f"  Mean quality        : {meta['mean_quality']:.4f}")
    print(f"  Median quality      : {meta['median_quality']:.4f}")
    print(f"  Nodes discovered    : {meta['n_nodes']}")
    print()
    print("  Per-node EMA weights:")
    for node, stats in sorted(result["node_stats"].items(), key=lambda x: -x[1]["ema"]):
        bar = "█" * int(stats["ema"] * 20)
        print(
            f"    {node:<28} EMA={stats['ema']:.4f}  n={stats['n']:4d}  "
            f"mean={stats['mean']:.4f}  [{bar}]"
        )
    print()
    print(f"  GoalType bias (0-4) : {result['goal_type_bias']}")
    print()
    print("  Saved → data/router_weights.json")
    print("=" * 60)


if __name__ == "__main__":
    result = train()
    _print_report(result)
