"""Tests for omega.core.config — centralized configuration loading."""

import os
import tempfile

import pytest

from omega.core.config import (
    AdversarialConfig,
    AlignmentConfig,
    DatabaseConfig,
    DataConfig,
    MonitoringConfig,
    NodesConfig,
    OmegaConfig,
)


class TestDefaults:
    def test_database_defaults(self):
        cfg = DatabaseConfig()
        assert cfg.state_db_path == "/tmp/omega_vectora_state.db"
        assert cfg.memory_db_path == "/tmp/omega_vectora_memory.db"

    def test_nodes_defaults(self):
        cfg = NodesConfig()
        assert cfg.brain_provider == "none"
        assert cfg.brain_temperature == 0.7
        assert cfg.ollama_host == "http://localhost:11434"

    def test_data_defaults_include_ten_symbols(self):
        cfg = DataConfig()
        assert len(cfg.symbols) == 10
        assert "BTCUSDT" in cfg.symbols

    def test_monitoring_defaults(self):
        cfg = MonitoringConfig()
        assert cfg.log_level == "INFO"
        assert cfg.json_logs is True
        assert cfg.metrics_port == 9090

    def test_alignment_defaults(self):
        cfg = AlignmentConfig()
        assert cfg.health_threshold == 0.6

    def test_adversarial_defaults(self):
        cfg = AdversarialConfig()
        assert cfg.active_rings == []
        assert cfg.veto_threshold == 0.8


class TestFromEnv:
    def test_loads_db_paths_from_env(self, monkeypatch):
        monkeypatch.setenv("OMEGA_STATE_DB_PATH", "/data/state.db")
        monkeypatch.setenv("OMEGA_MEMORY_DB_PATH", "/data/memory.db")
        cfg = OmegaConfig.from_env()
        assert cfg.database.state_db_path == "/data/state.db"
        assert cfg.database.memory_db_path == "/data/memory.db"

    def test_loads_brain_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("OMEGA_BRAIN_PROVIDER", "anthropic")
        monkeypatch.setenv("OMEGA_BRAIN_MODEL", "claude-sonnet-4-6")
        cfg = OmegaConfig.from_env()
        assert cfg.nodes.brain_provider == "anthropic"
        assert cfg.nodes.brain_model == "claude-sonnet-4-6"

    def test_loads_api_keys_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
        cfg = OmegaConfig.from_env()
        assert cfg.nodes.anthropic_api_key == "sk-test-key"
        assert cfg.nodes.openai_api_key == "openai-test"

    def test_loads_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("OMEGA_LOG_LEVEL", "DEBUG")
        cfg = OmegaConfig.from_env()
        assert cfg.monitoring.log_level == "DEBUG"

    def test_json_logs_false_from_env(self, monkeypatch):
        monkeypatch.setenv("OMEGA_JSON_LOGS", "false")
        cfg = OmegaConfig.from_env()
        assert cfg.monitoring.json_logs is False

    def test_json_logs_true_from_env(self, monkeypatch):
        for val in ("true", "1", "yes", "TRUE"):
            monkeypatch.setenv("OMEGA_JSON_LOGS", val)
            cfg = OmegaConfig.from_env()
            assert cfg.monitoring.json_logs is True

    def test_loads_health_threshold_from_env(self, monkeypatch):
        monkeypatch.setenv("OMEGA_HEALTH_THRESHOLD", "0.75")
        cfg = OmegaConfig.from_env()
        assert cfg.alignment.health_threshold == pytest.approx(0.75)

    def test_loads_symbols_from_env(self, monkeypatch):
        monkeypatch.setenv("OMEGA_SYMBOLS", "BTCUSDT,ETHUSDT")
        cfg = OmegaConfig.from_env()
        assert cfg.data.symbols == ["BTCUSDT", "ETHUSDT"]

    def test_empty_symbols_env_uses_defaults(self, monkeypatch):
        monkeypatch.setenv("OMEGA_SYMBOLS", "")
        cfg = OmegaConfig.from_env()
        assert len(cfg.data.symbols) == 10

    def test_adversarial_rings_from_env(self, monkeypatch):
        monkeypatch.setenv("OMEGA_ADVERSARIAL_RINGS", "ring-a,ring-b")
        cfg = OmegaConfig.from_env()
        assert cfg.adversarial.active_rings == ["ring-a", "ring-b"]

    def test_missing_env_uses_defaults(self, monkeypatch):
        # Clear relevant env vars
        for key in ("OMEGA_BRAIN_PROVIDER", "OMEGA_HEALTH_THRESHOLD", "OMEGA_LOG_LEVEL"):
            monkeypatch.delenv(key, raising=False)
        cfg = OmegaConfig.from_env()
        assert cfg.nodes.brain_provider == "none"
        assert cfg.alignment.health_threshold == pytest.approx(0.6)
        assert cfg.monitoring.log_level == "INFO"


