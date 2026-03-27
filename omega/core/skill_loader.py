"""
omega.core.skill_loader
~~~~~~~~~~~~~~~~~~~~~~~
Discovers, indexes, and serves SKILL.md knowledge artifacts to nodes.

Skills live under a root directory. Each skill is a subdirectory containing
a SKILL.md file with YAML-style frontmatter:

    ---
    name: go-best-practices
    description: Go coding standards for Omega
    tags:
      - go
      - testing
    ---

    # Content here...

Usage::

    loader = SkillLoader("/path/to/omega/skills")
    content = loader.load_for_tags(["go", "protobuf"])  # -> str injected into domain_context
    loader.list_all()                                     # -> List[SkillMetadata]
    loader.get_skill("go-best-practices")                # -> str (content, no frontmatter)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class SkillMetadata:
    """Metadata parsed from a SKILL.md frontmatter block."""

    name: str
    description: str
    tags: list[str]
    path: str  # absolute path to the SKILL.md file


class SkillLoader:
    """
    Discovers, indexes, and serves SKILL.md skills by tag.

    Scans ``skills_root`` on construction. Each subdirectory containing a
    ``SKILL.md`` file with valid YAML frontmatter is indexed as a skill.

    The frontmatter parser is intentionally minimal (stdlib-only, no PyYAML):
    it handles scalar values and block lists but not deeply nested structures.
    """

    def __init__(self, skills_root: str) -> None:
        self._root = skills_root
        self._index: dict[str, SkillMetadata] = {}  # name -> metadata
        self._tag_index: dict[str, list[str]] = {}  # tag -> [skill names]
        self._discover()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """Walk skills_root and index all valid SKILL.md files."""
        if not os.path.isdir(self._root):
            return
        for entry in sorted(os.scandir(self._root), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            skill_path = os.path.join(entry.path, "SKILL.md")
            if not os.path.isfile(skill_path):
                continue
            meta = self._parse_frontmatter(skill_path)
            if meta is None:
                continue
            self._index[meta.name] = meta
            for tag in meta.tags:
                self._tag_index.setdefault(tag, []).append(meta.name)

    def _parse_frontmatter(self, path: str) -> SkillMetadata | None:
        """Parse YAML frontmatter from a SKILL.md file. Returns None if invalid."""
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return None

        match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not match:
            return None

        fm = match.group(1)
        name = self._fm_scalar(fm, "name") or os.path.basename(os.path.dirname(path))
        description = self._fm_scalar(fm, "description") or ""
        tags = self._fm_list(fm, "tags")

        return SkillMetadata(name=name, description=description, tags=tags, path=path)

    @staticmethod
    def _fm_scalar(fm: str, key: str) -> str | None:
        """Extract a scalar value: ``key: value`` → ``value``."""
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.MULTILINE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _fm_list(fm: str, key: str) -> list[str]:
        """
        Extract a YAML block list::

            tags:
              - item1
              - item2

        Falls back to inline list: ``tags: [item1, item2]``
        """
        # Block list
        block = re.search(
            rf"^{re.escape(key)}:\n((?:[ \t]+-[ \t]+.+\n?)+)",
            fm,
            re.MULTILINE,
        )
        if block:
            return [
                i.strip() for i in re.findall(r"^[ \t]+-[ \t]+(.+)$", block.group(1), re.MULTILINE)
            ]
        # Inline list
        inline = re.search(rf"^{re.escape(key)}:\s+\[(.+)\]$", fm, re.MULTILINE)
        if inline:
            return [t.strip().strip("\"'") for t in inline.group(1).split(",")]
        return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_all(self) -> list[SkillMetadata]:
        """Return metadata for all discovered skills, sorted by name."""
        return list(self._index.values())

    def get_skill(self, name: str) -> str | None:
        """
        Return the body content of a named skill (frontmatter stripped).

        Returns None if the skill is not found.
        """
        meta = self._index.get(name)
        if meta is None:
            return None
        try:
            with open(meta.path, encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return None
        return re.sub(r"^---\n.*?\n---\n", "", raw, count=1, flags=re.DOTALL).strip()

    def load_for_tags(self, tags: list[str]) -> str:
        """
        Return concatenated skill content for all skills matching any of the given tags.

        Each matching skill appears at most once (deduplicated), ordered by
        the order tags appear in the input list, then by insertion order within
        each tag bucket.

        Returns empty string if no tags match or tags list is empty.
        """
        if not tags:
            return ""

        matched_names: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            for name in self._tag_index.get(tag, []):
                if name not in seen:
                    matched_names.append(name)
                    seen.add(name)

        parts: list[str] = []
        for name in matched_names:
            content = self.get_skill(name)
            if content:
                parts.append(f"## Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts)
