"""
omega.nodes.vectora.cleaners
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Immune-cell nodes for data quality enforcement.

CleanerNode — abstract base extending Node
LintNode    — data quality checker (NaN detection, missing fields, error rates)
DataIntegrityNode — freshness + completeness + volume sanity checker
"""

import time
import uuid
from abc import abstractmethod
from typing import Any, Dict, List

from omega.core.node import Node, NodeInput, NodeOutput, NodeState


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class CleanerNode(Node):
    """
    Immune-cell base for data quality enforcement.

    Cleaner nodes don't generate signals or trade — they patrol the data
    pipeline and flag anomalies, drift, and integrity violations.

    Two-tier detection:
      fast: run every cycle (cheap checks)
      deep: run every DEEP_INTERVAL cycles (expensive analysis)

    Triage state machine per issue:
      Recovery -> Pending -> Active -> Resolved
    """

    DEEP_INTERVAL = 5  # deep scan every N cycles

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._cycle_count = 0
        self._issues: Dict[str, Dict[str, Any]] = {}  # issue_id -> issue dict
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._issues_found_total = 0
        self._issues_resolved_total = 0

    # -- Node interface

    def evaluate(self) -> Dict[str, float]:
        active = sum(1 for i in self._issues.values() if i["state"] == "active")
        resolved_rate = self._issues_resolved_total / max(1, self._issues_found_total)
        return {
            "active_issues": float(active),
            "resolved_rate": resolved_rate,
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        return False  # Cleaners improve their rules, not their architecture

    def execute(self, input: NodeInput) -> NodeOutput:
        """Route to fast/deep checks based on action and cycle count."""
        t0 = time.perf_counter()
        self._execution_count += 1
        self._cycle_count += 1

        try:
            action = input.action
            if action not in self.get_capabilities():
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action: {action}"],
                    metrics={"latency_ms": 0.0},
                )

            data = input.parameters.get("market_data", {})

            # Run fast checks every cycle
            fast_issues = self._fast_check(data)
            for iss in fast_issues:
                self._open_issue(
                    iss["issue_id"],
                    iss["severity"],
                    iss["description"],
                    iss.get("context", {}),
                )

            # Run deep checks every DEEP_INTERVAL cycles
            deep_issues = []
            if self._cycle_count % self.DEEP_INTERVAL == 0:
                deep_issues = self._deep_check(data)
                for iss in deep_issues:
                    self._open_issue(
                        iss["issue_id"],
                        iss["severity"],
                        iss["description"],
                        iss.get("context", {}),
                    )

            # Resolve issues that were not re-raised this cycle
            raised_ids = {i["issue_id"] for i in fast_issues + deep_issues}
            for issue_id in list(self._issues.keys()):
                if issue_id not in raised_ids:
                    self._resolve_issue(issue_id)

            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms

            result = self._build_result(data, fast_issues + deep_issues)

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": latency_ms},
            )

        except Exception as exc:
            self._error_count += 1
            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": latency_ms},
            )

    # -- Triage helpers

    def _open_issue(self, issue_id: str, severity: str, description: str, context: Dict) -> None:
        if issue_id not in self._issues:
            self._issues[issue_id] = {
                "issue_id": issue_id,
                "severity": severity,    # "error", "warning", "info"
                "description": description,
                "context": context,
                "state": "pending",      # pending -> active -> resolved
                "opened_at": time.time(),
                "resolved_at": None,
            }
            self._issues_found_total += 1
        else:
            # Escalate to active if pending
            if self._issues[issue_id]["state"] == "pending":
                self._issues[issue_id]["state"] = "active"

    def _resolve_issue(self, issue_id: str) -> None:
        if issue_id in self._issues and self._issues[issue_id]["state"] != "resolved":
            self._issues[issue_id]["state"] = "resolved"
            self._issues[issue_id]["resolved_at"] = time.time()
            self._issues_resolved_total += 1

    def _active_issues(self) -> List[Dict[str, Any]]:
        return [i for i in self._issues.values() if i["state"] in ("pending", "active")]

    # -- Abstract methods (subclasses must implement)

    @abstractmethod
    def _fast_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Run cheap checks every cycle. Returns list of issue dicts."""

    @abstractmethod
    def _deep_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Run expensive analysis every DEEP_INTERVAL cycles."""

    @abstractmethod
    def _build_result(self, data: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build the action-specific result dict from check findings."""


# ---------------------------------------------------------------------------
# LintNode
# ---------------------------------------------------------------------------

class LintNode(CleanerNode):
    """
    Data quality linter — checks for NaN values, missing fields, and error rates.

    Fast checks (every cycle):
      - NaN/None detection in OHLCV fields per pair
      - Required field existence check
      - Error-rate threshold per pair

    Deep checks (every 5 cycles):
      - Price outlier detection (close > 5x previous close)
      - Suspiciously flat prices (all closes identical)

    Improvement arc:
      v1.0: basic NaN/missing field checks
      v1.1: add price outlier detection (if active issues > 3 or iteration >= 2)
    """

    REQUIRED_FIELDS = ["timestamps", "open", "high", "low", "close", "volume"]
    ERROR_RATE_THRESHOLD = 0.1

    def get_capabilities(self) -> List[str]:
        return ["lint_market_data"]

    def describe(self) -> str:
        return (
            "Patrols market data for NaN values, missing OHLCV fields, "
            "price outliers, and flat-price anomalies. Flags data quality "
            "issues before they propagate downstream."
        )

    def get_state(self) -> NodeState:
        active = self._active_issues()
        health = max(0.0, 1.0 - len(active) * 0.2)
        return NodeState(
            node_id=self._node_id,
            name="LintNode",
            version=self._version,
            health=health,
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={"active_issues": len(active)},
        )

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """
        v1.0 -> v1.1: enable deep price-outlier detection when issues accumulate
        or after sufficient iterations.
        """
        if self._version == "1.0":
            iteration = feedback.get("iteration", 0)
            active_count = len(self._active_issues())
            if active_count > 3 or iteration >= 2:
                self._version = "1.1"
                return True
        return False

    def _fast_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        for pair, ohlcv in data.items():
            if ohlcv is None:
                # Pair failed to fetch — this is an ingestion concern, not a lint concern
                continue

            # Check required fields
            for field in self.REQUIRED_FIELDS:
                if field not in ohlcv or ohlcv[field] is None:
                    issues.append({
                        "issue_id": f"missing_field_{pair}_{field}",
                        "severity": "error",
                        "description": f"{pair}: missing required field '{field}'",
                        "context": {"pair": pair, "field": field},
                    })

            # Count NaN/None in close/open/high/low/volume
            for field in ["close", "open", "high", "low", "volume"]:
                values = ohlcv.get(field)
                if not isinstance(values, (list, tuple)):
                    continue
                nan_count = sum(1 for v in values if v is None or (isinstance(v, float) and v != v))
                if nan_count > 0:
                    rate = nan_count / len(values) if values else 0.0
                    issues.append({
                        "issue_id": f"nan_values_{pair}_{field}",
                        "severity": "warning" if rate < 0.05 else "error",
                        "description": f"{pair}.{field}: {nan_count} NaN/None values ({rate:.1%})",
                        "context": {"pair": pair, "field": field, "nan_count": nan_count, "rate": rate},
                    })

        return issues

    def _deep_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Price outlier and flat-price detection (expensive, every 5 cycles)."""
        issues: List[Dict[str, Any]] = []

        for pair, ohlcv in data.items():
            if ohlcv is None:
                continue

            closes = ohlcv.get("close")
            if not isinstance(closes, (list, tuple)) or len(closes) < 2:
                continue

            # Detect price outliers: close > 5x previous close
            outliers = []
            for i in range(1, len(closes)):
                prev = closes[i - 1]
                curr = closes[i]
                if (
                    prev is not None and curr is not None
                    and prev > 0
                    and curr > 5 * prev
                ):
                    outliers.append(i)

            if outliers:
                issues.append({
                    "issue_id": f"price_outlier_{pair}",
                    "severity": "error",
                    "description": (
                        f"{pair}: {len(outliers)} bar(s) with close > 5x previous close"
                    ),
                    "context": {"pair": pair, "bar_indices": outliers},
                })

            # Detect suspiciously flat prices: all closes identical
            non_none = [c for c in closes if c is not None]
            if len(non_none) > 1 and len(set(non_none)) == 1:
                issues.append({
                    "issue_id": f"flat_prices_{pair}",
                    "severity": "warning",
                    "description": f"{pair}: all {len(non_none)} close prices are identical",
                    "context": {"pair": pair, "value": non_none[0]},
                })

        return issues

    def _build_result(self, data: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        pairs_checked = sum(1 for v in data.values() if v is not None)
        active = self._active_issues()
        issues_found = len(active)
        clean = issues_found == 0
        return {
            "pairs_checked": pairs_checked,
            "issues_found": issues_found,
            "active_issues": active,
            "clean": clean,
            "summary": "All clear" if clean else f"{issues_found} issue(s) found",
        }


# ---------------------------------------------------------------------------
# DataIntegrityNode
# ---------------------------------------------------------------------------

class DataIntegrityNode(CleanerNode):
    """
    Data integrity sentinel — checks freshness, coverage, bar counts, volume,
    and timestamp continuity.

    Fast checks (every cycle):
      - Freshness: flag if data older than 10 minutes
      - Coverage: flag if fewer than 8 pairs have data
      - Bar count: flag if any pair has fewer than 30 bars

    Deep checks (every 5 cycles):
      - Volume consistency: flag if volume is 0 for > 20% of bars
      - Gap detection: flag if timestamp gaps > 2x expected interval

    Improvement arc:
      v1.0: freshness + coverage checks
      v1.1: bar count check (if iteration >= 1 or issues > 2)
      v1.2: volume + gap detection (if iteration >= 2)
    """

    FRESHNESS_THRESHOLD_SECONDS = 600   # 10 minutes
    MIN_PAIRS = 8
    MIN_BARS = 30
    MAX_ZERO_VOLUME_RATE = 0.20
    EXPECTED_INTERVAL_SECONDS = 86400   # daily bars

    def __init__(self) -> None:
        super().__init__()
        self._bar_check_enabled = False
        self._deep_checks_enabled = False

    def get_capabilities(self) -> List[str]:
        return ["check_data_integrity"]

    def describe(self) -> str:
        return (
            "Validates market data freshness, pair coverage, bar counts, "
            "volume consistency, and timestamp continuity. Produces a "
            "composite data-quality score (0.0–1.0) each cycle."
        )

    def get_state(self) -> NodeState:
        active = self._active_issues()
        health = max(0.0, 1.0 - len(active) * 0.2)
        return NodeState(
            node_id=self._node_id,
            name="DataIntegrityNode",
            version=self._version,
            health=health,
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={"active_issues": len(active)},
        )

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """
        v1.0 -> v1.1: enable bar-count checks
        v1.1 -> v1.2: enable volume + gap detection
        """
        iteration = feedback.get("iteration", 0)
        active_count = len(self._active_issues())
        changed = False

        if self._version == "1.0":
            if iteration >= 1 or active_count > 2:
                self._version = "1.1"
                self._bar_check_enabled = True
                changed = True

        if self._version == "1.1" and iteration >= 2:
            self._version = "1.2"
            self._deep_checks_enabled = True
            changed = True

        return changed

    def _fast_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # Freshness check: look for a top-level fetched_at key
        fetched_at = data.get("fetched_at")
        if fetched_at is not None:
            age = time.time() - fetched_at
            if age > self.FRESHNESS_THRESHOLD_SECONDS:
                issues.append({
                    "issue_id": "data_stale",
                    "severity": "warning",
                    "description": f"Market data is {age:.0f}s old (threshold {self.FRESHNESS_THRESHOLD_SECONDS}s)",
                    "context": {"age_seconds": age},
                })

        # Coverage check
        valid_pairs = [k for k, v in data.items() if k != "fetched_at" and v is not None]
        if len(valid_pairs) < self.MIN_PAIRS:
            issues.append({
                "issue_id": "low_coverage",
                "severity": "warning",
                "description": (
                    f"Only {len(valid_pairs)} pairs have data (minimum {self.MIN_PAIRS})"
                ),
                "context": {"valid_pairs": len(valid_pairs), "min_pairs": self.MIN_PAIRS},
            })

        # Bar count check (enabled after v1.1 improvement)
        if self._bar_check_enabled:
            for pair, ohlcv in data.items():
                if pair == "fetched_at" or ohlcv is None:
                    continue
                closes = ohlcv.get("close", [])
                if isinstance(closes, (list, tuple)) and len(closes) < self.MIN_BARS:
                    issues.append({
                        "issue_id": f"low_bar_count_{pair}",
                        "severity": "warning",
                        "description": (
                            f"{pair}: only {len(closes)} bars (minimum {self.MIN_BARS})"
                        ),
                        "context": {"pair": pair, "bar_count": len(closes)},
                    })

        return issues

    def _deep_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Volume consistency + gap detection (expensive, every 5 cycles)."""
        issues: List[Dict[str, Any]] = []

        if not self._deep_checks_enabled:
            return issues

        for pair, ohlcv in data.items():
            if pair == "fetched_at" or ohlcv is None:
                continue

            # Volume consistency
            volumes = ohlcv.get("volume")
            if isinstance(volumes, (list, tuple)) and len(volumes) > 0:
                zero_count = sum(1 for v in volumes if v is not None and v == 0)
                zero_rate = zero_count / len(volumes)
                if zero_rate > self.MAX_ZERO_VOLUME_RATE:
                    issues.append({
                        "issue_id": f"zero_volume_{pair}",
                        "severity": "warning",
                        "description": (
                            f"{pair}: {zero_rate:.0%} of bars have zero volume "
                            f"(threshold {self.MAX_ZERO_VOLUME_RATE:.0%})"
                        ),
                        "context": {
                            "pair": pair,
                            "zero_rate": zero_rate,
                            "zero_count": zero_count,
                        },
                    })

            # Gap detection
            timestamps = ohlcv.get("timestamps")
            if isinstance(timestamps, (list, tuple)) and len(timestamps) > 1:
                gaps = []
                for i in range(1, len(timestamps)):
                    if timestamps[i] is None or timestamps[i - 1] is None:
                        continue
                    gap = timestamps[i] - timestamps[i - 1]
                    if gap > 2 * self.EXPECTED_INTERVAL_SECONDS:
                        gaps.append((i, gap))

                if gaps:
                    issues.append({
                        "issue_id": f"timestamp_gaps_{pair}",
                        "severity": "warning",
                        "description": (
                            f"{pair}: {len(gaps)} timestamp gap(s) > 2x expected interval"
                        ),
                        "context": {
                            "pair": pair,
                            "gap_count": len(gaps),
                            "expected_interval": self.EXPECTED_INTERVAL_SECONDS,
                        },
                    })

        return issues

    def _build_result(self, data: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        valid_pairs = [k for k, v in data.items() if k != "fetched_at" and v is not None]
        pairs_checked = len(valid_pairs)
        active = self._active_issues()

        # Freshness: pairs that have data at all are considered "fresh enough"
        # (we only flag staleness at the batch level via fetched_at)
        stale_issue = any(i["issue_id"] == "data_stale" for i in active)
        fresh_pairs = 0 if stale_issue else pairs_checked

        coverage_ok = not any(i["issue_id"] == "low_coverage" for i in active)
        bar_count_ok = not any(i["issue_id"].startswith("low_bar_count_") for i in active)

        # Data quality score: start at 1.0, penalise each active issue
        penalty_per_issue = 0.1
        dq_score = max(0.0, 1.0 - len(active) * penalty_per_issue)

        active_issue_dicts = [
            {k: v for k, v in i.items() if k != "context"}
            for i in active
        ]

        if not active:
            summary = "Data integrity OK"
        else:
            parts = []
            if stale_issue:
                parts.append("stale data")
            if not coverage_ok:
                parts.append(f"low coverage ({pairs_checked} pairs)")
            if not bar_count_ok:
                parts.append("short bar history")
            extra = len(active) - len(parts)
            if extra > 0:
                parts.append(f"{extra} other issue(s)")
            summary = "; ".join(parts) if parts else f"{len(active)} issue(s)"

        return {
            "pairs_checked": pairs_checked,
            "fresh_pairs": fresh_pairs,
            "coverage_ok": coverage_ok,
            "bar_count_ok": bar_count_ok,
            "data_quality_score": dq_score,
            "active_issues": active_issue_dicts,
            "summary": summary,
        }
