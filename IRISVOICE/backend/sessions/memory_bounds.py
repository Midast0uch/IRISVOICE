"""
IRIS Session Memory Bounds
Tracks memory usage per session and enforces limits.
"""
import sys
import gc
import weakref
import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemorySnapshot:
    """Point-in-time memory usage snapshot."""
    timestamp: datetime
    total_memory_mb: float
    state_size_kb: float
    object_count: int
    thread_count: int
    process_rss_mb: float


@dataclass
class MemoryBounds:
    """Memory limits for a session."""
    max_memory_mb: int = 512
    max_state_size_kb: int = 1024
    warning_threshold_percent: int = 80

    def check_bounds(self, current_memory_mb: float, current_state_kb: float) -> Dict[str, Any]:
        """Return bounds check result dict."""
        memory_ok = current_memory_mb <= self.max_memory_mb
        state_ok = current_state_kb <= self.max_state_size_kb
        memory_warning = current_memory_mb >= (self.max_memory_mb * self.warning_threshold_percent / 100)
        state_warning = current_state_kb >= (self.max_state_size_kb * self.warning_threshold_percent / 100)
        return {
            "memory_ok": memory_ok,
            "state_ok": state_ok,
            "memory_warning": memory_warning,
            "state_warning": state_warning,
            "within_bounds": memory_ok and state_ok,
        }


class MemoryTracker:
    """Tracks memory usage for a session."""

    def __init__(self, name: str):
        self.session_id = name
        self._tracked_objects: Dict[int, Any] = {}
        self._object_sizes: Dict[int, int] = {}
        self._total_memory_bytes: int = 0
        self._state_size_bytes: int = 0
        self._snapshots: List[MemorySnapshot] = []
        self._lock = threading.Lock()
        try:
            import psutil
            self._process = psutil.Process()
            self._initial_memory = self._process.memory_info().rss
        except Exception:
            self._process = None
            self._initial_memory = 0

    def track_object_creation(self, obj: Any, obj_type: str = "", metadata: Any = None) -> None:
        obj_id = id(obj)
        obj_size = sys.getsizeof(obj)
        with self._lock:
            self._tracked_objects[obj_id] = {
                "type": obj_type,
                "size": obj_size,
                "created": datetime.now(),
            }
            self._object_sizes[obj_id] = obj_size
            self._total_memory_bytes += obj_size

    def track_object_deletion(self, obj: Any) -> None:
        obj_id = id(obj)
        with self._lock:
            obj_size = self._object_sizes.get(obj_id, 0)
            self._tracked_objects.pop(obj_id, None)
            self._object_sizes.pop(obj_id, None)
            self._total_memory_bytes = max(0, self._total_memory_bytes - obj_size)
            self._state_size_bytes = max(0, self._state_size_bytes - obj_size)

    def _object_finalized(self, weak_ref: Any, obj_id: int) -> None:
        info = None
        for oid, i in list(self._tracked_objects.items()):
            if oid == obj_id:
                info = i
                break
        self.track_object_deletion(object())

    def track_field_change(self, section_id: str, field_id: str, old_value: Any, new_value: Any) -> None:
        old_size = sys.getsizeof(old_value) if old_value is not None else 0
        new_size = sys.getsizeof(new_value) if new_value is not None else 0
        size_delta = new_size - old_size
        with self._lock:
            self._state_size_bytes = max(0, self._state_size_bytes + size_delta)
            self._total_memory_bytes = max(0, self._total_memory_bytes + size_delta)

    def track_state_change(self, change_type: str, old_value: Any, new_value: Any) -> None:
        old_size = sys.getsizeof(old_value) if old_value is not None else 0
        new_size = sys.getsizeof(new_value) if new_value is not None else 0
        size_delta = new_size - old_size
        with self._lock:
            self._state_size_bytes = max(0, self._state_size_bytes + size_delta)
            self._total_memory_bytes = max(0, self._total_memory_bytes + size_delta)

    def track_theme_change(self, old_theme: Any, new_theme: Any) -> None:
        old_size = sys.getsizeof(str(old_theme))
        new_size = sys.getsizeof(str(new_theme))
        size_delta = new_size - old_size
        with self._lock:
            self._state_size_bytes = max(0, self._state_size_bytes + size_delta)
            self._total_memory_bytes = max(0, self._total_memory_bytes + size_delta)

    def get_total_memory_mb(self) -> float:
        with self._lock:
            return self._total_memory_bytes / (1024 * 1024)

    def get_state_size_kb(self) -> float:
        with self._lock:
            return self._state_size_bytes / 1024

    def get_object_count(self) -> int:
        with self._lock:
            return len(self._tracked_objects)

    def _get_objects_by_type(self) -> Dict[str, int]:
        type_counts: Dict[str, int] = {}
        for info in self._tracked_objects.values():
            obj_type = info.get("type", "unknown")
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
        return type_counts

    def get_memory_stats(self) -> Dict[str, Any]:
        with self._lock:
            current_memory = 0
            if self._process:
                try:
                    current_memory = self._process.memory_info().rss / (1024 * 1024)
                except Exception:
                    pass
            return {
                "session_id": self.session_id,
                "total_memory_mb": self.get_total_memory_mb(),
                "state_size_kb": self.get_state_size_kb(),
                "object_count": self.get_object_count(),
                "process_rss_mb": current_memory,
                "objects_by_type": self._get_objects_by_type(),
            }

    def take_memory_snapshot(self) -> MemorySnapshot:
        process_rss = 0
        if self._process:
            try:
                process_rss = self._process.memory_info().rss / (1024 * 1024)
            except Exception:
                pass
        snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            total_memory_mb=self.get_total_memory_mb(),
            state_size_kb=self.get_state_size_kb(),
            object_count=self.get_object_count(),
            thread_count=threading.active_count(),
            process_rss_mb=process_rss,
        )
        with self._lock:
            self._snapshots.append(snapshot)
            if len(self._snapshots) > 100:
                self._snapshots = self._snapshots[-100:]
        return snapshot

    def get_memory_snapshots(self, limit: int = 10) -> List[MemorySnapshot]:
        with self._lock:
            return self._snapshots[-limit:]

    def cleanup(self) -> None:
        with self._lock:
            gc.collect()
            self._tracked_objects.clear()
            self._object_sizes.clear()
            self._total_memory_bytes = 0
            self._state_size_bytes = 0
            self._snapshots.clear()

    def force_garbage_collection(self) -> Dict[str, Any]:
        before_stats = self.get_memory_stats()
        gc.collect()
        after_stats = self.get_memory_stats()
        return {"before": before_stats, "after": after_stats}


