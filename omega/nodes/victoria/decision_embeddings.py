"""
omega.nodes.victoria.decision_embeddings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vectorized decision clustering for Victoria's quant ensemble.

Foundation for the "trading house of quants" vision:
  1. Embed each DecisionSnapshot as a feature vector
     (signal values + regime one-hot + geometry state + outcome)
  2. Cluster via sklearn KMeans (default k=8)
  3. Compute per-cluster win rate and PnL — high-WR = trusted patterns
  4. At decision time, find nearest historical cluster and return a conviction
     bias: positive for high-WR clusters, negative for low-WR clusters

Requires: numpy, scikit-learn (optional — degrades gracefully if absent)

Offline fit (after a completed training run):
    from omega.nodes.victoria.decision_embeddings import DecisionEmbedder
    embedder = DecisionEmbedder()
    embedder.fit_from_files(
        decisions_path="data/decision_traces/v98.jsonl",
        trades_csv="data/v98_trades.csv",
        version="v98",
    )
    embedder.save("data/v98_cluster_model.pkl")

Online inference (bias conviction at decision time):
    embedder = DecisionEmbedder.load("data/v98_cluster_model.pkl")
    bias = embedder.cluster_bias(
        signal_values={"rsi_signal": 0.4, "macd_crossover": 0.2},
        regime="normal",
        geometry={"fiedler_zscore": 0.1, "fiedler_scale": 1.0, "ricci": 0.05},
        conviction_score=0.15,
    )
    adjusted_conviction = raw_conviction * (1.0 + bias)

CLI (fit + summarise):
    python -m omega.nodes.victoria.decision_embeddings \\
        --version v98 \\
        [--decisions data/decision_traces/v98.jsonl] \\
        [--trades data/v98_trades.csv] \\
        [--clusters 8]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("omega.nodes.victoria.decision_embeddings")

# ---------------------------------------------------------------------------
# Optional heavy deps — degrade gracefully
# ---------------------------------------------------------------------------

try:
    import numpy as np

    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
    logger.warning("numpy not available — DecisionEmbedder will be a no-op")

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available — DecisionEmbedder will be a no-op")

_DEPS_AVAILABLE = _NUMPY_AVAILABLE and _SKLEARN_AVAILABLE

# ---------------------------------------------------------------------------
# Regime one-hot encoding
# ---------------------------------------------------------------------------

_KNOWN_REGIMES = ["normal", "high_vol", "crisis", "bear", "bull", "sideways", "unknown"]


def _regime_onehot(regime: str) -> list[float]:
    r = regime.lower().strip()
    return [1.0 if r == k else 0.0 for k in _KNOWN_REGIMES]


# ---------------------------------------------------------------------------
# Signal feature set
# Signal names included in the feature vector (in fixed order).
# Absent signals default to 0.0.
# ---------------------------------------------------------------------------

_SIGNAL_FEATURES = [
    "rsi_signal",
    "sma_crossover",
    "macd_crossover",
    "volume_spike",
    "fear_greed_signal",
    "funding_rate_signal",
    "ricci_curvature_signal",
    "fiedler_signal",
    "vix_signal",
    "smart_money_signal",
    "finbert_signal",
    "momentum_signal",
    "carry_signal",
    "volatility_signal",
    "trend_signal",
    "mean_reversion_signal",
]


# ---------------------------------------------------------------------------
# EmbeddingRecord — one (cycle, ticker) feature vector + outcome
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingRecord:
    """Feature vector + outcome for a single (cycle, ticker) decision."""

    cycle: int
    ticker: str
    version: str

    # Feature components
    signal_vec: list[float] = field(default_factory=list)
    """Values for each name in _SIGNAL_FEATURES (0.0 if signal absent)."""

    regime_onehot: list[float] = field(default_factory=list)
    """One-hot over _KNOWN_REGIMES."""

    geometry: list[float] = field(default_factory=list)
    """[fiedler_zscore, fiedler_scale, ricci_value]"""

    conviction_score: float = 0.0
    proposal: str = "NONE"
    """LONG / SHORT / NONE"""

    # Outcome (filled after trade join)
    pnl: float = 0.0
    win: int = -1
    """1 = win, 0 = loss, -1 = no trade (HOLD / FILTERED)"""
    traded: bool = False

    def feature_vector(self) -> list[float]:
        """Flat concatenation of all feature components."""
        return self.signal_vec + self.regime_onehot + self.geometry + [self.conviction_score]


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def _extract_signal_values(signal_traces: list[dict]) -> dict[str, float]:
    return {
        t["signal_name"]: float(t.get("raw_value", 0.0))
        for t in signal_traces
        if isinstance(t, dict)
    }


def _embed_ticker_decision(
    cycle: int,
    ticker: str,
    version: str,
    td: dict,
    snapshot: dict,
) -> EmbeddingRecord:
    """Build an EmbeddingRecord from raw TickerDecision + parent snapshot dicts."""
    signal_vals = _extract_signal_values(td.get("signal_traces", []))
    sig_vec = [signal_vals.get(s, 0.0) for s in _SIGNAL_FEATURES]

    regime = snapshot.get("regime", "unknown")
    geo = [
        float(snapshot.get("fiedler_zscore", 0.0)),
        float(snapshot.get("fiedler_scale", 1.0)),
        signal_vals.get("ricci_curvature_signal", 0.0),
    ]

    return EmbeddingRecord(
        cycle=cycle,
        ticker=ticker,
        version=version,
        signal_vec=sig_vec,
        regime_onehot=_regime_onehot(regime),
        geometry=geo,
        conviction_score=float(td.get("conviction_score", 0.0)),
        proposal=str(td.get("proposal", "NONE")),
    )


# ---------------------------------------------------------------------------
# Trade join
# ---------------------------------------------------------------------------


def _load_trades_map(trades_csv: Path) -> dict[tuple[int, str, str], float]:
    """trades CSV → {(cycle, symbol, side_upper): pnl}. Sums duplicates."""
    result: dict[tuple[int, str, str], float] = {}
    if not trades_csv.exists():
        return result
    with open(trades_csv, newline="") as f:
        for row in csv.DictReader(f):
            try:
                key = (int(row["cycle"]), row["symbol"], row["side"].upper())
                result[key] = result.get(key, 0.0) + float(row["pnl"])
            except (KeyError, ValueError):
                pass
    return result


def _attach_outcomes(records: list[EmbeddingRecord], trades_map: dict) -> None:
    """Mutate records in-place — attach pnl / win / traded from trade map."""
    for rec in records:
        if rec.proposal == "NONE":
            rec.win = -1
            rec.traded = False
            continue
        side = "LONG" if rec.proposal == "LONG" else "SHORT"
        key = (rec.cycle, rec.ticker, side)
        if key in trades_map:
            rec.pnl = trades_map[key]
            rec.win = 1 if rec.pnl > 0 else 0
            rec.traded = True
        else:
            rec.win = -1
            rec.traded = False


# ---------------------------------------------------------------------------
# ClusterStats
# ---------------------------------------------------------------------------


@dataclass
class ClusterStats:
    cluster_id: int
    n_total: int = 0
    n_traded: int = 0
    n_wins: int = 0
    total_pnl: float = 0.0
    avg_conviction: float = 0.0
    regime_dist: dict[str, int] = field(default_factory=dict)
    dominant_proposal: str = "NONE"

    @property
    def win_rate(self) -> float:
        return self.n_wins / self.n_traded if self.n_traded > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.n_traded if self.n_traded > 0 else 0.0

    @property
    def bias(self) -> float:
        """
        Conviction multiplier bias in [-0.5, +0.5].
        +0.5 → 100% WR cluster (double-trust).
        -0.5 → 0% WR cluster (half-trust).
        0.0  → 50% WR, untested, or fewer than 3 traded samples.
        """
        if self.n_traded < 3:
            return 0.0
        return (self.win_rate - 0.5) * 1.0


# ---------------------------------------------------------------------------
# JSONL loader
# ---------------------------------------------------------------------------


def _load_records(decisions_path: Path, version: str) -> list[EmbeddingRecord]:
    records: list[EmbeddingRecord] = []
    if not decisions_path.exists():
        logger.warning("DecisionEmbedder: file not found: %s", decisions_path)
        return records
    with open(decisions_path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                snapshot = json.loads(line)
                cycle = int(snapshot.get("cycle", -1))
                ver = str(snapshot.get("version", version))
                for ticker, td in snapshot.get("per_ticker", {}).items():
                    rec = _embed_ticker_decision(cycle, ticker, ver, td, snapshot)
                    records.append(rec)
            except Exception as exc:
                logger.debug("DecisionEmbedder: line %d parse error: %s", lineno, exc)
    logger.info("DecisionEmbedder: loaded %d records from %s", len(records), decisions_path)
    return records


# ---------------------------------------------------------------------------
# DecisionEmbedder — main class
# ---------------------------------------------------------------------------


class DecisionEmbedder:
    """
    KMeans-based decision cluster model for Victoria.

    fit_from_files() → fit on historical data.
    cluster_bias()   → bias conviction at inference time.
    save() / load()  → persist model to disk.

    No-ops gracefully when numpy/sklearn are unavailable.
    """

    def __init__(self, n_clusters: int = 8, random_state: int = 42) -> None:
        self.n_clusters = n_clusters
        self.random_state = random_state
        self._fitted = False
        self._cluster_stats: list[ClusterStats] = []
        self._kmeans = None
        self._scaler = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit_from_files(
        self,
        decisions_path: str | Path,
        trades_csv: str | Path | None = None,
        version: str = "",
    ) -> "DecisionEmbedder":
        """
        Fit from decisions JSONL + optional trades CSV.
        Returns self for chaining.
        """
        if not _DEPS_AVAILABLE:
            logger.warning("DecisionEmbedder.fit: numpy/sklearn unavailable — skipping")
            return self

        records = _load_records(Path(decisions_path), version)
        if not records:
            logger.warning("DecisionEmbedder.fit: no records from %s", decisions_path)
            return self

        if trades_csv:
            trades_map = _load_trades_map(Path(trades_csv))
            _attach_outcomes(records, trades_map)

        return self._fit(records)

    def _fit(self, records: list[EmbeddingRecord]) -> "DecisionEmbedder":
        X = np.array([r.feature_vector() for r in records], dtype=np.float32)

        if X.shape[0] < self.n_clusters:
            logger.warning(
                "DecisionEmbedder: %d records < %d clusters — reducing k",
                X.shape[0],
                self.n_clusters,
            )
            self.n_clusters = max(2, X.shape[0] // 2)

        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        self._kmeans = KMeans(
            n_clusters=self.n_clusters,
            random_state=self.random_state,
            n_init="auto",
        )
        labels = self._kmeans.fit_predict(X_scaled)

        # Accumulate per-cluster stats
        stats: dict[int, ClusterStats] = {i: ClusterStats(cluster_id=i) for i in range(self.n_clusters)}
        proposal_counts: dict[int, dict[str, int]] = {i: {} for i in range(self.n_clusters)}

        for rec, label in zip(records, labels):
            s = stats[int(label)]
            s.n_total += 1
            s.avg_conviction = (
                s.avg_conviction * (s.n_total - 1) + rec.conviction_score
            ) / s.n_total

            if rec.regime_onehot:
                best_idx = rec.regime_onehot.index(max(rec.regime_onehot))
                regime = _KNOWN_REGIMES[best_idx]
                s.regime_dist[regime] = s.regime_dist.get(regime, 0) + 1

            pc = proposal_counts[int(label)]
            pc[rec.proposal] = pc.get(rec.proposal, 0) + 1

            if rec.traded:
                s.n_traded += 1
                s.total_pnl += rec.pnl
                if rec.win == 1:
                    s.n_wins += 1

        for i, s in stats.items():
            pc = proposal_counts[i]
            s.dominant_proposal = max(pc, key=lambda k: pc[k]) if pc else "NONE"

        self._cluster_stats = list(stats.values())
        self._fitted = True
        logger.info(
            "DecisionEmbedder: fitted %d clusters from %d records",
            self.n_clusters,
            len(records),
        )
        self._log_cluster_summary()
        return self

    def _log_cluster_summary(self) -> None:
        for s in sorted(self._cluster_stats, key=lambda x: x.win_rate, reverse=True):
            logger.info(
                "  Cluster %d: %dT %dW %.0f%% WR avg_pnl=$%.2f bias=%.2f [%s]",
                s.cluster_id,
                s.n_traded,
                s.n_wins,
                s.win_rate * 100,
                s.avg_pnl,
                s.bias,
                s.dominant_proposal,
            )

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def cluster_bias(
        self,
        signal_values: dict[str, float],
        regime: str,
        geometry: dict[str, float] | None = None,
        conviction_score: float = 0.0,
    ) -> float:
        """
        Return a conviction bias in [-0.5, +0.5].

        Usage:
            adjusted = raw_conviction * (1.0 + bias)

        Returns 0.0 (no adjustment) when:
          - model not fitted
          - numpy/sklearn unavailable
          - nearest cluster has < 3 traded samples
        """
        if not self._fitted or not _DEPS_AVAILABLE:
            return 0.0

        geo = geometry or {}
        sig_vec = [signal_values.get(s, 0.0) for s in _SIGNAL_FEATURES]
        regime_oh = _regime_onehot(regime)
        geo_vec = [
            float(geo.get("fiedler_zscore", 0.0)),
            float(geo.get("fiedler_scale", 1.0)),
            float(geo.get("ricci", 0.0)),
        ]
        feature = sig_vec + regime_oh + geo_vec + [conviction_score]

        X = np.array([feature], dtype=np.float32)
        X_scaled = self._scaler.transform(X)
        label = int(self._kmeans.predict(X_scaled)[0])
        return self._cluster_stats[label].bias

    def nearest_cluster(
        self,
        signal_values: dict[str, float],
        regime: str,
        geometry: dict[str, float] | None = None,
        conviction_score: float = 0.0,
    ) -> ClusterStats | None:
        """Return the full ClusterStats for the nearest historical cluster, or None."""
        if not self._fitted or not _DEPS_AVAILABLE:
            return None
        geo = geometry or {}
        sig_vec = [signal_values.get(s, 0.0) for s in _SIGNAL_FEATURES]
        regime_oh = _regime_onehot(regime)
        geo_vec = [
            float(geo.get("fiedler_zscore", 0.0)),
            float(geo.get("fiedler_scale", 1.0)),
            float(geo.get("ricci", 0.0)),
        ]
        feature = sig_vec + regime_oh + geo_vec + [conviction_score]
        X = np.array([feature], dtype=np.float32)
        X_scaled = self._scaler.transform(X)
        label = int(self._kmeans.predict(X_scaled)[0])
        return self._cluster_stats[label]

    def cluster_stats_summary(self) -> list[dict]:
        """JSON-serialisable cluster stats for dashboard / reporting."""
        return [
            {
                "cluster_id": s.cluster_id,
                "n_total": s.n_total,
                "n_traded": s.n_traded,
                "n_wins": s.n_wins,
                "win_rate": round(s.win_rate, 3),
                "total_pnl": round(s.total_pnl, 2),
                "avg_pnl": round(s.avg_pnl, 2),
                "avg_conviction": round(s.avg_conviction, 3),
                "dominant_proposal": s.dominant_proposal,
                "bias": round(s.bias, 3),
                "regime_dist": s.regime_dist,
            }
            for s in self._cluster_stats
        ]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        if not self._fitted:
            logger.warning("DecisionEmbedder.save: not fitted — nothing to save")
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "n_clusters": self.n_clusters,
                    "random_state": self.random_state,
                    "cluster_stats": self._cluster_stats,
                    "kmeans": self._kmeans,
                    "scaler": self._scaler,
                },
                f,
            )
        logger.info("DecisionEmbedder: saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "DecisionEmbedder":
        if not _DEPS_AVAILABLE:
            logger.warning("DecisionEmbedder.load: deps unavailable — returning unfitted instance")
            return cls()
        with open(path, "rb") as f:
            d = pickle.load(f)
        embedder = cls(n_clusters=d["n_clusters"], random_state=d["random_state"])
        embedder._cluster_stats = d["cluster_stats"]
        embedder._kmeans = d["kmeans"]
        embedder._scaler = d["scaler"]
        embedder._fitted = True
        logger.info(
            "DecisionEmbedder: loaded from %s (%d clusters)", path, embedder.n_clusters
        )
        return embedder


# ---------------------------------------------------------------------------
# Auto-detection helper
# ---------------------------------------------------------------------------


def _find_decisions_auto(version: str) -> Path | None:
    candidates = [
        Path(f"/tmp/{version}_decisions.jsonl"),
        Path(f"data/decision_traces/{version}.jsonl"),
        Path(f"data/decision_traces/{version}_decisions.jsonl"),
        Path(f"data/{version}_decisions.jsonl"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Fit decision cluster model from Victoria training run"
    )
    parser.add_argument("--version", required=True, help="Training version e.g. v98")
    parser.add_argument("--decisions", help="Path to decisions JSONL")
    parser.add_argument("--trades", help="Path to trades CSV")
    parser.add_argument("--out", help="Output model path (default: data/{version}_cluster_model.pkl)")
    parser.add_argument("--clusters", type=int, default=8, help="Number of KMeans clusters")
    args = parser.parse_args()

    version = args.version
    decisions = (
        Path(args.decisions) if args.decisions else _find_decisions_auto(version)
    )
    trades = (
        Path(args.trades) if args.trades else Path(f"data/{version}_trades.csv")
    )
    out = Path(args.out) if args.out else Path(f"data/{version}_cluster_model.pkl")

    if decisions is None:
        print(f"ERROR: could not find decisions JSONL for {version}")
        print("Searched: /tmp/{v}_decisions.jsonl, data/decision_traces/{v}.jsonl")
        return

    embedder = DecisionEmbedder(n_clusters=args.clusters)
    embedder.fit_from_files(decisions, trades, version)

    if embedder._fitted:
        embedder.save(out)
        print(f"\nCluster model saved to: {out}")
        print(json.dumps(embedder.cluster_stats_summary(), indent=2))
    else:
        print("Fitting failed — check logs (missing numpy/sklearn or empty JSONL?)")


if __name__ == "__main__":
    main()
