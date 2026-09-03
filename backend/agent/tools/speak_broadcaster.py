"""Broadcast agent speech to external channels (Issue C.2 extension).

When the agent speaks — via the ``speak`` tool, a structured ``speak`` summary
(Issue C.1), or any other utterance — the same words the user hears locally
(TTS) are also delivered to connected external channels: Telegram and any
MCP-connected messaging integration.

Design:
  * A single ``SpeakBroadcaster`` subscribes to ``UTTERANCE_START`` on the
    EventBus and forwards the text to every registered external channel.
  * Channels are registered via ``register_channel(name, sender)``.  The
    built-in channels are Telegram (via ``TelegramNotifier``) and any
    MCP-connected integration server that exposes a ``send_message`` tool.
  * All forwarding is fire-and-forget and exception-safe — a failed external
    send never blocks local TTS or the agent.
  * The local TTS path is handled separately by ``ConversationKernel``; this
    module only adds the external delivery, so there is no double-speaking.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict, Optional

from backend.agent.event_bus import EventBus, IRISStreamEvent, get_event_bus

logger = logging.getLogger(__name__)

# A channel sender takes the spoken text and returns truthy on success.
ChannelSender = Callable[[str], object]


class SpeakBroadcaster:
    """Forwards utterances to external channels (Telegram, MCP, ...)."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._bus = event_bus or get_event_bus()
        self._IRISStreamEvent = IRISStreamEvent
        self._channels: Dict[str, ChannelSender] = {}
        self._subscribed = False

    # ── Channel registry ──────────────────────────────────────────────────

    def register_channel(self, name: str, sender: ChannelSender) -> None:
        """Register an external channel. ``sender(text)`` is called per utterance."""
        self._channels[name] = sender
        logger.info("[SpeakBroadcaster] registered channel: %s", name)

    def register_default_channels(self) -> None:
        """Register the built-in channels (Telegram + MCP-connected servers)."""
        self._register_telegram()
        self._register_mcp_channels()

    def _register_telegram(self) -> None:
        try:
            from backend.channels.telegram_notifier import get_telegram_notifier

            notifier = get_telegram_notifier()

            def _send(text: str) -> bool:
                if not notifier.is_configured():
                    return False
                result = notifier.send_message(text)
                return bool(result.get("success"))

            self.register_channel("telegram", _send)
        except Exception as exc:
            logger.warning("[SpeakBroadcaster] Telegram channel unavailable: %s", exc)

    def _register_mcp_channels(self) -> None:
        """Register a sender per MCP-connected integration server (best-effort).

        For each server registered with ``IntegrationMCPBridge`` that is
        reachable, forward utterances to it via ``ServerManager.call_tool``
        (tool ``send_message``).  This is how "Telegram etc." MCP connections
        receive the agent's spoken feedback.
        """
        try:
            from backend.integrations.mcp_bridge import get_mcp_bridge
            from backend.mcp.server_manager import get_server_manager

            bridge = get_mcp_bridge()
            manager = get_server_manager()
        except Exception as exc:
            logger.warning("[SpeakBroadcaster] MCP bridge unavailable: %s", exc)
            return

        for server_id in list(getattr(bridge, "_integration_servers", {}).keys()):
            try:

                def _make_sender(sid: str) -> ChannelSender:
                    def _send(text: str) -> bool:
                        try:
                            coro = manager.call_tool(sid, "send_message", {"text": text})
                            try:
                                loop = asyncio.get_event_loop()
                            except RuntimeError:
                                return False
                            if loop.is_running():
                                asyncio.run_coroutine_threadsafe(coro, loop)
                            else:
                                loop.run_until_complete(coro)
                            return True
                        except Exception as exc:
                            logger.warning(
                                "[SpeakBroadcaster] MCP send to %s failed: %s", sid, exc
                            )
                            return False

                    return _send

                self.register_channel(f"mcp:{server_id}", _make_sender(server_id))
            except Exception as exc:
                logger.warning(
                    "[SpeakBroadcaster] MCP channel %s setup failed: %s", server_id, exc
                )

    # ── Forwarding ─────────────────────────────────────────────────────────

    def forward_external(self, text: str) -> None:
        """Send ``text`` to every registered external channel. Fire-and-forget."""
        if not text:
            return
        for name, sender in self._channels.items():
            try:
                sender(text)
            except Exception as exc:
                logger.warning("[SpeakBroadcaster] channel %s failed: %s", name, exc)

    # ── EventBus wiring ────────────────────────────────────────────────────

    def subscribe(self) -> None:
        """Subscribe to utterance events so every spoken line is forwarded."""
        if self._subscribed:
            return
        self._bus.subscribe(
            self._IRISStreamEvent.UTTERANCE_START, self._on_utterance_start
        )
        self._subscribed = True
        logger.info("[SpeakBroadcaster] subscribed to utterance:start")

    def _on_utterance_start(self, payload) -> None:
        # Local TTS is handled separately by ConversationKernel.  Here we only
        # mirror the spoken words to external channels.  Fire-and-forget.
        text = (payload.data or {}).get("text", "")
        if text:
            self.forward_external(text)


# ── Singleton ──────────────────────────────────────────────────────────────

_broadcaster: Optional[SpeakBroadcaster] = None


def get_speak_broadcaster() -> SpeakBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = SpeakBroadcaster()
        _broadcaster.register_default_channels()
        _broadcaster.subscribe()
    return _broadcaster
