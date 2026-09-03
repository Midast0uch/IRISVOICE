"""
Tests for Skill Creator — Gate 2 Step 2.2
Source: bootstrap/GOALS.md Step 2.2 acceptance criteria

Key requirements:
  - InternalCapabilityServer.create_skill creates SKILL.md file in skills/
  - Created skill appears in registry after load_all_skills() reload
  - Created skill is listed via get_skill_prompt_context()
  - create_skill returns success=True on valid input
  - create_skill returns success=False on missing/invalid name
  - Tool dispatch path has create_skill registered

Run: python -m pytest backend/tests/test_skill_creator.py -v
"""

import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock


SKILL_DIR = Path(__file__).parent.parent / "agent" / "skills"
TEST_SKILL_NAME = "_test_creator_skill"
TEST_SKILL_CONTENT = (
    "---\nname: _test_creator_skill\n"
    "description: Auto-created test skill for unit tests\n---\n\n"
    "This skill was created by test_skill_creator.py."
)


def _cleanup():
    target = SKILL_DIR / TEST_SKILL_NAME
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


# ── InternalCapabilityServer — create_skill tool ─────────────────────────────

def test_internal_server_importable():
    from backend.mcp.builtin_servers import InternalCapabilityServer
    assert InternalCapabilityServer


def test_internal_server_instantiates():
    from backend.mcp.builtin_servers import InternalCapabilityServer
    server = InternalCapabilityServer()
    assert server is not None


def test_create_skill_tool_registered():
    """create_skill is in the server's tool list."""
    from backend.mcp.builtin_servers import InternalCapabilityServer
    server = InternalCapabilityServer()
    tool_names = [t.name for t in server._tools]
    assert "create_skill" in tool_names, f"create_skill not in {tool_names}"


@pytest.mark.asyncio
async def test_create_skill_creates_file():
    """create_skill writes SKILL.md into skills/<name>/ directory."""
    _cleanup()
    try:
        from backend.mcp.builtin_servers import InternalCapabilityServer
        server = InternalCapabilityServer()
        result = await server.execute_tool("create_skill", {
            "name": TEST_SKILL_NAME,
            "content": TEST_SKILL_CONTENT,
        })
        assert result.get("success") is True, f"Expected success=True, got: {result}"
        skill_file = SKILL_DIR / TEST_SKILL_NAME / "SKILL.md"
        assert skill_file.exists(), f"SKILL.md not created at {skill_file}"
        assert TEST_SKILL_NAME in skill_file.read_text(encoding="utf-8")
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_create_skill_returns_path():
    """Result includes the path to the created SKILL.md."""
    _cleanup()
    try:
        from backend.mcp.builtin_servers import InternalCapabilityServer
        server = InternalCapabilityServer()
        result = await server.execute_tool("create_skill", {
            "name": TEST_SKILL_NAME,
            "content": TEST_SKILL_CONTENT,
        })
        assert "path" in result, f"No 'path' in result: {result}"
        assert TEST_SKILL_NAME in result["path"]
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_create_skill_empty_name_fails():
    """create_skill with empty name returns success=False."""
    from backend.mcp.builtin_servers import InternalCapabilityServer
    server = InternalCapabilityServer()
    result = await server.execute_tool("create_skill", {
        "name": "",
        "content": TEST_SKILL_CONTENT,
    })
    assert result.get("success") is not True, f"Expected failure for empty name, got: {result}"


@pytest.mark.asyncio
async def test_create_skill_idempotent():
    """Writing the same skill twice succeeds both times (exist_ok)."""
    _cleanup()
    try:
        from backend.mcp.builtin_servers import InternalCapabilityServer
        server = InternalCapabilityServer()
        for _ in range(2):
            result = await server.execute_tool("create_skill", {
                "name": TEST_SKILL_NAME,
                "content": TEST_SKILL_CONTENT,
            })
            assert result.get("success") is True
    finally:
        _cleanup()


# ── Registry integration — skill appears after reload ────────────────────────

@pytest.mark.asyncio
async def test_created_skill_in_registry_after_reload():
    """After create_skill, calling load_all_skills() returns the new skill."""
    _cleanup()
    try:
        from backend.mcp.builtin_servers import InternalCapabilityServer
        from backend.agent.skills.skills_loader import load_all_skills

        server = InternalCapabilityServer()
        result = await server.execute_tool("create_skill", {
            "name": TEST_SKILL_NAME,
            "content": TEST_SKILL_CONTENT,
        })
        assert result.get("success") is True

        skills = load_all_skills()
        assert TEST_SKILL_NAME in skills, \
            f"Created skill not found in registry. Found: {list(skills.keys())}"
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_created_skill_in_prompt_context():
    """After create_skill, get_skill_prompt_context() includes the new skill."""
    _cleanup()
    try:
        from backend.mcp.builtin_servers import InternalCapabilityServer
        from backend.agent.skills.skills_loader import get_skill_prompt_context

        server = InternalCapabilityServer()
        await server.execute_tool("create_skill", {
            "name": TEST_SKILL_NAME,
            "content": TEST_SKILL_CONTENT,
        })

        context = get_skill_prompt_context()
        assert TEST_SKILL_NAME in context, \
            f"Created skill not in prompt context. Context start: {context[:300]}"
    finally:
        _cleanup()


# ── Tool dispatch path — create_skill is accessible ──────────────────────────

def test_tool_bridge_lists_create_skill():
    """tool_bridge module includes create_skill in its tools definition."""
    import inspect
    import backend.agent.tool_bridge as tb_module
    source = inspect.getsource(tb_module)
    assert "create_skill" in source, "create_skill not found in tool_bridge module"


def test_skill_creator_skill_md_exists():
    """The skill-creator SKILL.md file exists in the skills directory."""
    skill_md = SKILL_DIR / "skill-creator" / "SKILL.md"
    assert skill_md.exists(), f"skill-creator/SKILL.md not found at {skill_md}"


def test_skill_creator_skill_md_has_frontmatter():
    """skill-creator/SKILL.md has valid YAML frontmatter with name and description."""
    from backend.agent.skills.skills_loader import extract_description
    skill_md = SKILL_DIR / "skill-creator" / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")
    desc = extract_description(content)
    assert len(desc) > 0 and desc != "(no description)", \
        f"skill-creator has no description: '{desc}'"


def test_skill_creator_loaded_by_skills_loader():
    """skills_loader picks up skill-creator from the registry."""
    from backend.agent.skills.skills_loader import load_all_skills
    skills = load_all_skills()
    assert "skill-creator" in skills
    assert len(skills["skill-creator"]) > 100  # non-trivial content
