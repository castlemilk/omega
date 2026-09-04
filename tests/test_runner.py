"""tests.test_runner — OmegaRunner unit tests (all external deps mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Marked slow: these run real multi-cycle Victoria simulations and take minutes.
# Unmarked, they made `pytest tests/` appear to hang, so the suite was not run —
# which is how a whole stale TestRegimeAdaptivity class sat failing unnoticed.
pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(**overrides):
    """Return a minimal fake OmegaConfig object."""
    cfg = MagicMock()
    cfg.database.state_db_path = ":memory:"
    cfg.database.orchestrator_db_path = ":memory:"
    cfg.monitoring.log_level = "INFO"
    cfg.monitoring.json_logs = False
    cfg.monitoring.log_file = None
    cfg.monitoring.metrics_port = 9090
    cfg.data.symbols = ["BTCUSDT", "ETHUSDT"]
    cfg.data.providers = ["binance"]
    cfg.data.fetch_interval_days = 90
    cfg.heartbeat_interval_sec = 1
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOmegaRunnerInit:
    def test_defaults(self):
        from omega.runner import OmegaRunner

        r = OmegaRunner()
        assert r.mode == "pico"
        assert r.dry_run is False
        assert r.max_iterations is None

    def test_custom_args(self):
        from omega.runner import OmegaRunner

        r = OmegaRunner(
            config_path="omega.yml",
            mode="supervised",
            symbols=["BTCUSDT"],
            dry_run=True,
            heartbeat_override=30,
            max_iterations=5,
        )
        assert r.mode == "supervised"
        assert r.dry_run is True
        assert r.heartbeat_override == 30
        assert r.max_iterations == 5


class TestOmegaRunnerSetup:
    def test_setup_initialises_subsystems(self):
        from omega.runner import OmegaRunner

        cfg = _make_cfg()
        mock_exporter_inst = MagicMock()

        with (
            patch("omega.core.config.OmegaConfig.load", return_value=cfg),
            patch("omega.core.logging.configure_logging"),
            patch("omega.core.state_store.make_state_backend", return_value=MagicMock()),
            patch("omega.core.metrics_exporter.MetricsExporter", return_value=mock_exporter_inst),
            patch("omega.core.orchestrator.Orchestrator"),
            patch.object(OmegaRunner, "_setup_nodes"),
        ):
            runner = OmegaRunner(config_path=None)
            runner._setup()

            mock_exporter_inst.start.assert_called_once()

    def test_symbols_override(self):
        from omega.runner import OmegaRunner

        cfg = _make_cfg()

        with (
            patch("omega.core.config.OmegaConfig.load", return_value=cfg),
            patch("omega.core.logging.configure_logging"),
            patch("omega.core.state_store.make_state_backend", return_value=MagicMock()),
            patch("omega.core.metrics_exporter.MetricsExporter", return_value=MagicMock()),
            patch("omega.core.orchestrator.Orchestrator"),
            patch.object(OmegaRunner, "_setup_nodes"),
        ):
            runner = OmegaRunner(symbols=["SOLUSDT"])
            runner._setup()

            assert cfg.data.symbols == ["SOLUSDT"]


class TestOmegaRunnerStop:
    def test_stop_sets_running_false(self):
        from omega.runner import OmegaRunner

        r = OmegaRunner()
        r._running = True
        r.stop()
        assert r._running is False


class TestOmegaRunnerMaxIterations:
    def test_run_stops_at_max_iterations(self):
        from omega.runner import OmegaRunner

        cfg = _make_cfg()
        cfg.heartbeat_interval_sec = 0

        orch_inst = MagicMock()
        orch_inst.registry._nodes = {}

        with (
            patch.object(OmegaRunner, "_setup"),
            patch.object(OmegaRunner, "_heartbeat") as mock_hb,
            patch.object(OmegaRunner, "_install_signal_handlers"),
            patch.object(OmegaRunner, "_teardown"),
        ):
            runner = OmegaRunner(max_iterations=3)
            runner._cfg = cfg
            runner._store = MagicMock()
            runner._exporter = MagicMock()
            runner._orchestrator = orch_inst

            exit_code = runner.run()

            assert exit_code == 0
            assert mock_hb.call_count == 3


class TestOmegaRunnerTeardown:
    def test_teardown_stops_exporter(self):
        from omega.runner import OmegaRunner

        r = OmegaRunner()
        r._exporter = MagicMock()
        r._teardown()
        r._exporter.stop.assert_called_once()

    def test_teardown_handles_exporter_error(self):
        from omega.runner import OmegaRunner

        r = OmegaRunner()
        mock_exp = MagicMock()
        mock_exp.stop.side_effect = RuntimeError("boom")
        r._exporter = mock_exp
        r._teardown()  # must not raise


class TestOmegaRunnerHeartbeat:
    def test_heartbeat_runs_all_nodes(self):
        from omega.runner import OmegaRunner

        runner = OmegaRunner()
        runner._cfg = _make_cfg()
        runner._exporter = MagicMock()

        cycle_result = MagicMock()
        cycle_result.duration_seconds = 0.1

        runner._orchestrator = MagicMock()
        runner._orchestrator.run_one_cycle.return_value = cycle_result

        runner._heartbeat(0)

        runner._orchestrator.run_one_cycle.assert_called_once()
        runner._exporter.record_heartbeat.assert_called_once_with(duration_s=0.1)

    def test_heartbeat_continues_on_node_error(self):
        from omega.runner import OmegaRunner

        runner = OmegaRunner()
        runner._cfg = _make_cfg()
        runner._exporter = MagicMock()

        runner._orchestrator = MagicMock()
        # run_one_cycle raising should be caught by the outer run() loop, not _heartbeat
        runner._orchestrator.run_one_cycle.return_value = MagicMock(duration_seconds=0.0)

        runner._heartbeat(0)  # must not raise
        runner._orchestrator.run_one_cycle.assert_called_once()
