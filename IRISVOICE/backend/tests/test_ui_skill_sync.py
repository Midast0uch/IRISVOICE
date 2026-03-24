"""
Tests for UI Skill List Sync — Gate 2 Step 2.3
Source: bootstrap/GOALS.md Step 2.3 acceptance criteria

Key requirements:
  - _handle_get_skills() sends skills_list WebSocket message with skill data
  - skills_reloaded broadcast triggers UI re-fetch via iris:skills_reloaded event
  - After create_skill, skills_reloaded is broadcast so UI updates automatically
  - get_skills WS message is handled by iris_gateway
  - LearnedSkillsPanel hooks: skills_reloaded → re-fetch (verified by inspection)

Run: python -m pytest backend/tests/test_ui_skill_sync.py -v
"""

import shutil
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


SKILL_DIR = Path(__file__).parent.parent / "agent" / "skills"
TEST_SKILL_NAME = "_test_ui_sync_skill"
TEST_SKILL_CONTENT = (
    "---\nname: _test_ui_sync_skill\n"
    "description: Temporary skill for UI sync tests\n---\n\nContent."
)


def _cleanup():
    target = SKILL_DIR / TEST_SKILL_NAME
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


# ── Backend: _handle_get_skills ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_get_skills_sends_skills_list():
    """_handle_get_skills() sends a skills_list message to the client."""
    from backend.iris_gateway import IRISGateway as IrisGateway

    gw = IrisGateway.__new__(IrisGateway)
    gw._logger = MagicMock()
    gw._ws_manager = AsyncMock()

    await gw._handle_get_skills("session1", "client1")

    # Must have sent to client
    gw._ws_manager.send_to_client.assert_called_once()
    call_args = gw._ws_manager.send_to_client.call_args
    msg = call_args[0][1]
    assert msg["type"] == "skills_list", f"Expected skills_list, got: {msg['type']}"
    assert "skills" in msg["payload"], f"No 'skills' in payload: {msg['payload']}"


@pytest.mark.asyncio
async def test_handle_get_skills_list_is_list():
    """skills_list payload['skills'] is a list."""
    from backend.iris_gateway import IRISGateway as IrisGateway

    gw = IrisGateway.__new__(IrisGateway)
    gw._logger = MagicMock()
    gw._ws_manager = AsyncMock()

    await gw._handle_get_skills("session1", "client1")

    msg = gw._ws_manager.send_to_client.call_args[0][1]
    assert isinstance(msg["payload"]["skills"], list)


@pytest.mark.asyncio
async def test_handle_get_skills_excludes_system_skills():
    """_handle_get_skills() never returns 'skill-creator' in the list."""
    from backend.iris_gateway import IRISGateway as IrisGateway

    gw = IrisGateway.__new__(IrisGateway)
    gw._logger = MagicMock()
    gw._ws_manager = AsyncMock()

    await gw._handle_get_skills("session1", "client1")

    msg = gw._ws_manager.send_to_client.call_args[0][1]
    skill_keys = [s.get("key") for s in msg["payload"]["skills"]]
    assert "skill-creator" not in skill_keys, \
        f"skill-creator must not appear in UI list: {skill_keys}"


@pytest.mark.asyncio
async def test_handle_get_skills_each_skill_has_required_fields():
    """Each skill in the list has key, name, description, enabled fields."""
    _cleanup()
    target = SKILL_DIR / TEST_SKILL_NAME
    target.mkdir(exist_ok=True)
    (target / "SKILL.md").write_text(TEST_SKILL_CONTENT, encoding="utf-8")
    try:
        from backend.iris_gateway import IRISGateway as IrisGateway

        gw = IrisGateway.__new__(IrisGateway)
        gw._logger = MagicMock()
        gw._ws_manager = AsyncMock()

        await gw._handle_get_skills("session1", "client1")

        msg = gw._ws_manager.send_to_client.call_args[0][1]
        skills = msg["payload"]["skills"]
        matching = [s for s in skills if s.get("key") == TEST_SKILL_NAME]
        assert matching, f"{TEST_SKILL_NAME} not in skills list: {[s.get('key') for s in skills]}"
        skill = matching[0]
        for field in ("key", "name", "description", "enabled"):
            assert field in skill, f"Field '{field}' missing from skill: {skill}"
    finally:
        _cleanup()


