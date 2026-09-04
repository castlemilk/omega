"""
Tests for omega.core.project_config
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omega.core.node_registry import reset_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    reset_registry()
    yield
    reset_registry()


# ---------------------------------------------------------------------------
# ProjectConfig — from_dict
# ---------------------------------------------------------------------------


class TestProjectConfigFromDict:
    def _minimal(self):
        return {
            "name": "test_proj",
            "description": "A test project",
            "nodes": [
                {"type": "data_provider", "name": "feed", "config": {}},
                {
                    "type": "signal_generator",
                    "name": "signals",
                    "inputs": ["feed.market_data"],
                    "config": {"signals": ["basic"]},
                },
            ],
            "routing": {"type": "dag", "config": {}},
        }

    def test_basic_load(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict(self._minimal())
        assert config.name == "test_proj"
        assert len(config.nodes) == 2

    def test_node_def_fields(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict(self._minimal())
        signals_node = config.get_node("signals")
        assert signals_node is not None
        assert signals_node.type == "signal_generator"
        assert signals_node.inputs == ["feed.market_data"]
        assert signals_node.config == {"signals": ["basic"]}

    def test_default_routing(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict({"name": "x", "nodes": []})
        assert config.routing.type == "dag"

    def test_get_node_not_found(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict(self._minimal())
        assert config.get_node("nonexistent") is None

    def test_nodes_by_type(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict(self._minimal())
        signal_nodes = config.nodes_by_type("signal_generator")
        assert len(signal_nodes) == 1
        assert signal_nodes[0].name == "signals"


# ---------------------------------------------------------------------------
# Topological ordering
# ---------------------------------------------------------------------------


class TestTopologicalOrder:
    def test_simple_linear_chain(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict({
            "name": "chain",
            "nodes": [
                {"type": "data_provider", "name": "A", "inputs": []},
                {"type": "signal_generator", "name": "B", "inputs": ["A.market_data"]},
                {"type": "strategy", "name": "C", "inputs": ["B.signal_value"]},
            ],
        })
        order = config.topological_order()
        names = [nd.name for nd in order]
        assert names.index("A") < names.index("B")
        assert names.index("B") < names.index("C")

    def test_diamond_dependency(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict({
            "name": "diamond",
            "nodes": [
                {"type": "data_provider", "name": "root", "inputs": []},
                {"type": "signal_generator", "name": "left", "inputs": ["root.market_data"]},
                {"type": "signal_generator", "name": "right", "inputs": ["root.market_data"]},
                {"type": "strategy", "name": "sink",
                 "inputs": ["left.signal_value", "right.signal_value"]},
            ],
        })
        order = config.topological_order()
        names = [nd.name for nd in order]
        assert names.index("root") < names.index("left")
        assert names.index("root") < names.index("right")
        assert names.index("left") < names.index("sink")
        assert names.index("right") < names.index("sink")

    def test_cycle_raises(self):
        from omega.core.project_config import ProjectConfig

        config = ProjectConfig.from_dict({
            "name": "cyclic",
            "nodes": [
                {"type": "signal_generator", "name": "A", "inputs": ["B.signal_value"]},
                {"type": "signal_generator", "name": "B", "inputs": ["A.signal_value"]},
            ],
        })
        with pytest.raises(ValueError, match="Cycle"):
            config.topological_order()


# ---------------------------------------------------------------------------
# ProjectLoader — validation
# ---------------------------------------------------------------------------


class TestProjectLoaderValidation:
    def test_valid_project_passes(self):
        import omega.core.node_registry  # ensure built-ins are registered  # noqa
        from omega.core.project_config import ProjectLoader

        loader = ProjectLoader()
        config = loader.load_from_dict({
            "name": "valid",
            "nodes": [
                {"type": "data_provider", "name": "feed"},
                {
                    "type": "signal_generator",
                    "name": "sig",
                    "inputs": ["feed.market_data"],
                    "config": {"signals": ["basic"]},
                },
            ],
        })
        errors = loader.validate(config)
        assert errors == [], errors

    def test_unknown_node_type_error(self):
        import omega.core.node_registry  # noqa
        from omega.core.project_config import ProjectLoader

        loader = ProjectLoader()
        config = loader.load_from_dict({
            "name": "bad",
            "nodes": [
                {"type": "unicorn_node", "name": "rainbow"},
            ],
        })
        errors = loader.validate(config)
        assert any("unicorn_node" in e for e in errors)

    def test_duplicate_name_error(self):
        import omega.core.node_registry  # noqa
        from omega.core.project_config import ProjectLoader

        loader = ProjectLoader()
        config = loader.load_from_dict({
            "name": "dupes",
            "nodes": [
                {"type": "data_provider", "name": "feed"},
                {"type": "data_provider", "name": "feed"},
            ],
        })
        errors = loader.validate(config)
        assert any("Duplicate" in e and "feed" in e for e in errors)

    def test_missing_source_connection_error(self):
        import omega.core.node_registry  # noqa
        from omega.core.project_config import ProjectLoader

        loader = ProjectLoader()
        config = loader.load_from_dict({
            "name": "missing_src",
            "nodes": [
                {
                    "type": "signal_generator",
                    "name": "sig",
                    "inputs": ["ghost_node.market_data"],
                },
            ],
        })
        errors = loader.validate(config)
        assert any("ghost_node" in e for e in errors)


# ---------------------------------------------------------------------------
# ProjectLoader — load from file
# ---------------------------------------------------------------------------


class TestProjectLoaderFileLoad:
    def test_load_victoria_yaml(self):
        import omega.core.node_registry  # noqa
        from omega.core.project_config import ProjectLoader

        # Find victoria.yaml relative to repo root
        here = Path(__file__).parent.parent
        victoria_path = here / "projects" / "victoria.yaml"
        if not victoria_path.exists():
            pytest.skip("projects/victoria.yaml not found")

        loader = ProjectLoader()
        config = loader.load(victoria_path)
        assert config.name == "victoria"
        assert len(config.nodes) > 0

        # All node types used in victoria.yaml should be registered
        errors = loader.validate(config)
        assert errors == [], f"Victoria project has validation errors:\n" + "\n".join(errors)

    def test_load_nonexistent_raises(self):
        from omega.core.project_config import ProjectLoader

        loader = ProjectLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("/no/such/file.yaml")


# ---------------------------------------------------------------------------
# register_factory + instantiate (smoke test, no live nodes)
# ---------------------------------------------------------------------------


class TestProjectInstantiation:
    def test_instantiate_with_custom_factory(self):
        import omega.core.node_registry  # noqa
        from omega.core.project_config import NodeDef, ProjectLoader, register_factory

        sentinel = object()

        def my_factory(nd: NodeDef):
            return sentinel

        register_factory("data_provider", my_factory)

        loader = ProjectLoader()
        config = loader.load_from_dict({
            "name": "smoke",
            "nodes": [
                {"type": "data_provider", "name": "feed"},
            ],
        })
        instances = loader.instantiate(config, extra_factories={"data_provider": my_factory})
        assert instances["feed"] is sentinel

    def test_no_factory_raises(self):
        import omega.core.node_registry  # noqa
        from omega.core.project_config import ProjectLoader

        loader = ProjectLoader()
        config = loader.load_from_dict({
            "name": "no_factory",
            "nodes": [
                {"type": "data_provider", "name": "feed"},
            ],
        })
        # Override with no factories at all
        with pytest.raises((ValueError, RuntimeError)):
            loader.instantiate(config, extra_factories={"data_provider": None})
