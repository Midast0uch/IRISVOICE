"""
Tests for Telegram wired into agent loop — Gate 3 Step 3.3
Source: bootstrap/GOALS.md Step 3.3 acceptance criteria

Key requirements:
  - TelegramBridge importable from backend.channels.telegram_bridge
  - notify_gate_clear(gate_num, gate_name) sends update via notifier
  - notify_credential_needed(service, what) sends request_credentials via notifier
  - notify_critical_failure(description) sends message via notifier
  - All methods guard against spam (no-op if notifier not configured)
  - All methods never raise even if notifier fails
  - TelegramBridge exposes get_telegram_bridge() singleton

Run: python -m pytest backend/tests/test_telegram_wired.py -v
"""

import os
import pytest
from unittest.mock import MagicMock, patch


# ── Imports and structure ─────────────────────────────────────────────────────

def test_telegram_bridge_importable():
    from backend.channels.telegram_bridge import TelegramBridge
    assert TelegramBridge


def test_get_telegram_bridge_importable():
    from backend.channels.telegram_bridge import get_telegram_bridge
    assert callable(get_telegram_bridge)


def test_telegram_bridge_has_notify_gate_clear():
    from backend.channels.telegram_bridge import TelegramBridge
    assert hasattr(TelegramBridge, "notify_gate_clear")


def test_telegram_bridge_has_notify_credential_needed():
    from backend.channels.telegram_bridge import TelegramBridge
    assert hasattr(TelegramBridge, "notify_credential_needed")


def test_telegram_bridge_has_notify_critical_failure():
    from backend.channels.telegram_bridge import TelegramBridge
    assert hasattr(TelegramBridge, "notify_critical_failure")


# ── No-op without credentials ─────────────────────────────────────────────────

def test_notify_gate_clear_no_op_without_credentials():
    """notify_gate_clear returns gracefully when Telegram is not configured."""
    from backend.channels.telegram_bridge import TelegramBridge
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        bridge = TelegramBridge()
        result = bridge.notify_gate_clear(2, "Skill Creator + UI Sync")
    assert isinstance(result, dict), f"Expected dict, got: {type(result)}"
    # success=False is fine when not configured — must not raise


def test_notify_credential_needed_no_op_without_credentials():
    """notify_credential_needed returns gracefully when Telegram not configured."""
    from backend.channels.telegram_bridge import TelegramBridge
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        bridge = TelegramBridge()
        result = bridge.notify_credential_needed("github", "Personal access token")
    assert isinstance(result, dict)


def test_notify_critical_failure_no_op_without_credentials():
    """notify_critical_failure returns gracefully when Telegram not configured."""
    from backend.channels.telegram_bridge import TelegramBridge
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        bridge = TelegramBridge()
        result = bridge.notify_critical_failure("Cannot resolve circular import")
    assert isinstance(result, dict)


# ── With mocked notifier — correct messages sent ─────────────────────────────

def test_notify_gate_clear_calls_send_update():
    """notify_gate_clear calls notifier.send_update with gate info."""
    from backend.channels.telegram_bridge import TelegramBridge

    mock_notifier = MagicMock()
    mock_notifier.is_configured.return_value = True
    mock_notifier.send_update.return_value = {"success": True}

    bridge = TelegramBridge(notifier=mock_notifier)
    bridge.notify_gate_clear(2, "Skill Creator + UI Sync")

    mock_notifier.send_update.assert_called_once()
    call_args = mock_notifier.send_update.call_args
    title = call_args[0][0] if call_args[0] else call_args[1].get("title", "")
    body = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("body", "")
    combined = f"{title} {body}"
    assert "2" in combined or "Gate" in combined or "gate" in combined.lower()


def test_notify_gate_clear_message_contains_gate_name():
    """Gate name appears in the sent message."""
    from backend.channels.telegram_bridge import TelegramBridge

    mock_notifier = MagicMock()
    mock_notifier.is_configured.return_value = True
    mock_notifier.send_update.return_value = {"success": True}

    bridge = TelegramBridge(notifier=mock_notifier)
    bridge.notify_gate_clear(3, "MCP + Telegram")

    call_str = str(mock_notifier.send_update.call_args)
    assert "MCP" in call_str or "Telegram" in call_str, \
        f"Gate name not in message: {call_str}"


def test_notify_credential_needed_calls_request_credentials():
    """notify_credential_needed calls notifier.request_credentials."""
    from backend.channels.telegram_bridge import TelegramBridge

    mock_notifier = MagicMock()
    mock_notifier.is_configured.return_value = True
    mock_notifier.request_credentials.return_value = {"success": True}

    bridge = TelegramBridge(notifier=mock_notifier)
    bridge.notify_credential_needed("openai", "API key for LLM inference")

    mock_notifier.request_credentials.assert_called_once()
    call_str = str(mock_notifier.request_credentials.call_args)
    assert "openai" in call_str
    assert "API key" in call_str


def test_notify_critical_failure_calls_send_message():
    """notify_critical_failure calls notifier.send_message with description."""
    from backend.channels.telegram_bridge import TelegramBridge

    mock_notifier = MagicMock()
    mock_notifier.is_configured.return_value = True
    mock_notifier.send_message.return_value = {"success": True}

    bridge = TelegramBridge(notifier=mock_notifier)
    bridge.notify_critical_failure("SQLite database locked for 60 seconds")

    mock_notifier.send_message.assert_called_once()
    call_str = str(mock_notifier.send_message.call_args)
    assert "SQLite" in call_str or "locked" in call_str


# ── Never raise on notifier failure ──────────────────────────────────────────

def test_notify_gate_clear_never_raises_on_notifier_failure():
    """Even if notifier.send_update raises, notify_gate_clear does not propagate."""
    from backend.channels.telegram_bridge import TelegramBridge

    mock_notifier = MagicMock()
    mock_notifier.is_configured.return_value = True
    mock_notifier.send_update.side_effect = Exception("network error")

    bridge = TelegramBridge(notifier=mock_notifier)
    # Must not raise
    result = bridge.notify_gate_clear(1, "DER Loop + Director Mode")
    assert isinstance(result, dict)


def test_notify_credential_needed_never_raises_on_failure():
    from backend.channels.telegram_bridge import TelegramBridge

    mock_notifier = MagicMock()
    mock_notifier.is_configured.return_value = True
    mock_notifier.request_credentials.side_effect = Exception("timeout")

    bridge = TelegramBridge(notifier=mock_notifier)
    result = bridge.notify_credential_needed("service", "key")
    assert isinstance(result, dict)


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_telegram_bridge_returns_telegram_bridge_instance():
    from backend.channels.telegram_bridge import get_telegram_bridge, TelegramBridge
    bridge = get_telegram_bridge()
    assert isinstance(bridge, TelegramBridge)


def test_get_telegram_bridge_singleton():
    from backend.channels.telegram_bridge import get_telegram_bridge
    a = get_telegram_bridge()
    b = get_telegram_bridge()
    assert a is b
