"""
omega.nodes.skill_creator
~~~~~~~~~~~~~~~~~~~~~~~~~
A capability node that creates and manages SKILL.md knowledge artifacts.

SkillCreatorNode writes new skills to the omega/skills/ directory and can list
or describe existing ones. It declares ``skill_tags = ["research"]`` so that
when an LLM brain is attached, it automatically receives the deep-research
skill and applies the IterDRAG pattern when generating new skill content.

Capabilities:
  create_skill   — write a new SKILL.md for a given domain
  list_skills    — list all known skills with metadata
  describe_skill — return the content of a specific skill
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.skill_loader import SkillLoader


class SkillCreatorNode(Node):
    """
    Creates new skill documentation artifacts for the Omega skill library.

    Each skill is written to ``<skills_root>/<name>/SKILL.md`` with YAML
    frontmatter (name, description, tags) followed by the markdown body.

    After ``create_skill`` the internal SkillLoader index is refreshed, so
    subsequent ``list_skills`` / ``describe_skill`` calls reflect the new skill
    immediately without restarting the node.

    Usage::

        node = SkillCreatorNode()
        out = node.execute(NodeInput(
            action="create_skill",
            parameters={
                "name": "kubernetes",
                "description": "K8s deployment best practices",
                "tags": ["kubernetes", "devops", "go"],
                "content": "# Kubernetes\\n\\n...",
            },
        ))
        assert out.success
        print(out.result["skill_name"])   # "kubernetes"
        print(out.result["path"])         # "/path/to/omega/skills/kubernetes/SKILL.md"
    """

    skill_tags: list[str] = ["research"]

    def __init__(
        self,
        skills_root: str | None = None,
        brain_config=None,
    ) -> None:
        super().__init__(brain_config)
        if skills_root is None:
            skills_root = os.path.normpath(
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "..", "skills"
                )
            )
        self._skills_root = skills_root
        self._loader = SkillLoader(self._skills_root)
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        error_rate = self._error_count / max(1, self._execution_count)
        return NodeState(
            node_id=self._node_id,
            name="SkillCreatorNode",
            version=self._version,
            health=max(0.0, 1.0 - error_rate),
            capabilities=self.get_capabilities(),
            metrics={
                "execution_count": float(self._execution_count),
                "error_rate": error_rate,
                "skill_count": float(len(self._loader.list_all())),
            },
            metadata={"skills_root": self._skills_root},
        )

    def get_capabilities(self) -> list[str]:
        return ["create_skill", "list_skills", "describe_skill"]

    def describe(self) -> str:
        return (
            "SkillCreatorNode creates and manages SKILL.md knowledge artifacts. "
            "It writes new skills to the omega/skills/ directory, lists all existing "
            "skills with their tags, and retrieves skill content by name. "
            "Use it to bootstrap new domain knowledge for Omega nodes."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        try:
            if input.action == "create_skill":
                result = self._create_skill(input.parameters)
            elif input.action == "list_skills":
                result = self._list_skills()
            elif input.action == "describe_skill":
                result = self._describe_skill(input.parameters.get("name", ""))
            else:
                self._error_count += 1
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"SkillCreatorNode: unknown action '{input.action}'"],
                    metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
                )
            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
            )
        except Exception as exc:
            self._error_count += 1
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "execution_count": float(self._execution_count),
            "error_rate": self._error_count / max(1, self._execution_count),
            "skill_count": float(len(self._loader.list_all())),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        """Reload the skill index from disk. Returns True if the count changed."""
        old_count = len(self._loader.list_all())
        self._loader = SkillLoader(self._skills_root)
        return len(self._loader.list_all()) != old_count

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _create_skill(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write a new SKILL.md file to the skills directory."""
        name = str(params.get("name", "")).strip()
        tags: list[str] = list(params.get("tags", []))
        description = str(params.get("description", "")).strip()
        content = str(params.get("content", "")).strip()

        if not name:
            raise ValueError("'name' parameter is required")
        if not content:
            raise ValueError("'content' parameter is required")

        # Sanitise: lowercase alphanumeric + hyphens only
        safe_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not safe_name:
            raise ValueError(
                f"'name' yields an empty filesystem name after sanitisation: {name!r}"
            )

        skill_dir = os.path.join(self._skills_root, safe_name)
        os.makedirs(skill_dir, exist_ok=True)

        tags_yaml = (
            "\n".join(f"  - {t}" for t in tags) if tags else "  - general"
        )
        skill_md = (
            f"---\n"
            f"name: {safe_name}\n"
            f"description: {description}\n"
            f"tags:\n{tags_yaml}\n"
            f"---\n\n"
            f"{content}\n"
        )

        skill_path = os.path.join(skill_dir, "SKILL.md")
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skill_md)

        # Refresh index so callers see the new skill immediately
        self._loader = SkillLoader(self._skills_root)

        return {"skill_name": safe_name, "path": skill_path, "tags": tags}

    def _list_skills(self) -> list[dict[str, Any]]:
        """Return metadata for all known skills."""
        return [
            {"name": m.name, "description": m.description, "tags": m.tags}
            for m in self._loader.list_all()
        ]

    def _describe_skill(self, name: str) -> str:
        """Return body content of a named skill (frontmatter stripped)."""
        content = self._loader.get_skill(name)
        if content is None:
            raise ValueError(f"Skill '{name}' not found in {self._skills_root!r}")
        return content
