"""
omega.core.config
~~~~~~~~~~~~~~~~~
Centralized configuration for the Omega framework.

Priority (highest → lowest):
  1. YAML file values  (when ``omega.yml`` or ``OMEGA_CONFIG`` is set)
  2. Environment variables
  3. Built-in defaults

Usage::

    from omega.core.config import OmegaConfig

    # Load from env only
    cfg = OmegaConfig.load()

    # Load from env + YAML override
    cfg = OmegaConfig.load("omega.yml")

    # Validate and log on startup
    cfg.validate()
    cfg.dump_to_log()

Sections
--------
  cfg.database    — SQLite file paths
  cfg.nodes       — brain provider, API keys, model params
  cfg.data        — trading pairs, provider URLs
  cfg.monitoring  — log level, JSON logs, metrics port, API URL
  cfg.alignment   — health threshold, improvement cadence
  cfg.adversarial — active rings, veto threshold
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.core.config")


def _db_path(filename: str) -> str:
    """Resolve a DB filename against OMEGA_DATA_DIR (default: ./data)."""
    data_dir = os.environ.get("OMEGA_DATA_DIR", "./data")
    return os.path.join(data_dir, filename)


# Optional YAML support — fail gracefully if PyYAML is not installed
_YAML_AVAILABLE = False
try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Section dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DatabaseConfig:
    """SQLite database file paths."""

    state_db_path: str = field(default_factory=lambda: _db_path("omega_victoria_state.db"))
    """Node registry, executions, traces, issues, costs, improvements."""

    memory_db_path: str = field(default_factory=lambda: _db_path("omega_victoria_memory.db"))
    """Episodic + semantic memory (MemoryKernel)."""

    orchestrator_db_path: str = field(default_factory=lambda: _db_path("omega_victoria.db"))
    """Orchestrator internal state."""

    def ensure_dirs(self) -> None:
        """Create parent directories for all configured DB paths."""
        for path in (self.state_db_path, self.memory_db_path, self.orchestrator_db_path):
            dir_ = os.path.dirname(path)
            if dir_:
                os.makedirs(dir_, exist_ok=True)


@dataclass
class NodesConfig:
    """Brain and node-level configuration."""

    brain_provider: str = "none"
    """Active LLM provider: ``"anthropic" | "openai" | "deepseek" | "ollama" | "none"``."""

    brain_model: str = ""
    """Model ID, e.g. ``"claude-sonnet-4-6"`` or ``"gpt-4o"``."""

    brain_temperature: float = 0.7
    brain_max_tokens: int = 1024

    # API keys — read from env; never hard-coded in YAML
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    google_api_key: str = ""
    ollama_host: str = "http://localhost:11434"


@dataclass
class DataConfig:
    """External data provider configuration."""

    symbols: list[str] = field(
        default_factory=lambda: [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "DOTUSDT",
            "AVAXUSDT",
            "LINKUSDT",
            "MATICUSDT",
        ]
    )

    providers: list[str] = field(default_factory=lambda: ["binance", "coingecko"])

    binance_base_url: str = "https://api.binance.com"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    fetch_interval_days: int = 90


@dataclass
class MonitoringConfig:
    """Observability configuration."""

    log_level: str = "INFO"
    """``"DEBUG" | "INFO" | "WARNING" | "ERROR"``."""

    json_logs: bool = True
    """Emit JSON lines to stdout (12-factor style)."""

    log_file: str | None = None
    """Optional secondary log file path."""

    metrics_port: int = 9090
    """Prometheus-style metrics exposition port (future use)."""

    api_base_url: str = "http://localhost:8080"
    """Base URL of the Go Connect-RPC API (used by DashboardNode)."""


@dataclass
class AlignmentConfig:
    """Alignment system thresholds."""

    health_threshold: float = 0.6
    """Node health score below which self-improvement is triggered."""

    improvement_interval: int = 3
    """Minimum cycles between forced improvement attempts per node."""

    max_improvement_cycles: int = 10
    """Maximum improvement cycles before giving up."""


@dataclass
class AdversarialConfig:
    """Adversarial ring configuration."""

    active_rings: list[str] = field(default_factory=list)
    """List of active adversarial ring names."""

    veto_threshold: float = 0.8
    """Confidence threshold above which a challenge veto takes effect."""

    challenge_timeout_sec: float = 5.0
    """Maximum seconds a challenge ring can hold up execution."""


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


@dataclass
class OmegaConfig:
    """Root configuration object for the Omega framework.

    Build via :meth:`load` (preferred) or the :meth:`from_env` /
    :meth:`from_yaml` class methods.
    """

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    nodes: NodesConfig = field(default_factory=NodesConfig)
    data: DataConfig = field(default_factory=DataConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    alignment: AlignmentConfig = field(default_factory=AlignmentConfig)
    adversarial: AdversarialConfig = field(default_factory=AdversarialConfig)

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> OmegaConfig:
        """Build config entirely from environment variables."""
        _e = os.environ.get

        database = DatabaseConfig(
            state_db_path=_e("OMEGA_STATE_DB_PATH") or _db_path("omega_victoria_state.db"),
            memory_db_path=_e("OMEGA_MEMORY_DB_PATH") or _db_path("omega_victoria_memory.db"),
            orchestrator_db_path=_e("OMEGA_DB_PATH") or _db_path("omega_victoria.db"),
        )

        nodes = NodesConfig(
            brain_provider=_e("OMEGA_BRAIN_PROVIDER", "none"),
            brain_model=_e("OMEGA_BRAIN_MODEL", ""),
            brain_temperature=float(_e("OMEGA_BRAIN_TEMPERATURE", "0.7")),
            brain_max_tokens=int(_e("OMEGA_BRAIN_MAX_TOKENS", "1024")),
            anthropic_api_key=_e("ANTHROPIC_API_KEY", ""),
            openai_api_key=_e("OPENAI_API_KEY", ""),
            deepseek_api_key=_e("DEEPSEEK_API_KEY", ""),
            google_api_key=_e("GOOGLE_API_KEY", ""),
            ollama_host=_e("OLLAMA_HOST", "http://localhost:11434"),
        )

        raw_symbols = _e("OMEGA_SYMBOLS", "")
        symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()] or DataConfig().symbols

        raw_providers = _e("OMEGA_PROVIDERS", "")
        providers = [
            p.strip() for p in raw_providers.split(",") if p.strip()
        ] or DataConfig().providers

        data = DataConfig(
            symbols=symbols,
            providers=providers,
            fetch_interval_days=int(_e("OMEGA_FETCH_INTERVAL_DAYS", "90")),
        )

        monitoring = MonitoringConfig(
            log_level=_e("OMEGA_LOG_LEVEL", "INFO"),
            json_logs=_e("OMEGA_JSON_LOGS", "true").lower() not in ("false", "0", "no"),
            log_file=_e("OMEGA_LOG_FILE") or None,
            metrics_port=int(_e("OMEGA_METRICS_PORT", "9090")),
            api_base_url=_e("OMEGA_API_BASE_URL", "http://localhost:8080"),
        )

        alignment = AlignmentConfig(
            health_threshold=float(_e("OMEGA_HEALTH_THRESHOLD", "0.6")),
            improvement_interval=int(_e("OMEGA_IMPROVEMENT_INTERVAL", "3")),
            max_improvement_cycles=int(_e("OMEGA_MAX_IMPROVEMENT_CYCLES", "10")),
        )

        raw_rings = _e("OMEGA_ADVERSARIAL_RINGS", "")
        active_rings = [r.strip() for r in raw_rings.split(",") if r.strip()]

        adversarial = AdversarialConfig(
            active_rings=active_rings,
            veto_threshold=float(_e("OMEGA_VETO_THRESHOLD", "0.8")),
            challenge_timeout_sec=float(_e("OMEGA_CHALLENGE_TIMEOUT_SEC", "5.0")),
        )

        return cls(
            database=database,
            nodes=nodes,
            data=data,
            monitoring=monitoring,
            alignment=alignment,
            adversarial=adversarial,
        )

    @classmethod
    def from_yaml(cls, path: str) -> OmegaConfig:
        """Load config from a YAML file, merged over env-var defaults.

        YAML values take precedence over environment variables. API keys
        should still be provided via env vars, not hard-coded in YAML.

        Args:
            path: Path to the YAML config file.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ValueError: If *path* contains invalid YAML.
        """
        if not _YAML_AVAILABLE:
            logger.warning(
                "PyYAML not installed; ignoring config file %s — install with: pip install pyyaml",
                path,
            )
            return cls.from_env()

        cfg = cls.from_env()

        with open(path) as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        # Merge each section — only known fields, no silent typo acceptance
        _merge_section(cfg.database, raw.get("database", {}))
        _merge_section(cfg.nodes, raw.get("nodes", {}))
        _merge_section(cfg.data, raw.get("data", {}))
        _merge_section(cfg.monitoring, raw.get("monitoring", {}))
        _merge_section(cfg.alignment, raw.get("alignment", {}))
        _merge_section(cfg.adversarial, raw.get("adversarial", {}))

        return cfg

    @classmethod
    def load(cls, yaml_path: str | None = None) -> OmegaConfig:
        """Preferred entry point. Load from env vars + optional YAML override.

        If *yaml_path* is ``None``, checks the ``OMEGA_CONFIG`` env var for
        a file path. If neither is set, loads from env vars only.

        Args:
            yaml_path: Optional path to a YAML config file.
        """
        if yaml_path is None:
            yaml_path = os.environ.get("OMEGA_CONFIG")
        cfg = cls.from_yaml(yaml_path) if yaml_path else cls.from_env()
        cfg.database.ensure_dirs()
        return cfg

    # ------------------------------------------------------------------
    # Validation & introspection
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Validate required fields and value ranges.

        Raises:
            ValueError: If any field fails validation.
        """
        errors: list[str] = []

        if not (0.0 <= self.alignment.health_threshold <= 1.0):
            errors.append(
                f"alignment.health_threshold must be 0.0-1.0, "
                f"got {self.alignment.health_threshold}"
            )

        if not (1 <= self.monitoring.metrics_port <= 65535):
            errors.append(
                f"monitoring.metrics_port must be 1-65535, got {self.monitoring.metrics_port}"
            )

        if self.nodes.brain_temperature < 0.0 or self.nodes.brain_temperature > 2.0:
            errors.append(
                f"nodes.brain_temperature must be 0.0-2.0, got {self.nodes.brain_temperature}"
            )

        if errors:
            raise ValueError("OmegaConfig validation failed:\n  " + "\n  ".join(errors))

    def dump_to_log(self) -> None:
        """Log the active configuration at INFO level on startup.

        API keys are masked — only their presence is indicated.
        """
        safe: dict[str, Any] = {
            "database": {
                "state_db_path": self.database.state_db_path,
                "memory_db_path": self.database.memory_db_path,
                "orchestrator_db_path": self.database.orchestrator_db_path,
            },
            "monitoring": {
                "log_level": self.monitoring.log_level,
                "json_logs": self.monitoring.json_logs,
                "api_base_url": self.monitoring.api_base_url,
            },
            "alignment": {
                "health_threshold": self.alignment.health_threshold,
                "improvement_interval": self.alignment.improvement_interval,
            },
            "nodes": {
                "brain_provider": self.nodes.brain_provider,
                "brain_model": self.nodes.brain_model or "(default)",
                "anthropic_api_key": "***" if self.nodes.anthropic_api_key else "(not set)",
                "openai_api_key": "***" if self.nodes.openai_api_key else "(not set)",
                "deepseek_api_key": "***" if self.nodes.deepseek_api_key else "(not set)",
                "google_api_key": "***" if self.nodes.google_api_key else "(not set)",
                "ollama_host": self.nodes.ollama_host,
            },
            "data": {
                "symbols": self.data.symbols,
                "providers": self.data.providers,
            },
            "adversarial": {
                "active_rings": self.adversarial.active_rings,
                "veto_threshold": self.adversarial.veto_threshold,
            },
        }
        logger.info("Omega config loaded", extra={"config": safe})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _merge_section(section: Any, overrides: dict[str, Any]) -> None:
    """Apply *overrides* dict onto a config dataclass in-place.

    Unknown keys are silently skipped (avoids crashing on future-compat
    YAML files) but a debug log is emitted so they're not invisible.
    """
    for key, value in overrides.items():
        if hasattr(section, key):
            setattr(section, key, value)
        else:
            logger.debug(
                "OmegaConfig: unknown key '%s' in section %s — ignored",
                key,
                type(section).__name__,
            )
