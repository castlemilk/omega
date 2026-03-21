"""Tests for omega.nodes.skill_creator.SkillCreatorNode."""

import os
import tempfile

import pytest

from omega.core.node import NodeInput
from omega.nodes.skill_creator import SkillCreatorNode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def node_and_dir():
    """SkillCreatorNode with an isolated temp skills directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        node = SkillCreatorNode(skills_root=tmpdir)
        yield node, tmpdir


# ---------------------------------------------------------------------------
# Basic Node interface
# ---------------------------------------------------------------------------

class TestSkillCreatorNodeInterface:
    def test_get_capabilities(self, node_and_dir):
        node, _ = node_and_dir
        caps = node.get_capabilities()
        assert "create_skill" in caps
        assert "list_skills" in caps
        assert "describe_skill" in caps

    def test_get_state_structure(self, node_and_dir):
        node, _ = node_and_dir
        state = node.get_state()
        assert state.node_id
        assert state.name == "SkillCreatorNode"
        assert state.version == "1.0"
        assert state.health == 1.0
        assert "execution_count" in state.metrics
        assert "skill_count" in state.metrics

    def test_describe_returns_non_empty_string(self, node_and_dir):
        node, _ = node_and_dir
        assert len(node.describe()) > 20

    def test_unknown_action_returns_failure(self, node_and_dir):
        node, _ = node_and_dir
        out = node.execute(NodeInput(action="fly", parameters={}))
        assert not out.success
        assert out.errors

    def test_request_id_always_propagated(self, node_and_dir):
        node, _ = node_and_dir
        inp = NodeInput(action="list_skills", parameters={})
        out = node.execute(inp)
        assert out.request_id == inp.request_id

    def test_evaluate_returns_metrics(self, node_and_dir):
        node, _ = node_and_dir
        metrics = node.evaluate()
        assert "execution_count" in metrics
        assert "error_rate" in metrics
        assert "skill_count" in metrics

    def test_skill_tags_declared(self, node_and_dir):
        node, _ = node_and_dir
        assert "research" in node.skill_tags


# ---------------------------------------------------------------------------
# create_skill
# ---------------------------------------------------------------------------

class TestCreateSkill:
    def test_creates_skill_md_file(self, node_and_dir):
        node, tmpdir = node_and_dir
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={
                "name": "my-skill",
                "description": "A test skill",
                "tags": ["go", "testing"],
                "content": "# My Skill\n\nContent.",
            },
        ))
        assert out.success
        assert os.path.isfile(os.path.join(tmpdir, "my-skill", "SKILL.md"))

    def test_created_file_has_valid_frontmatter(self, node_and_dir):
        node, tmpdir = node_and_dir
        node.execute(NodeInput(
            action="create_skill",
            parameters={
                "name": "fm-skill",
                "description": "Frontmatter test",
                "tags": ["go"],
                "content": "# Content",
            },
        ))
        with open(os.path.join(tmpdir, "fm-skill", "SKILL.md")) as f:
            raw = f.read()
        assert raw.startswith("---\n")
        assert "name: fm-skill" in raw
        assert "  - go" in raw
        assert "# Content" in raw

    def test_result_contains_skill_name_and_path(self, node_and_dir):
        node, _ = node_and_dir
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "result-skill", "content": "body", "tags": ["x"]},
        ))
        assert out.success
        assert out.result["skill_name"] == "result-skill"
        assert out.result["path"].endswith("SKILL.md")

    def test_sanitises_name_with_spaces(self, node_and_dir):
        node, tmpdir = node_and_dir
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "My Skill With Spaces!", "content": "body", "tags": []},
        ))
        assert out.success
        safe = out.result["skill_name"]
        assert " " not in safe
        assert "!" not in safe
        assert os.path.isdir(os.path.join(tmpdir, safe))

    def test_sanitises_uppercase_name(self, node_and_dir):
        node, tmpdir = node_and_dir
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "GoLang", "content": "body", "tags": []},
        ))
        assert out.success
        assert out.result["skill_name"] == "golang"

    def test_missing_name_returns_failure(self, node_and_dir):
        node, _ = node_and_dir
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={"content": "body"},
        ))
        assert not out.success
        assert out.errors

    def test_missing_content_returns_failure(self, node_and_dir):
        node, _ = node_and_dir
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "no-content"},
        ))
        assert not out.success
        assert out.errors

    def test_empty_tags_uses_general_tag(self, node_and_dir):
        node, tmpdir = node_and_dir
        node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "notag-skill", "content": "body", "tags": []},
        ))
        with open(os.path.join(tmpdir, "notag-skill", "SKILL.md")) as f:
            raw = f.read()
        assert "  - general" in raw

    def test_index_refreshed_after_create(self, node_and_dir):
        node, _ = node_and_dir
        node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "fresh-skill", "description": "d", "tags": ["x"], "content": "body"},
        ))
        out = node.execute(NodeInput(action="list_skills", parameters={}))
        names = [s["name"] for s in out.result]
        assert "fresh-skill" in names


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------

class TestListSkills:
    def test_empty_initially(self, node_and_dir):
        node, _ = node_and_dir
        out = node.execute(NodeInput(action="list_skills", parameters={}))
        assert out.success
        assert out.result == []

    def test_shows_created_skills(self, node_and_dir):
        node, _ = node_and_dir
        for name in ("alpha", "beta"):
            node.execute(NodeInput(
                action="create_skill",
                parameters={"name": name, "description": name, "tags": [], "content": "body"},
            ))
        out = node.execute(NodeInput(action="list_skills", parameters={}))
        assert out.success
        names = [s["name"] for s in out.result]
        assert "alpha" in names
        assert "beta" in names

    def test_result_entries_have_expected_keys(self, node_and_dir):
        node, _ = node_and_dir
        node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "keyed", "description": "d", "tags": ["t"], "content": "c"},
        ))
        out = node.execute(NodeInput(action="list_skills", parameters={}))
        assert out.success
        entry = next(s for s in out.result if s["name"] == "keyed")
        assert "name" in entry
        assert "description" in entry
        assert "tags" in entry


# ---------------------------------------------------------------------------
# describe_skill
# ---------------------------------------------------------------------------

class TestDescribeSkill:
    def test_returns_skill_body_content(self, node_and_dir):
        node, _ = node_and_dir
        node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "detailed", "description": "d", "tags": [], "content": "# Body\nHello."},
        ))
        out = node.execute(NodeInput(
            action="describe_skill",
            parameters={"name": "detailed"},
        ))
        assert out.success
        assert "# Body" in out.result
        assert "Hello." in out.result

    def test_strips_frontmatter_from_result(self, node_and_dir):
        node, _ = node_and_dir
        node.execute(NodeInput(
            action="create_skill",
            parameters={"name": "striptest", "description": "d", "tags": [], "content": "# Content"},
        ))
        out = node.execute(NodeInput(
            action="describe_skill",
            parameters={"name": "striptest"},
        ))
        assert out.success
        assert "name: striptest" not in out.result

    def test_unknown_skill_returns_failure(self, node_and_dir):
        node, _ = node_and_dir
        out = node.execute(NodeInput(
            action="describe_skill",
            parameters={"name": "does-not-exist"},
        ))
        assert not out.success
        assert out.errors


# ---------------------------------------------------------------------------
# improve
# ---------------------------------------------------------------------------

class TestImprove:
    def test_improve_returns_false_when_no_new_skills(self, node_and_dir):
        node, _ = node_and_dir
        assert not node.improve({})

    def test_improve_returns_true_after_external_skill_added(self, node_and_dir):
        node, tmpdir = node_and_dir
        # Add a skill externally (bypass the node)
        os.makedirs(os.path.join(tmpdir, "external-skill"))
        with open(os.path.join(tmpdir, "external-skill", "SKILL.md"), "w") as f:
            f.write("---\nname: external-skill\ndescription: d\ntags:\n  - x\n---\n\n# Content\n")
        # improve() should detect the new skill
        assert node.improve({})


# ---------------------------------------------------------------------------
# Integration: consult_brain wiring
# ---------------------------------------------------------------------------

class TestConsultBrainIntegration:
    def test_consult_brain_returns_pass_with_no_brain(self, node_and_dir):
        """Default NoBrain: action='pass', zero latency, no API calls."""
        node, _ = node_and_dir
        response = node.consult_brain("improve")
        assert response.action == "pass"

    def test_consult_brain_skill_hints_populated(self, node_and_dir):
        """skill_hints in BrainRequest should reflect node.skill_tags."""
        from unittest.mock import MagicMock

        from omega.core.brain import BrainRequest

        node, _ = node_and_dir
        captured: list[BrainRequest] = []

        mock_brain = MagicMock()
        mock_brain.think.side_effect = lambda req: (captured.append(req), __import__("omega.core.brain", fromlist=["BrainResponse"]).BrainResponse(action="pass"))[1]
        node.brain = mock_brain

        node.consult_brain("evaluate")

        assert captured
        assert captured[0].skill_hints == ["research"]
