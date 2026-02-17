"""
IRIS Memory Bounds and Tracking
Provides memory management and bounds checking for sessions
"""
import sys
import gc
import weakref
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import threading
import psutil
import os


@dataclass
class MemorySnapshot:
    """Snapshot of memory usage at a point in time"""
    timestamp: datetime
    total_memory_mb: float
    state_size_kb: float
    object_count: int
    thread_count: int
    process_memory_mb: float


@dataclass
class MemoryBounds:
    """Memory bounds configuration for a session"""
    max_memory_mb: int = 100  # Maximum memory per session in MB
    max_state_size_kb: int = 1024  # Maximum state size in KB
    warning_threshold_percent: float = 0.8  # Warn when 80% of limit reached
    enforce_hard_limit: bool = True  # Whether to enforce hard limits
    
    def check_bounds(self, current_memory_mb: float, current_state_kb: float) -> Dict[str, Any]:
        """Check if current usage is within bounds"""
        memory_ok = current_memory_mb <= self.max_memory_mb
        state_ok = current_state_kb <= self.max_state_size_kb
        
        memory_warning = current_memory_mb > (self.max_memory_mb * self.warning_threshold_percent)
        state_warning = current_state_kb > (self.max_state_size_kb * self.warning_threshold_percent)
        
        return {
            "within_bounds": memory_ok and state_ok,
            "memory_ok": memory_ok,
            "state_ok": state_ok,
            "memory_warning": memory_warning,
            "state_warning": state_warning,
            "memory_usage_percent": (current_memory_mb / self.max_memory_mb) * 100 if self.max_memory_mb > 0 else 0,
            "state_usage_percent": (current_state_kb / self.max_state_size_kb) * 100 if self.max_state_size_kb > 0 else 0
        }


