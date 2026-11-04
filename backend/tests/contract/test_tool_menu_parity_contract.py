"""Contract: the chat menu and the registry menu must not drift apart.

DEFECT (measured 2026-10-31): ``AgentToolBridge.get_available_tools()`` is the
menu the CHAT path hands to the model; ``tool_registry.get_registry_tools()``
is the menu the DER path uses. They were two hand-maintained lists, and they
had drifted:

  * registry 27 tools, chat 20 — ``glob_files``, ``grep_files``,
    ``recall_research``, ``list_conversations``, ``transcribe_media``,
    ``combine_documents``, ``get_rendered_documents``, ``analyze_video_frames``
    and ``clip_video`` were callable by a DER step and invisible in chat;
  * ``ask_user_question`` was in both, but only the registry declared
    ``non_blocking`` / ``parked_url`` / ``run_id`` / ``wall_kind``, so the chat
    path could not raise a non-blocking question.

`forget` was the measured instance of the same shape (2026-10-30): added to
one list, invisible on the other path, and the model claimed a deletion it
never made. This test pins the invariant, not the tool.

Gates are respected: the chat menu may omit a registry tool only when the
desktop-control gate removes it, or when the spec is ``developer_only`` and
the app is in personal mode (the registry keeps those for DER; chat does not).
The registry already applies the internet and personal-mode gates itself.
"""
from __future__ import annotations

from backend.agent.tool_bridge import DESKTOP_CONTROL_TOOLS, AgentToolBridge
from backend.agent.tool_registry import get_registry_tools, get_all_specs


def _menus() -> tuple[list[dict], dict[str, dict]]:
    chat = AgentToolBridge().get_available_tools()
    return chat, {t["name"]: t for t in get_registry_tools()}


def test_every_registry_tool_reaches_the_chat_menu():
    from backend.agent.agent_kernel import get_desktop_control_enabled
    from backend.capabilities import CapabilitySet

    chat, registry = _menus()
    chat_names = {t["name"] for t in chat}
    desktop_on = get_desktop_control_enabled()
    developer_only = {
        s.name for s in get_all_specs() if getattr(s, "developer_only", False)
    }
    chat_has_developer_tools = CapabilitySet.is_developer()

    expected = {
        name
        for name in registry
        if (desktop_on or name not in DESKTOP_CONTROL_TOOLS)
        and (chat_has_developer_tools or name not in developer_only)
    }
    missing = expected - chat_names
    assert not missing, (
        "these tools are callable by a DER step but the model cannot see them "
        f"in chat: {sorted(missing)}"
    )


def test_no_chat_only_tool_exists_without_being_named_here():
    """A tool the chat path offers and the registry does not is the same defect
    in the other direction: the DER planner cannot reach it. Register it, or
    add it to this list with a reason."""
    chat, registry = _menus()
    known_chat_only = {"read_command_output", "stop_command"}
    assert {t["name"] for t in chat} - set(registry) <= known_chat_only


def test_a_shared_tool_declares_the_same_parameters_on_both_paths():
    chat, registry = _menus()
    drift = {}
    for tool in chat:
        name = tool.get("name")
        if name not in registry:
            continue
        chat_params = set((tool.get("parameters") or {}))
        reg_params = set((registry[name].get("parameters") or {}))
        if chat_params != reg_params:
            drift[name] = {
                "chat_only": sorted(chat_params - reg_params),
                "registry_only": sorted(reg_params - chat_params),
            }
    assert not drift, f"the same tool has two shapes: {drift}"
