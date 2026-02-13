"""
ScreenMonitor — Proactive screen monitoring for IRIS.

Periodically captures the screen and analyzes it for context changes,
enabling proactive assistance ("Hey, I noticed you got an error...").
"""
import asyncio
import time
import threading
from typing import Any, Callable, Dict, List, Optional


class ScreenMonitor:
    """
    Background screen monitor that periodically captures and analyzes
    the screen to detect context changes.

    Features:
    - Configurable polling interval (default 10s)
    - Change detection (only analyze when screen changes)
    - Proactive notifications via callbacks
    - Activity tracking (what app, what task)
    """

    _instance: Optional["ScreenMonitor"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if ScreenMonitor._initialized:
            return

        self.config: Dict[str, Any] = {
            "enabled": False,
            "interval_seconds": 10,
            "analyze_on_change_only": True,
            "notify_on_errors": True,
            "notify_on_new_windows": False,
            "max_history": 20,
        }

        # State
        self._is_running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Context history
        self._context_history: List[Dict[str, Any]] = []
        self._current_context: Optional[Dict[str, Any]] = None

        # Callbacks for proactive notifications
        self._notification_callbacks: List[Callable[[Dict], None]] = []

        # Lazy deps
        self._minicpm_client = None
        self._screen_capture = None

        ScreenMonitor._initialized = True

    def _get_minicpm_client(self):
        if self._minicpm_client is None:
            try:
                from backend.vision import MiniCPMClient
                self._minicpm_client = MiniCPMClient()
            except Exception as e:
                print(f"[ScreenMonitor] Cannot load MiniCPM client: {e}")
        return self._minicpm_client

    def _get_screen_capture(self):
        if self._screen_capture is None:
            try:
                from backend.vision import ScreenCapture
                self._screen_capture = ScreenCapture()
            except Exception as e:
                print(f"[ScreenMonitor] Cannot load screen capture: {e}")
        return self._screen_capture

    def on_notification(self, callback: Callable[[Dict], None]):
        """Register a callback for proactive notifications."""
        self._notification_callbacks.append(callback)

    def start(self) -> bool:
        """Start background monitoring."""
        if self._is_running:
            return True

        minicpm = self._get_minicpm_client()
        if not minicpm or not minicpm.check_availability():
            print("[ScreenMonitor] MiniCPM-o not available, cannot start")
            return False

        self._stop_event.clear()
        self._is_running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self._monitor_thread.start()
        print("[ScreenMonitor] Started background monitoring")
        return True

    def stop(self):
        """Stop background monitoring."""
        self._stop_event.set()
        self._is_running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        print("[ScreenMonitor] Stopped")

    def _monitor_loop(self):
        """Main monitoring loop running in background thread."""
        while not self._stop_event.is_set():
            try:
                self._check_screen()
            except Exception as e:
                print(f"[ScreenMonitor] Error in monitor loop: {e}")

            # Wait for interval or stop signal
            self._stop_event.wait(
                timeout=self.config.get("interval_seconds", 10)
            )

    def _check_screen(self):
        """Capture and analyze the screen."""
        capture = self._get_screen_capture()
        if not capture:
            return

        screenshot_b64, is_new = capture.capture_base64()

        # Skip if no change and configured to only analyze on change
        if not is_new and self.config.get("analyze_on_change_only", True):
            return

        minicpm = self._get_minicpm_client()
        if not minicpm:
            return

        # Analyze screen context
        context = minicpm.detect_screen_context(screenshot_b64)
        context["timestamp"] = time.time()

        # Check for notable changes
        notifications = self._detect_notable_changes(context)

        # Update history
        self._current_context = context
        self._context_history.append(context)
        max_history = self.config.get("max_history", 20)
        if len(self._context_history) > max_history:
            self._context_history = self._context_history[-max_history:]

        # Fire notifications
        for notification in notifications:
            for callback in self._notification_callbacks:
                try:
                    callback(notification)
                except Exception as e:
                    print(f"[ScreenMonitor] Notification callback error: {e}")

    def _detect_notable_changes(
        self, new_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Compare new context with previous to find notable changes."""
        notifications = []

        if not self._current_context:
            return notifications

        old = self._current_context
        new = new_context

        # App changed
        if old.get("active_app") != new.get("active_app"):
            if self.config.get("notify_on_new_windows", False):
                notifications.append({
                    "type": "app_change",
                    "message": f"Switched to {new.get('active_app', 'unknown')}",
                    "old_app": old.get("active_app"),
                    "new_app": new.get("active_app"),
                })

        # Error appeared
        notable_items = new.get("notable_items", [])
        if notable_items and self.config.get("notify_on_errors", True):
            for item in notable_items:
                if isinstance(item, str) and any(
                    kw in item.lower()
                    for kw in ["error", "exception", "failed", "warning", "crash"]
                ):
                    notifications.append({
                        "type": "error_detected",
                        "message": f"I noticed something: {item}",
                        "detail": item,
                    })

        # User seems stuck
        if new.get("needs_help") and not old.get("needs_help"):
            notifications.append({
                "type": "help_offered",
                "message": new.get(
                    "suggestion", "It looks like you might need help."
                ),
            })

        return notifications

    def get_current_context(self) -> Optional[Dict[str, Any]]:
        """Get the most recent screen context analysis."""
        return self._current_context

    def get_context_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent context history."""
        return self._context_history[-limit:]

    def update_config(self, **kwargs):
        """Update monitor configuration."""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value

        # Restart if interval changed and currently running
        if "interval_seconds" in kwargs and self._is_running:
            self.stop()
            self.start()

    def get_status(self) -> Dict[str, Any]:
        """Get monitor status."""
        return {
            "enabled": self.config.get("enabled", False),
            "is_running": self._is_running,
            "interval_seconds": self.config.get("interval_seconds"),
            "context_history_size": len(self._context_history),
            "current_app": (
                self._current_context.get("active_app")
                if self._current_context
                else None
            ),
        }


def get_screen_monitor() -> ScreenMonitor:
    """Get the singleton ScreenMonitor instance."""
    return ScreenMonitor()
