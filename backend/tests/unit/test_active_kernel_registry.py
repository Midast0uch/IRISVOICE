"""Wave 5 (session-conversation-switching spec): eliminate the phantom
"default" kernel.

These tests assert that a session resolves to its ACTIVE conversation's kernel
via get_active_kernel(session_id) instead of silently materialising a
disconnected "default"-keyed kernel.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.agent.agent_kernel import (  # noqa: E402
    get_agent_kernel,
    get_active_kernel,
    set_active_conversation,
    cleanup_agent_kernel,
    _agent_kernel_instances,
    _session_active_conversation,
)


def _reset():
    # Clear any kernels/conversation bindings created by this test.
    for k in list(_agent_kernel_instances.keys()):
        _agent_kernel_instances.pop(k, None)
    for k in list(_session_active_conversation.keys()):
        _session_active_conversation.pop(k, None)


def test_get_active_kernel_resolves_active_conversation():
    """get_active_kernel(session_id) returns the kernel keyed by the session's
    active conversation_id, NOT a phantom 'default' kernel."""
    _reset()
    sid = "session_iris"
    conv = "conv_wave5_active"
    set_active_conversation(sid, conv)

    active = get_active_kernel(sid)
    direct = get_agent_kernel(conversation_id=conv, session_id=sid)

    # Same instance — the active conversation's kernel.
    assert active is direct
    assert active.conversation_id == conv
    # No phantom "default" kernel was created.
    assert "default" not in _agent_kernel_instances
    _reset()


def test_get_active_kernel_switches_with_active_conversation():
    """When the active conversation changes, get_active_kernel follows it."""
    _reset()
    sid = "session_iris"
    conv_a = "conv_wave5_A"
    conv_b = "conv_wave5_B"

    set_active_conversation(sid, conv_a)
    kA = get_active_kernel(sid)
    assert kA.conversation_id == conv_a

    set_active_conversation(sid, conv_b)
    kB = get_active_kernel(sid)
    assert kB.conversation_id == conv_b
    # The two are distinct kernels for distinct conversations.
    assert kA is not kB
    assert "default" not in _agent_kernel_instances
    _reset()


def test_get_active_kernel_falls_back_to_default_only_when_unregistered():
    """A session with no registered active conversation still resolves (to the
    legacy 'default' kernel) rather than raising — preserving old behaviour for
    brand-new sessions before the first new_conversation/sync_state."""
    _reset()
    sid = "session_unknown"
    kernel = get_active_kernel(sid)
    assert kernel.conversation_id == "default"
    _reset()


def test_set_active_conversation_mirrors_gateway_binding():
    """set_active_conversation is the single source the gateway mirrors into;
    get_active_kernel must read exactly what was set."""
    _reset()
    sid = "session_iris"
    conv = "conv_mirror"
    set_active_conversation(sid, conv)
    assert _session_active_conversation.get(sid) == conv
    assert get_active_kernel(sid).conversation_id == conv
    _reset()
