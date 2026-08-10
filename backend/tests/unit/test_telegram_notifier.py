"""
Tests for TelegramNotifier — Gate 3 Step 3.2
Source: bootstrap/GOALS.md Step 3.2 acceptance criteria

Key requirements:
  - TelegramNotifier importable from backend.channels.telegram_notifier
  - send_message(text) — fails gracefully when no credentials, sends via HTTP when mocked
  - send_update(title, body) — formatted progress update
  - request_credentials(service, what_is_needed) — structured credential request
  - All methods return dict with success key (never raise)
  - Without TELEGRAM_BOT_TOKEN env var, returns success=False with meaningful error

Run: python -m pytest backend/tests/test_telegram_notifier.py -v
"""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ── Import and instantiation ──────────────────────────────────────────────────

def test_telegram_notifier_importable():
    from backend.channels.telegram_notifier import TelegramNotifier
    assert TelegramNotifier


def test_telegram_notifier_instantiates_without_credentials():
    """TelegramNotifier() must not raise even without env vars set."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        notifier = TelegramNotifier()
    assert notifier is not None


def test_telegram_notifier_has_send_message():
    from backend.channels.telegram_notifier import TelegramNotifier
    assert hasattr(TelegramNotifier, "send_message")


def test_telegram_notifier_has_send_update():
    from backend.channels.telegram_notifier import TelegramNotifier
    assert hasattr(TelegramNotifier, "send_update")


def test_telegram_notifier_has_request_credentials():
    from backend.channels.telegram_notifier import TelegramNotifier
    assert hasattr(TelegramNotifier, "request_credentials")


def test_telegram_notifier_has_is_configured():
    from backend.channels.telegram_notifier import TelegramNotifier
    assert hasattr(TelegramNotifier, "is_configured")


# ── Without credentials — graceful failure ────────────────────────────────────

def test_send_message_no_credentials_returns_failure():
    """send_message without credentials returns success=False, does not raise."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        notifier = TelegramNotifier()
        result = notifier.send_message("test message")
    assert result.get("success") is False, \
        f"Expected success=False without credentials, got: {result}"
    assert "error" in result or "reason" in result, \
        f"Expected error/reason in result: {result}"


def test_send_update_no_credentials_returns_failure():
    """send_update without credentials returns success=False, does not raise."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        notifier = TelegramNotifier()
        result = notifier.send_update("Gate 2 cleared", "All tests passing")
    assert result.get("success") is False


def test_request_credentials_no_credentials_returns_dict():
    """request_credentials without credentials returns a dict, does not raise."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        notifier = TelegramNotifier()
        result = notifier.request_credentials("github", "Personal access token for repo access")
    assert isinstance(result, dict), f"Expected dict, got: {type(result)}"


def test_is_configured_false_without_credentials():
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        notifier = TelegramNotifier()
        assert notifier.is_configured() is False


# ── With credentials — correct HTTP call made ─────────────────────────────────

def test_is_configured_true_with_credentials():
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "12345:faketoken",
        "TELEGRAM_CHAT_ID": "99999"
    }):
        notifier = TelegramNotifier()
        assert notifier.is_configured() is True


def test_send_message_calls_telegram_api():
    """send_message with credentials calls the Telegram Bot API."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "12345:faketoken",
        "TELEGRAM_CHAT_ID": "99999"
    }):
        notifier = TelegramNotifier()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = notifier.send_message("Hello from IRIS")

        assert result.get("success") is True, f"Expected success=True, got: {result}"
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "sendMessage" in call_url
        assert "12345:faketoken" in call_url


def test_send_message_payload_contains_text():
    """send_message POST payload includes the chat_id and message text."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "12345:faketoken",
        "TELEGRAM_CHAT_ID": "99999"
    }):
        notifier = TelegramNotifier()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}

        with patch("requests.post", return_value=mock_response) as mock_post:
            notifier.send_message("IRIS is online")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args[1].get("data") \
                  or mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else {}
        # The chat_id and text should appear somewhere in the call
        call_str = str(mock_post.call_args)
        assert "99999" in call_str, "chat_id not in API call"
        assert "IRIS is online" in call_str, "message text not in API call"


def test_send_update_formats_title_and_body():
    """send_update includes both title and body in the sent message."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "12345:faketoken",
        "TELEGRAM_CHAT_ID": "99999"
    }):
        notifier = TelegramNotifier()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 2}}

        with patch("requests.post", return_value=mock_response) as mock_post:
            notifier.send_update("Gate 3 cleared", "All MCP integrations working")

        call_str = str(mock_post.call_args)
        assert "Gate 3 cleared" in call_str
        assert "All MCP integrations working" in call_str


def test_request_credentials_includes_service_and_reason():
    """request_credentials sends a message containing the service name and what is needed."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "12345:faketoken",
        "TELEGRAM_CHAT_ID": "99999"
    }):
        notifier = TelegramNotifier()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 3}}

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = notifier.request_credentials("github", "Personal access token")

        assert result.get("success") is True
        call_str = str(mock_post.call_args)
        assert "github" in call_str
        assert "Personal access token" in call_str


def test_send_message_handles_http_error_gracefully():
    """If Telegram API returns error status, send_message returns success=False."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "12345:faketoken",
        "TELEGRAM_CHAT_ID": "99999"
    }):
        notifier = TelegramNotifier()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"ok": False, "description": "Unauthorized"}

        with patch("requests.post", return_value=mock_response):
            result = notifier.send_message("test")

        assert result.get("success") is False


def test_send_message_handles_exception_gracefully():
    """If requests.post raises, send_message returns success=False (never raises)."""
    from backend.channels.telegram_notifier import TelegramNotifier
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "12345:faketoken",
        "TELEGRAM_CHAT_ID": "99999"
    }):
        notifier = TelegramNotifier()
        with patch("requests.post", side_effect=Exception("connection refused")):
            result = notifier.send_message("test")
        assert result.get("success") is False