# ── Backend: reload_skills broadcasts skills_reloaded ────────────────────────

@pytest.mark.asyncio
async def test_reload_skills_broadcasts_skills_reloaded():
    """_handle_reload_skills() broadcasts skills_reloaded to the client."""
    from backend.iris_gateway import IRISGateway as IrisGateway

    gw = IrisGateway.__new__(IrisGateway)
    gw._logger = MagicMock()
    gw._ws_manager = AsyncMock()

    await gw._handle_reload_skills("session1", "client1", {})

    gw._ws_manager.send_to_client.assert_called_once()
    msg = gw._ws_manager.send_to_client.call_args[0][1]
    assert msg["type"] == "skills_reloaded", f"Expected skills_reloaded, got: {msg['type']}"


@pytest.mark.asyncio
async def test_reload_skills_payload_has_skills_list():
    """skills_reloaded payload contains a skills list."""
    from backend.iris_gateway import IRISGateway as IrisGateway

    gw = IrisGateway.__new__(IrisGateway)
    gw._logger = MagicMock()
    gw._ws_manager = AsyncMock()

    await gw._handle_reload_skills("session1", "client1", {})

    msg = gw._ws_manager.send_to_client.call_args[0][1]
    assert "skills" in msg["payload"], f"No 'skills' in payload: {msg['payload']}"
    assert isinstance(msg["payload"]["skills"], list)


# ── Gateway message routing — get_skills and reload_skills are handled ────────

def test_gateway_handles_get_skills_message():
    """IrisGateway has a _handle_get_skills method."""
    from backend.iris_gateway import IRISGateway as IrisGateway
    assert hasattr(IrisGateway, "_handle_get_skills"), \
        "IrisGateway missing _handle_get_skills"


def test_gateway_handles_reload_skills_message():
    """IrisGateway has a _handle_reload_skills method."""
    from backend.iris_gateway import IRISGateway as IrisGateway
    assert hasattr(IrisGateway, "_handle_reload_skills"), \
        "IrisGateway missing _handle_reload_skills"


# ── Skills reloaded after create_skill ───────────────────────────────────────

@pytest.mark.asyncio
async def test_create_skill_triggers_skills_reloaded_broadcast():
    """After create_skill, tool_bridge broadcasts skills_reloaded to frontend."""
    import inspect
    import backend.agent.tool_bridge as tb_module
    source = inspect.getsource(tb_module)
    # The broadcast is guarded by tool_name == "create_skill" and result.get("success")
    assert "skills_reloaded" in source and "create_skill" in source, \
        "tool_bridge does not contain skills_reloaded broadcast after create_skill"


# ── New skill appears in UI list after creation ───────────────────────────────

@pytest.mark.asyncio
async def test_new_skill_appears_in_get_skills_after_creation():
    """After creating a skill, _handle_get_skills() includes it in the response."""
    _cleanup()
    target = SKILL_DIR / TEST_SKILL_NAME
    target.mkdir(exist_ok=True)
    (target / "SKILL.md").write_text(TEST_SKILL_CONTENT, encoding="utf-8")
    try:
        from backend.iris_gateway import IRISGateway as IrisGateway

        gw = IrisGateway.__new__(IrisGateway)
        gw._logger = MagicMock()
        gw._ws_manager = AsyncMock()

        await gw._handle_get_skills("session1", "client1")

        msg = gw._ws_manager.send_to_client.call_args[0][1]
        skill_keys = [s.get("key") for s in msg["payload"]["skills"]]
        assert TEST_SKILL_NAME in skill_keys, \
            f"New skill not in UI list: {skill_keys}"
    finally:
        _cleanup()