class GlobalMemoryManager:
    """Manages memory trackers across all sessions."""

    def __init__(self):
        self._trackers: Dict[str, MemoryTracker] = {}
        self._global_bounds = MemoryBounds()

    def create_tracker(self, session_id: str) -> MemoryTracker:
        tracker = MemoryTracker(session_id)
        self._trackers[session_id] = tracker
        return tracker

    def get_tracker(self, session_id: str) -> Optional[MemoryTracker]:
        return self._trackers.get(session_id)

    def remove_tracker(self, session_id: str) -> None:
        tracker = self._trackers.pop(session_id, None)
        if tracker:
            tracker.cleanup()

    def get_global_memory_usage(self) -> Dict[str, Any]:
        total_memory = sum(t.get_total_memory_mb() for t in self._trackers.values())
        total_state = sum(t.get_state_size_kb() for t in self._trackers.values())
        total_objects = sum(t.get_object_count() for t in self._trackers.values())
        bounds_check = self._global_bounds.check_bounds(total_memory, total_state)
        return {
            "total_memory_mb": total_memory,
            "total_state_kb": total_state,
            "total_objects": total_objects,
            "session_count": len(self._trackers),
            "bounds": bounds_check,
            "sessions": {
                sid: {
                    "memory_mb": t.get_total_memory_mb(),
                    "state_kb": t.get_state_size_kb(),
                    "objects": t.get_object_count(),
                }
                for sid, t in self._trackers.items()
            },
        }

    def force_global_garbage_collection(self) -> Dict[str, Any]:
        results = {}
        total_freed = 0
        for session_id, tracker in self._trackers.items():
            result = tracker.force_garbage_collection()
            results[session_id] = result
        return {"sessions": results, "global_usage": self.get_global_memory_usage()}


_global_memory_manager: Optional[GlobalMemoryManager] = None


def get_global_memory_manager() -> GlobalMemoryManager:
    global _global_memory_manager
    if _global_memory_manager is None:
        _global_memory_manager = GlobalMemoryManager()
    return _global_memory_manager
