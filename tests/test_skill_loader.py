"""Unit tests for omega.core.skill_loader.SkillLoader."""

import os
import tempfile
import pytest
from omega.core.skill_loader import SkillLoader, SkillMetadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SKILL_A = """\
---
name: skill-alpha
description: Alpha skill for testing
tags:
  - go
  - testing
---

# Skill Alpha

Alpha content here.
"""

SKILL_B = """\
---
name: skill-beta
description: Beta skill for testing
tags:
  - python
  - testing
---

# Skill Beta

Beta content here.
"""

SKILL_NO_FRONTMATTER = """\
# No frontmatter here

Just content without the --- delimiters.
"""


@pytest.fixture
def skills_dir():
    """Temp directory with two valid skills + edge case dirs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Skill A — go + testing
        os.makedirs(os.path.join(tmpdir, "skill-alpha"))
        with open(os.path.join(tmpdir, "skill-alpha", "SKILL.md"), "w") as f:
            f.write(SKILL_A)

        # Skill B — python + testing
        os.makedirs(os.path.join(tmpdir, "skill-beta"))
        with open(os.path.join(tmpdir, "skill-beta", "SKILL.md"), "w") as f:
            f.write(SKILL_B)

        # Dir without SKILL.md — must be ignored
        os.makedirs(os.path.join(tmpdir, "no-skill-dir"))

        # SKILL.md without frontmatter — must be ignored
        os.makedirs(os.path.join(tmpdir, "bad-skill"))
        with open(os.path.join(tmpdir, "bad-skill", "SKILL.md"), "w") as f:
            f.write(SKILL_NO_FRONTMATTER)

        # Non-directory file — must be ignored
        with open(os.path.join(tmpdir, "README.md"), "w") as f:
            f.write("not a skill")

        yield tmpdir


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestSkillLoaderDiscovery:
    def test_discovers_valid_skills(self, skills_dir):
        loader = SkillLoader(skills_dir)
        names = {m.name for m in loader.list_all()}
        assert "skill-alpha" in names
        assert "skill-beta" in names

    def test_ignores_dirs_without_skill_md(self, skills_dir):
        loader = SkillLoader(skills_dir)
        names = {m.name for m in loader.list_all()}
        assert "no-skill-dir" not in names

    def test_ignores_skill_md_without_frontmatter(self, skills_dir):
        loader = SkillLoader(skills_dir)
        names = {m.name for m in loader.list_all()}
        assert "bad-skill" not in names

    def test_nonexistent_root_returns_empty(self):
        loader = SkillLoader("/nonexistent/path/to/skills")
        assert loader.list_all() == []

    def test_metadata_tags_parsed_correctly(self, skills_dir):
        loader = SkillLoader(skills_dir)
        meta = {m.name: m for m in loader.list_all()}
        assert "go" in meta["skill-alpha"].tags
        assert "testing" in meta["skill-alpha"].tags
        assert "python" in meta["skill-beta"].tags

    def test_metadata_description_parsed(self, skills_dir):
        loader = SkillLoader(skills_dir)
        meta = {m.name: m for m in loader.list_all()}
        assert meta["skill-alpha"].description == "Alpha skill for testing"
        assert meta["skill-beta"].description == "Beta skill for testing"

    def test_metadata_path_is_absolute(self, skills_dir):
        loader = SkillLoader(skills_dir)
        for m in loader.list_all():
            assert os.path.isabs(m.path)
            assert m.path.endswith("SKILL.md")


# ---------------------------------------------------------------------------
# get_skill
# ---------------------------------------------------------------------------

class TestSkillLoaderGetSkill:
    def test_returns_content_without_frontmatter(self, skills_dir):
        loader = SkillLoader(skills_dir)
        content = loader.get_skill("skill-alpha")
        assert content is not None
        assert "# Skill Alpha" in content
        assert "Alpha content here." in content
        # Frontmatter must be stripped
        assert "name: skill-alpha" not in content
        assert content.strip().startswith("#")

    def test_unknown_name_returns_none(self, skills_dir):
        loader = SkillLoader(skills_dir)
        assert loader.get_skill("does-not-exist") is None


# ---------------------------------------------------------------------------
# load_for_tags
# ---------------------------------------------------------------------------

class TestSkillLoaderLoadForTags:
    def test_single_tag_returns_matching_skill(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["go"])
        assert "Skill Alpha" in result
        assert "Skill Beta" not in result

    def test_shared_tag_returns_both_skills(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["testing"])
        assert "Skill Alpha" in result
        assert "Skill Beta" in result

    def test_deduplicates_skills_matched_by_multiple_tags(self, skills_dir):
        loader = SkillLoader(skills_dir)
        # skill-alpha matches both "go" and "testing"
        result = loader.load_for_tags(["go", "testing"])
        assert result.count("Skill Alpha") == 1

    def test_no_match_returns_empty_string(self, skills_dir):
        loader = SkillLoader(skills_dir)
        assert loader.load_for_tags(["rust", "haskell"]) == ""

    def test_empty_tags_returns_empty_string(self, skills_dir):
        loader = SkillLoader(skills_dir)
        assert loader.load_for_tags([]) == ""

    def test_result_includes_skill_name_header(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["go"])
        assert "## Skill: skill-alpha" in result

    def test_multiple_skills_separated_by_divider(self, skills_dir):
        loader = SkillLoader(skills_dir)
        result = loader.load_for_tags(["testing"])
        # Both skills matched — should be separated
        assert "---" in result


# ---------------------------------------------------------------------------
# Frontmatter edge cases
# ---------------------------------------------------------------------------

class TestSkillLoaderFrontmatterEdgeCases:
    def test_inline_tag_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "inline-skill"))
            with open(os.path.join(tmpdir, "inline-skill", "SKILL.md"), "w") as f:
                f.write("---\nname: inline-skill\ndescription: d\ntags: [go, testing]\n---\n\n# Content\n")
            loader = SkillLoader(tmpdir)
            meta = {m.name: m for m in loader.list_all()}
            assert "inline-skill" in meta
            assert "go" in meta["inline-skill"].tags
            assert "testing" in meta["inline-skill"].tags

    def test_skill_with_no_tags_still_indexed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "tagless"))
            with open(os.path.join(tmpdir, "tagless", "SKILL.md"), "w") as f:
                f.write("---\nname: tagless\ndescription: no tags\ntags:\n---\n\n# Content\n")
            loader = SkillLoader(tmpdir)
            # Should be discovered but with empty tags
            names = {m.name for m in loader.list_all()}
            assert "tagless" in names
