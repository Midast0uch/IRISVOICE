"""
TelegramNotifier — IRIS outbound channel to a Telegram bot.

Credentials are loaded from environment variables:
  TELEGRAM_BOT_TOKEN  — bot token from @BotFather
  TELEGRAM_CHAT_ID    — the chat/user ID to send messages to

If credentials are absent, all methods return {"success": False, "error": ...}
and never raise. This ensures the agent can check `is_configured()` before
attempting to send, and fall back gracefully.

Credential request protocol:
  When IRIS needs credentials it cannot access locally, call
  request_credentials(service, what_is_needed). If Telegram is configured,
  this sends a formatted request message to the owner. If not configured,
  it returns a failure dict and the caller should record a gradient warning.
"""

import logging
import os

logger = logging.getLogger(__name__)

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """
    Sends notifications to a Telegram chat via the Telegram Bot API.

    All methods are synchronous and never raise — they return a dict with
    a 'success' key so callers can branch without try/except.
    """

    def __init__(self) -> None:
        self._token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self._chat_id: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """Return True if both token and chat_id are present in the environment."""
        return bool(self._token and self._chat_id)

    def send_message(self, text: str) -> dict:
        """
        Send a plain text message to the configured Telegram chat.

        Args:
            text: The message body.

        Returns:
            {"success": True} on success.
            {"success": False, "error": reason} on failure.
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
            }
        return self._post(text)

    def send_update(self, title: str, body: str) -> dict:
        """
        Send a formatted progress update message.

        Args:
            title: Short title / headline.
            body:  Details / body text.

        Returns:
            {"success": True} on success, {"success": False, "error": ...} on failure.
        """
        formatted = f"[IRIS UPDATE] {title}\n\n{body}"
        return self.send_message(formatted)

    def request_credentials(self, service: str, what_is_needed: str) -> dict:
        """
        Send a structured credential request to the Telegram chat owner.

        When Telegram is not configured, returns success=False. The caller
        should record a gradient warning and work on something else.

        Args:
            service:         Name of the service that needs credentials
                             (e.g. "github", "openai").
            what_is_needed:  Human-readable description of exactly what is
                             needed and why (e.g. "Personal access token for
                             reading private repos").

        Returns:
            {"success": True} if sent, {"success": False, "error": ...} otherwise.
        """
        message = (
            f"[IRIS CREDENTIAL REQUEST]\n\n"
            f"Service: {service}\n"
            f"Needed:  {what_is_needed}\n\n"
            f"Please reply with the credential so IRIS can continue."
        )
        return self.send_message(message)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _post(self, text: str) -> dict:
        """POST a sendMessage request to the Telegram Bot API."""
        try:
            import requests as _requests
            url = _TELEGRAM_API_BASE.format(token=self._token)
            payload = {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
            response = _requests.post(url, json=payload, timeout=10)
            data = response.json()
            if response.status_code == 200 and data.get("ok"):
                logger.info("[TelegramNotifier] Message sent successfully")
                return {"success": True, "message_id": data.get("result", {}).get("message_id")}
            else:
                error = data.get("description", f"HTTP {response.status_code}")
                logger.warning(f"[TelegramNotifier] API error: {error}")
                return {"success": False, "error": error}
        except Exception as exc:
            logger.warning(f"[TelegramNotifier] Failed to send message: {exc}")
            return {"success": False, "error": str(exc)}


def get_telegram_notifier() -> TelegramNotifier:
    """Return a TelegramNotifier instance (created fresh each call — reads env at init)."""
    return TelegramNotifier()
