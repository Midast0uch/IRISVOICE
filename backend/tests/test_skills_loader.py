"""
Tests for SkillsLoader — Gate 2 Step 2.1
Source: bootstrap/GOALS.md Step 2.1 acceptance criteria

Key requirements:
  - load_all_skills() returns dict of skill_name → content
  - skills/ folder is read and skill-creator is found
  - New SKILL.md files are picked up on next call to load_all_skills()
  - get_skill_prompt_context() returns non-empty string containing skill names
  - extract_description() pulls description from frontmatter
  - get_skills_loader() is importable from backend.agent.skills

Run: python -m pytest backend/tests/test_skills_loader.py -v
"""

import os
import shutil
import pytest
from pathlib import Path


# ── load_all_skills — basic import and return type ───────────────────────────

def test_load_all_skills_importable():
    from backend.agent.skills.skills_loader import load_all_skills
    assert callable(load_all_skills)


def test_load_all_skills_returns_dict():
    from backend.agent.skills.skills_loader import load_all_skills
    result = load_all_skills()
    assert isinstance(result, dict)


def test_load_all_skills_finds_skill_creator():
    """The skill-creator subdirectory with SKILL.md must be found."""
    from backend.agent.skills.skills_loader import load_all_skills
    skills = load_all_skills()
    assert "skill-creator" in skills, f"skill-creator not found in {list(skills.keys())}"


def test_load_all_skills_content_is_string():
    """Each value must be a non-empty string (the SKILL.md text)."""
    from backend.agent.skills.skills_loader import load_all_skills
    skills = load_all_skills()
    for name, content in skills.items():
        assert isinstance(content, str) and len(content) > 0, \
            f"Skill '{name}' has empty or non-string content"


# ── Reload — new SKILL.md files are picked up ────────────────────────────────

def test_new_skill_picked_up_on_reload(tmp_path):
    """
    Writing a new SKILL.md into the skills/ directory and calling
    load_all_skills() again must return the new skill.
    """
    from backend.agent.skills import skills_loader as sl
    skills_dir = Path(sl.__file__).parent

    # Create a temporary skill directory
    test_skill_dir = skills_dir / "_test_reload_skill"
    try:
        test_skill_dir.mkdir(exist_ok=True)
        skill_md = test_skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: _test_reload_skill\n"
            "description: Temporary skill for reload test\n---\n\nTest content.",
            encoding="utf-8"
        )

        skills = sl.load_all_skills()
        assert "_test_reload_skill" in skills, \
            f"New skill not found after reload. Found: {list(skills.keys())}"
    finally:
        shutil.rmtree(test_skill_dir, ignore_errors=True)


def test_removed_skill_absent_after_reload():
    """Skill removed from disk is gone on next load_all_skills() call."""
    from backend.agent.skills import skills_loader as sl
    skills_dir = Path(sl.__file__).parent

    test_skill_dir = skills_dir / "_test_remove_skill"
    try:
        test_skill_dir.mkdir(exist_ok=True)
        (test_skill_dir / "SKILL.md").write_text(
            "---\nname: _test_remove_skill\ndescription: To be removed\n---\nContent.",
            encoding="utf-8"
        )
        # Confirm present
        skills = sl.load_all_skills()
        assert "_test_remove_skill" in skills

        # Remove and reload
        shutil.rmtree(test_skill_dir)
        skills = sl.load_all_skills()
        assert "_test_remove_skill" not in skills
    finally:
        shutil.rmtree(test_skill_dir, ignore_errors=True)


# ── get_skill_prompt_context — planner context string ────────────────────────

def test_get_skill_prompt_context_importable():
    from backend.agent.skills.skills_loader import get_skill_prompt_context
    assert callable(get_skill_prompt_context)


def test_get_skill_prompt_context_returns_string():
    from backend.agent.skills.skills_loader import get_skill_prompt_context
    result = get_skill_prompt_context()
    assert isinstance(result, str)


def test_get_skill_prompt_context_contains_skill_creator():
    """skill-creator must appear in the planner context string."""
    from backend.agent.skills.skills_loader import get_skill_prompt_context
    context = get_skill_prompt_context()
    assert "skill-creator" in context, \
        f"skill-creator not in context. Got: {context[:200]}"


def test_get_skill_prompt_context_non_empty():
    """Context string must be non-empty when at least one skill is present."""
    from backend.agent.skills.skills_loader import get_skill_prompt_context
    context = get_skill_prompt_context()
    assert len(context) > 0


def test_get_skill_prompt_context_new_skill_appears(tmp_path):
    """After writing a new skill, get_skill_prompt_context() includes it."""
    from backend.agent.skills import skills_loader as sl
    skills_dir = Path(sl.__file__).parent

    test_skill_dir = skills_dir / "_test_context_skill"
    try:
        test_skill_dir.mkdir(exist_ok=True)
        (test_skill_dir / "SKILL.md").write_text(
            "---\nname: _test_context_skill\n"
            "description: Context inclusion test skill\n---\nContent.",
            encoding="utf-8"
        )
        context = sl.get_skill_prompt_context()
        assert "_test_context_skill" in context
    finally:
        shutil.rmtree(test_skill_dir, ignore_errors=True)


# ── extract_description ───────────────────────────────────────────────────────

def test_extract_description_from_frontmatter():
    from backend.agent.skills.skills_loader import extract_description
    content = "---\nname: test\ndescription: A test skill description\n---\n\nBody."
    result = extract_description(content)
    assert result == "A test skill description"


def test_extract_description_fallback_no_frontmatter():
    from backend.agent.skills.skills_loader import extract_description
    content = "# My Skill\n\nThis is the first paragraph."
    result = extract_description(content)
    assert len(result) > 0
    assert result != "(no description)"


def test_extract_description_empty_skill():
    from backend.agent.skills.skills_loader import extract_description
    result = extract_description("")
    assert isinstance(result, str)


# ── get_skills_loader — package-level loader object ──────────────────────────

def test_get_skills_loader_importable():
    from backend.agent.skills import get_skills_loader
    assert callable(get_skills_loader)


def test_get_skills_loader_has_list_skills():
    from backend.agent.skills import get_skills_loader
    loader = get_skills_loader()
    assert hasattr(loader, "list_skills")


def test_get_skills_loader_list_skills_returns_list():
    from backend.agent.skills import get_skills_loader
    loader = get_skills_loader()
    result = loader.list_skills()
    assert isinstance(result, list)


def test_get_skills_loader_has_reload():
    from backend.agent.skills import get_skills_loader
    loader = get_skills_loader()
    assert hasattr(loader, "reload")


def test_get_skills_loader_reload_does_not_raise():
    from backend.agent.skills import get_skills_loader
    loader = get_skills_loader()
    loader.reload()  # should not raise