class TestFromYaml:
    def test_yaml_overrides_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OMEGA_LOG_LEVEL", "DEBUG")
        yaml_file = tmp_path / "omega.yml"
        yaml_file.write_text(
            "monitoring:\n  log_level: WARNING\n"
        )
        # Only run if PyYAML is installed
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("PyYAML not installed")

        cfg = OmegaConfig.from_yaml(str(yaml_file))
        assert cfg.monitoring.log_level == "WARNING"

    def test_yaml_unknown_keys_ignored(self, tmp_path):
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("PyYAML not installed")

        yaml_file = tmp_path / "omega.yml"
        yaml_file.write_text(
            "monitoring:\n  unknown_future_key: blah\n"
        )
        cfg = OmegaConfig.from_yaml(str(yaml_file))
        assert cfg.monitoring.log_level == "INFO"  # default preserved

    def test_yaml_db_paths_override(self, tmp_path):
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("PyYAML not installed")

        yaml_file = tmp_path / "omega.yml"
        yaml_file.write_text(
            "database:\n"
            "  state_db_path: /custom/state.db\n"
            "  memory_db_path: /custom/memory.db\n"
        )
        cfg = OmegaConfig.from_yaml(str(yaml_file))
        assert cfg.database.state_db_path == "/custom/state.db"
        assert cfg.database.memory_db_path == "/custom/memory.db"


class TestLoad:
    def test_load_without_yaml_uses_env(self, monkeypatch):
        monkeypatch.delenv("OMEGA_CONFIG", raising=False)
        monkeypatch.setenv("OMEGA_LOG_LEVEL", "ERROR")
        cfg = OmegaConfig.load()
        assert cfg.monitoring.log_level == "ERROR"

    def test_load_with_omega_config_env(self, monkeypatch, tmp_path):
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("PyYAML not installed")

        yaml_file = tmp_path / "omega.yml"
        yaml_file.write_text("monitoring:\n  log_level: WARNING\n")
        monkeypatch.setenv("OMEGA_CONFIG", str(yaml_file))
        cfg = OmegaConfig.load()
        assert cfg.monitoring.log_level == "WARNING"


class TestValidate:
    def test_valid_config_passes(self):
        cfg = OmegaConfig.load.__func__(OmegaConfig)  # call classmethod directly
        cfg = OmegaConfig.from_env()
        cfg.validate()  # should not raise

    def test_invalid_health_threshold_raises(self):
        cfg = OmegaConfig.from_env()
        cfg.alignment.health_threshold = 1.5
        with pytest.raises(ValueError, match="health_threshold"):
            cfg.validate()

    def test_invalid_metrics_port_raises(self):
        cfg = OmegaConfig.from_env()
        cfg.monitoring.metrics_port = 99999
        with pytest.raises(ValueError, match="metrics_port"):
            cfg.validate()

    def test_invalid_temperature_raises(self):
        cfg = OmegaConfig.from_env()
        cfg.nodes.brain_temperature = 3.0
        with pytest.raises(ValueError, match="brain_temperature"):
            cfg.validate()


class TestDumpToLog:
    def test_dump_does_not_raise(self):
        cfg = OmegaConfig.from_env()
        cfg.dump_to_log()  # should not raise

    def test_dump_masks_api_keys(self, caplog):
        import logging
        cfg = OmegaConfig.from_env()
        cfg.nodes.anthropic_api_key = "real-secret-key"
        with caplog.at_level(logging.INFO, logger="omega.core.config"):
            cfg.dump_to_log()
        # The raw key should not appear in any log message
        for record in caplog.records:
            assert "real-secret-key" not in record.getMessage()
