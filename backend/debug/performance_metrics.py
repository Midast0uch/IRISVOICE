
import asyncio
import time
import json
import psutil
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class PerformanceMetric:
    """Represents a single performance measurement."""
    timestamp: datetime
    metric_type: str
    value: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class PerformanceMonitor:
    """
    Monitors system and application performance metrics.
    Provides real-time performance data for debugging and optimization.
    """

    def __init__(self, collection_interval: float = 1.0, session_manager=None, state_manager=None):
        self.collection_interval = collection_interval
        self.metrics: List[PerformanceMetric] = []
        self.is_running = False
        self.start_time: Optional[datetime] = None
        self.worker_task: Optional[asyncio.Task] = None
        self.session_manager = session_manager
        self.state_manager = state_manager

    async def start(self):
        """Starts the performance monitoring."""
        if self.is_running:
            return

        self.is_running = True
        self.start_time = datetime.now(timezone.utc)
        self.worker_task = asyncio.create_task(self._collect_metrics())

    async def stop(self):
        """Stops the performance monitoring."""
        if not self.is_running:
            return

        self.is_running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

    async def _collect_metrics(self):
        """Collects performance metrics in the background."""
        while self.is_running:
            try:
                await self._collect_system_metrics()
                await self._collect_application_metrics()
                await asyncio.sleep(self.collection_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error collecting metrics: {e}")
                await asyncio.sleep(self.collection_interval)

    async def _collect_system_metrics(self):
        """Collects system-level performance metrics."""
        try:
            # CPU usage (non-blocking)
            cpu_percent = psutil.cpu_percent(interval=None)
            self.add_metric("cpu_usage", cpu_percent, {"unit": "percent"})

            # Memory usage
            memory = psutil.virtual_memory()
            self.add_metric("memory_usage", memory.percent, {"unit": "percent"})
            self.add_metric("memory_available", memory.available, {"unit": "bytes"})

            # Disk usage
            disk = psutil.disk_usage('/')
            self.add_metric("disk_usage", disk.percent, {"unit": "percent"})
            self.add_metric("disk_free", disk.free, {"unit": "bytes"})

        except Exception as e:
            print(f"Error collecting system metrics: {e}")

    async def _collect_application_metrics(self):
        """Collects application-specific performance metrics."""
        try:
            # Session count
            if self.session_manager:
                session_count = len(self.session_manager.sessions)
                self.add_metric("active_sessions", session_count)

                # Memory usage per session
                total_memory = 0
                for session_id in self.session_manager.sessions:
                    try:
                        if self.state_manager:
                            memory = await self.state_manager.get_memory_usage(session_id)
                            total_memory += memory
                            self.add_metric("session_memory", memory, {"session_id": session_id})
                    except Exception:
                        pass

                self.add_metric("total_session_memory", total_memory, {"unit": "bytes"})

        except Exception as e:
            print(f"Error collecting application metrics: {e}")

    def add_metric(self, metric_type: str, value: float, metadata: Optional[Dict[str, Any]] = None):
        """Adds a custom metric to the collection."""
        metric = PerformanceMetric(
            timestamp=datetime.now(timezone.utc),
            metric_type=metric_type,
            value=value,
            metadata=metadata or {}
        )
        self.metrics.append(metric)

    def get_metrics(self, metric_type: Optional[str] = None, time_range: Optional[tuple] = None) -> List[PerformanceMetric]:
        """
        Retrieves metrics, optionally filtered by type and time range.
        
        Args:
            metric_type: Filter by metric type
            time_range: Tuple of (start_time, end_time) as datetime objects
        """
        filtered_metrics = self.metrics

        if metric_type:
            filtered_metrics = [m for m in filtered_metrics if m.metric_type == metric_type]

        if time_range and len(time_range) == 2:
            start_time, end_time = time_range
            filtered_metrics = [m for m in filtered_metrics if start_time <= m.timestamp <= end_time]

        return filtered_metrics

    def get_summary(self) -> Dict[str, Any]:
        """Gets a summary of collected metrics."""
        if not self.metrics:
            return {"error": "No metrics collected"}

        summary = {
            "total_metrics": len(self.metrics),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": datetime.now(timezone.utc).isoformat(),
            "metric_types": list(set(m.metric_type for m in self.metrics)),
            "collection_interval": self.collection_interval,
        }

        # Calculate averages for common metrics
        for metric_type in ["cpu_usage", "memory_usage", "active_sessions"]:
            type_metrics = [m for m in self.metrics if m.metric_type == metric_type]
            if type_metrics:
                summary[f"avg_{metric_type}"] = sum(m.value for m in type_metrics) / len(type_metrics)

        return summary

    def export_metrics(self, export_path: str) -> bool:
        """Exports collected metrics to a JSON file."""
        try:
            data = {
                "metadata": self.get_summary(),
                "metrics": [
                    {
                        "timestamp": m.timestamp.isoformat(),
                        "metric_type": m.metric_type,
                        "value": m.value,
                        "metadata": m.metadata
                    }
                    for m in self.metrics
                ]
            }

            with open(export_path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except (IOError, TypeError) as e:
            print(f"Error exporting metrics: {e}")
            return False

# Global performance monitor instance
performance_monitor = PerformanceMonitor()
