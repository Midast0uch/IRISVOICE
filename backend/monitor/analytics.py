"""
Analytics Manager — Token usage, latency metrics, cost estimation.

Now persists to a separate SQLite DB (data/monitor.db) via MonitorStore.
Completely isolated from the agent memory DB.

Tracks per-model usage for the Monitor dashboard panel.
"""
import time
from typing import Dict, Any, List, Optional

from .store import MonitorStore, get_monitor_store


class AnalyticsManager:
    """
    Manages usage analytics:
    - Token usage tracking (per-model)
    - Latency metrics
    - Cost estimation
    - Session statistics
    - Persistent storage via MonitorStore (data/monitor.db)
    """

    _instance: Optional['AnalyticsManager'] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if AnalyticsManager._initialized:
            return

        self._store: MonitorStore = get_monitor_store()
        self._session_start = time.time()

        AnalyticsManager._initialized = True

    def record_usage(
        self,
        *,
        session_id: str = "",
        model: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        audio_tokens: int = 0,
        latency_ms: float = 0,
        mode: str = "conversation",
    ) -> None:
        """Record a usage event and persist to SQLite.

        Args:
            session_id: Active session identifier.
            model: Model name used for this call (e.g. 'gpt-4o-mini', 'local-model').
            prompt_tokens: Input tokens from the API response usage field.
            completion_tokens: Output tokens from the API response usage field.
            audio_tokens: Audio tokens (TTS/STT), if applicable.
            latency_ms: Round-trip latency in milliseconds.
            mode: 'conversation' | 'tool' | 'voice'
        """
        self._store.record_usage(
            session_id=session_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            audio_tokens=audio_tokens,
            latency_ms=latency_ms,
            mode=mode,
        )

    def get_session_stats(self) -> Dict[str, Any]:
        """Aggregate statistics across all recorded usage."""
        stats = self._store.get_session_stats()
        stats["session_duration_minutes"] = round(
            (time.time() - self._session_start) / 60, 2
        )
        return stats

    def get_model_breakdown(self) -> List[Dict[str, Any]]:
        """Per-model aggregated stats with percentage of total tokens."""
        return self._store.get_model_breakdown()

    def get_latency_metrics(self) -> Dict[str, Any]:
        """Detailed latency distribution (min/max/avg/p50/p95)."""
        return self._store.get_latency_metrics()

    def get_recent_records(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Most recent usage records for activity feed."""
        return self._store.get_recent_records(limit)

    def get_all_analytics(self) -> Dict[str, Any]:
        """Everything the frontend Monitor panel needs in one call."""
        return self._store.get_all_analytics()

    def reset_session(self) -> None:
        """Reset the in-memory session timer (does NOT delete persisted data)."""
        self._session_start = time.time()


def get_analytics_manager() -> AnalyticsManager:
    """Get the singleton AnalyticsManager instance."""
    return AnalyticsManager()