class MemoryTracker:
    """Tracks memory usage for objects and provides bounds checking"""
    
    def __init__(self, name: str):
        self.name = name
        self.session_id = name
        self._tracked_objects: Dict[int, Dict[str, Any]] = {}
        self._object_sizes: Dict[int, int] = {}
        self._total_memory_bytes = 0
        self._state_size_bytes = 0
        self._snapshots: List[MemorySnapshot] = []
        self._lock = threading.Lock()
        
        # Get initial process memory
        self._process = psutil.Process(os.getpid())
        self._initial_memory = self._process.memory_info().rss / 1024 / 1024  # MB
    
    def track_object_creation(self, obj: Any, obj_type: str = "unknown", metadata: Optional[Dict[str, Any]] = None):
        """Track creation of an object"""
        obj_id = id(obj)
        obj_size = sys.getsizeof(obj)
        
        with self._lock:
            self._tracked_objects[obj_id] = {
                "type": obj_type,
                "created_at": datetime.now(),
                "metadata": metadata or {},
                "weakref": weakref.ref(obj, self._object_finalized)
            }
            self._object_sizes[obj_id] = obj_size
            self._total_memory_bytes += obj_size
            
            # Track state objects separately
            if obj_type in ["state", "IRISState", "dict", "list"]:
                self._state_size_bytes += obj_size
    
    def track_object_deletion(self, obj: Any):
        """Track deletion of an object"""
        obj_id = id(obj)
        
        with self._lock:
            if obj_id in self._tracked_objects:
                obj_size = self._object_sizes.get(obj_id, 0)
                self._total_memory_bytes -= obj_size
                
                # Update state size if applicable
                if self._tracked_objects[obj_id]["type"] in ["state", "IRISState", "dict", "list"]:
                    self._state_size_bytes -= obj_size
                
                del self._tracked_objects[obj_id]
                del self._object_sizes[obj_id]
    
    def _object_finalized(self, weak_ref):
        """Called when a tracked object is garbage collected"""
        # Find the object ID from the weak reference
        for obj_id, info in list(self._tracked_objects.items()):
            if info.get("weakref") is weak_ref:
                self.track_object_deletion(object())  # Dummy object to trigger cleanup
                break
    
    def track_field_change(self, subnode_id: str, field_id: str, old_value: Any, new_value: Any):
        """Track changes to state fields"""
        old_size = sys.getsizeof(old_value) if old_value is not None else 0
        new_size = sys.getsizeof(new_value) if new_value is not None else 0
        size_delta = new_size - old_size
        
        with self._lock:
            self._state_size_bytes += size_delta
            self._total_memory_bytes += size_delta
            
            # Track the field object
            field_key = f"{subnode_id}:{field_id}"
            # Implementation would track field objects here
    
    def track_state_change(self, change_type: str, old_value: Any, new_value: Any):
        """Track changes to state objects"""
        old_size = sys.getsizeof(old_value) if old_value is not None else 0
        new_size = sys.getsizeof(new_value) if new_value is not None else 0
        size_delta = new_size - old_size
        
        with self._lock:
            self._state_size_bytes += size_delta
            self._total_memory_bytes += size_delta
    
    def track_confirmed_node_change(self, node_id: str, values: Dict[str, Any]):
        """Track changes to confirmed nodes"""
        node_size = sys.getsizeof(values)
        
        with self._lock:
            self._state_size_bytes += node_size
            self._total_memory_bytes += node_size
    
    def track_confirmed_nodes_clear(self, old_count: int):
        """Track clearing of confirmed nodes"""
        # Rough estimate - actual implementation would track individual nodes
        estimated_size_per_node = 1024  # 1KB per node estimate
        size_reduction = old_count * estimated_size_per_node
        
        with self._lock:
            self._state_size_bytes -= size_reduction
            self._total_memory_bytes -= size_reduction
    
    def track_theme_change(self, old_theme: dict, new_theme: dict):
        """Track theme changes"""
        old_size = sys.getsizeof(str(old_theme))
        new_size = sys.getsizeof(str(new_theme))
        size_delta = new_size - old_size
        
        with self._lock:
            self._state_size_bytes += size_delta
            self._total_memory_bytes += size_delta
    
    def get_total_memory_mb(self) -> float:
        """Get total tracked memory in MB"""
        with self._lock:
            return self._total_memory_bytes / (1024 * 1024)
    
    def get_state_size_kb(self) -> float:
        """Get state-specific memory in KB"""
        with self._lock:
            return self._state_size_bytes / 1024
    
    def get_object_count(self) -> int:
        """Get number of tracked objects"""
        with self._lock:
            return len(self._tracked_objects)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get detailed memory statistics"""
        with self._lock:
            current_memory = self._process.memory_info().rss / 1024 / 1024
            
            return {
                "session_id": self.session_id,
                "total_memory_mb": self.get_total_memory_mb(),
                "state_size_kb": self.get_state_size_kb(),
                "object_count": self.get_object_count(),
                "process_memory_mb": current_memory,
                "memory_growth_mb": current_memory - self._initial_memory,
                "tracked_objects_by_type": self._get_objects_by_type(),
                "thread_count": threading.active_count()
            }
    
    def _get_objects_by_type(self) -> Dict[str, int]:
        """Get count of objects by type"""
        type_counts = {}
        for info in self._tracked_objects.values():
            obj_type = info.get("type", "unknown")
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
        return type_counts
    
    def take_memory_snapshot(self) -> MemorySnapshot:
        """Take a snapshot of current memory usage"""
        snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            total_memory_mb=self.get_total_memory_mb(),
            state_size_kb=self.get_state_size_kb(),
            object_count=self.get_object_count(),
            thread_count=threading.active_count(),
            process_memory_mb=self._process.memory_info().rss / 1024 / 1024
        )
        
        with self._lock:
            self._snapshots.append(snapshot)
            
            # Keep only last 100 snapshots
            if len(self._snapshots) > 100:
                self._snapshots = self._snapshots[-100:]
        
        return snapshot
    
    def get_memory_snapshots(self, limit: int = 10) -> List[MemorySnapshot]:
        """Get recent memory snapshots"""
        with self._lock:
            return self._snapshots[-limit:]
    
    def cleanup(self):
        """Clean up memory tracker resources"""
        with self._lock:
            # Force garbage collection
            gc.collect()
            
            # Clear tracked objects
            self._tracked_objects.clear()
            self._object_sizes.clear()
            self._total_memory_bytes = 0
            self._state_size_bytes = 0
            self._snapshots.clear()
    
    def force_garbage_collection(self) -> Dict[str, Any]:
        """Force garbage collection and return stats"""
        before_stats = self.get_memory_stats()
        
        # Force garbage collection
        gc.collect()
        
        after_stats = self.get_memory_stats()
        
        return {
            "before": before_stats,
            "after": after_stats,
            "memory_freed_mb": before_stats["total_memory_mb"] - after_stats["total_memory_mb"],
            "objects_freed": before_stats["object_count"] - after_stats["object_count"]
        }


class GlobalMemoryManager:
    """Global memory manager for all sessions"""
    
    def __init__(self):
        self._trackers: Dict[str, MemoryTracker] = {}
        self._global_bounds = MemoryBounds(
            max_memory_mb=1024,  # 1GB global limit
            max_state_size_kb=100 * 1024,  # 100MB global state limit
            enforce_hard_limit=True
        )
    
    def create_tracker(self, session_id: str) -> MemoryTracker:
        """Create a new memory tracker for a session"""
        tracker = MemoryTracker(session_id)
        self._trackers[session_id] = tracker
        return tracker
    
    def get_tracker(self, session_id: str) -> Optional[MemoryTracker]:
        """Get a memory tracker for a session"""
        return self._trackers.get(session_id)
    
    def remove_tracker(self, session_id: str):
        """Remove a memory tracker"""
        if session_id in self._trackers:
            self._trackers[session_id].cleanup()
            del self._trackers[session_id]
    
    def get_global_memory_usage(self) -> Dict[str, Any]:
        """Get global memory usage across all sessions"""
        total_memory = sum(tracker.get_total_memory_mb() for tracker in self._trackers.values())
        total_state = sum(tracker.get_state_size_kb() for tracker in self._trackers.values())
        total_objects = sum(tracker.get_object_count() for tracker in self._trackers.values())
        
        bounds_check = self._global_bounds.check_bounds(total_memory, total_state)
        
        return {
            "total_sessions": len(self._trackers),
            "total_memory_mb": total_memory,
            "total_state_kb": total_state,
            "total_objects": total_objects,
            "within_global_bounds": bounds_check["within_bounds"],
            "memory_usage_percent": bounds_check["memory_usage_percent"],
            "state_usage_percent": bounds_check["state_usage_percent"],
            "sessions": [
                {
                    "session_id": session_id,
                    "memory_mb": tracker.get_total_memory_mb(),
                    "state_kb": tracker.get_state_size_kb(),
                    "objects": tracker.get_object_count()
                }
                for session_id, tracker in self._trackers.items()
            ]
        }
    
    def force_global_garbage_collection(self) -> Dict[str, Any]:
        """Force garbage collection across all sessions"""
        results = {}
        total_freed = 0
        
        for session_id, tracker in self._trackers.items():
            result = tracker.force_garbage_collection()
            results[session_id] = result
            total_freed += result["memory_freed_mb"]
        
        return {
            "session_results": results,
            "total_memory_freed_mb": total_freed,
            "global_stats_after": self.get_global_memory_usage()
        }


# Global memory manager instance
_global_memory_manager = GlobalMemoryManager()


def get_global_memory_manager() -> GlobalMemoryManager:
    """Get the global memory manager"""
    return _global_memory_manager