"""
TelegramBridge — wires TelegramNotifier into the IRIS agent loop.

Three notification events are defined:
  1. Gate cleared       → notify_gate_clear(gate_num, gate_name)
  2. Credentials needed → notify_credential_needed(service, what_is_needed)
  3. Critical failure   → notify_critical_failure(description)

All methods:
  - Check is_configured() first; no-op silently if Telegram is not set up
  - Never raise — always return a dict
  - Are designed to avoid spam: only call them for the three defined events

Usage in agent code:
    from backend.channels.telegram_bridge import get_telegram_bridge

    bridge = get_telegram_bridge()
    bridge.notify_gate_clear(2, "Skill Creator + UI Sync")
    bridge.notify_credential_needed("github", "PAT for reading private repos")
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramBridge:
    """
    High-level integration layer that maps IRIS agent events to Telegram messages.
    """

    def __init__(self, notifier=None) -> None:
        if notifier is None:
            from .telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        self._notifier = notifier

    # ── Public API ────────────────────────────────────────────────────────────

    def notify_gate_clear(self, gate_num: int, gate_name: str) -> dict:
        """
        Send a gate-cleared update to Telegram.

        Call this once per gate when all landmarks in the gate become PERMANENT.
        Only sends when Telegram is configured.

        Args:
            gate_num:   Gate number (1–4).
            gate_name:  Human-readable gate name (e.g. "Skill Creator + UI Sync").

        Returns:
            {"success": True} on send, {"success": False, ...} otherwise.
        """
        try:
            if not self._notifier.is_configured():
                return {"success": False, "error": "Telegram not configured"}
            title = f"Gate {gate_num} cleared"
            body = (
                f"All landmarks in Gate {gate_num} ({gate_name}) are now PERMANENT.\n"
                f"IRIS is ready to advance to the next gate."
            )
            return self._notifier.send_update(title, body)
        except Exception as exc:
            logger.warning(f"[TelegramBridge] notify_gate_clear failed: {exc}")
            return {"success": False, "error": str(exc)}

    def notify_credential_needed(self, service: str, what_is_needed: str) -> dict:
        """
        Send a structured credential request via Telegram.

        Call this when the agent is blocked waiting for credentials.
        After calling, record a gradient warning and work on something else.

        Args:
            service:         Service name (e.g. "github", "openai").
            what_is_needed:  What credential is needed and why.

        Returns:
            {"success": True} on send, {"success": False, ...} otherwise.
        """
        try:
            if not self._notifier.is_configured():
                logger.warning(
                    f"[TelegramBridge] Credential needed for {service} but Telegram not configured"
                )
                return {"success": False, "error": "Telegram not configured"}
            return self._notifier.request_credentials(service, what_is_needed)
        except Exception as exc:
            logger.warning(f"[TelegramBridge] notify_credential_needed failed: {exc}")
            return {"success": False, "error": str(exc)}

    def notify_critical_failure(self, description: str) -> dict:
        """
        Send a critical failure alert.

        Only use for failures that cannot be self-resolved (not routine errors).

        Args:
            description: What failed and why it cannot be resolved automatically.

        Returns:
            {"success": True} on send, {"success": False, ...} otherwise.
        """
        try:
            if not self._notifier.is_configured():
                return {"success": False, "error": "Telegram not configured"}
            message = f"[IRIS CRITICAL FAILURE]\n\n{description}"
            return self._notifier.send_message(message)
        except Exception as exc:
            logger.warning(f"[TelegramBridge] notify_critical_failure failed: {exc}")
            return {"success": False, "error": str(exc)}


_bridge_instance: Optional[TelegramBridge] = None


def get_telegram_bridge() -> TelegramBridge:
    """Return the singleton TelegramBridge instance."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = TelegramBridge()
    return _bridge_instance
