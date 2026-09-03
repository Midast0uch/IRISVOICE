"""
State Persistence Optimizer
Ensures field updates persist within 100ms with write batching.
"""
import asyncio
import logging
import time
import json
from typing import Dict, Any, Optional, Callable, Awaitable
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PersistenceMetrics:
    """Track persistence performance metrics."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def record(self, persistence_time_ms: float):
        """Record a persistence time sample."""
        self.samples.append(persistence_time_ms)
    
    def get_p95(self) -> float:
        """Get 95th percentile persistence time."""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[idx]
    
    def get_mean(self) -> float:
        """Get mean persistence time."""
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)
    
    def get_max(self) -> float:
        """Get maximum persistence time."""
        if not self.samples:
            return 0.0
        return max(self.samples)


@dataclass
class WriteBatch:
    """Batch of write operations."""
    updates: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    
    def add_update(self, key: str, value: Any):
        """Add an update to the batch."""
        self.updates[key] = value
    
    def age_ms(self) -> float:
        """Get age of batch in milliseconds."""
        return (time.time() - self.created_at) * 1000
    
    def is_empty(self) -> bool:
        """Check if batch is empty."""
        return len(self.updates) == 0


class StateOptimizer:
    """
    Optimizes state persistence with write batching.
    
    Features:
    - Write batching for rapid updates
    - Persistence time monitoring
    - Automatic batch flushing
    """
    
    # Configuration
    TARGET_PERSISTENCE_TIME_MS = 100  # Target persistence time
    MAX_BATCH_SIZE = 20  # Maximum updates per batch
    MAX_BATCH_AGE_MS = 50  # Maximum batch age before forced flush
    FLUSH_INTERVAL_MS = 10  # How often to check for batch flushes
    
    def __init__(self, persist_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None):
        self.persistence_metrics = PersistenceMetrics()
        self.write_batch = WriteBatch()
        self._persist_callback = persist_callback
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()
    
    async def start(self):
        """Start the optimizer background tasks."""
        if self._running:
            return
        
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("State optimizer started")
    
    async def stop(self):
        """Stop the optimizer background tasks."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Flush any remaining updates
        if self._persist_callback:
            await self._flush_batch()
        
        logger.info("State optimizer stopped")
    
    async def _flush_loop(self):
        """Background task to periodically flush batches."""
        try:
            while self._running:
                await asyncio.sleep(self.FLUSH_INTERVAL_MS / 1000)
                
                # Check if batch needs flushing
                if not self.write_batch.is_empty() and self.write_batch.age_ms() >= self.MAX_BATCH_AGE_MS:
                    if self._persist_callback:
                        await self._flush_batch()
        
        except asyncio.CancelledError:
            logger.debug("Flush loop cancelled")
        except Exception as e:
            logger.error(f"Error in flush loop: {e}", exc_info=True)
    
    async def _flush_batch(self):
        """Flush the current write batch."""
        async with self._lock:
            if self.write_batch.is_empty():
                return
            
            start_time = time.time()
            
            try:
                # Persist all updates
                if self._persist_callback:
                    await self._persist_callback(self.write_batch.updates)
                
                # Record metrics
                persistence_time_ms = (time.time() - start_time) * 1000
                self.persistence_metrics.record(persistence_time_ms)
                
                if persistence_time_ms > self.TARGET_PERSISTENCE_TIME_MS:
                    logger.warning(
                        f"Batch persistence took {persistence_time_ms:.2f}ms, exceeds {self.TARGET_PERSISTENCE_TIME_MS}ms target"
                    )
                
                # Clear batch
                self.write_batch = WriteBatch()
            
            except Exception as e:
                logger.error(f"Error flushing batch: {e}", exc_info=True)
                raise
    
    async def update_field(
        self,
        key: str,
        value: Any,
        persist_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ):
        """
        Update a field with batching.
        
        Args:
            key: Field key
            value: Field value
            persist_callback: Optional callback for immediate persistence
        """
        async with self._lock:
            # Add to batch
            self.write_batch.add_update(key, value)
            
            # Flush if batch is full
            if len(self.write_batch.updates) >= self.MAX_BATCH_SIZE:
                callback = persist_callback or self._persist_callback
                if callback:
                    start_time = time.time()
                    await callback(self.write_batch.updates)
                    persistence_time_ms = (time.time() - start_time) * 1000
                    self.persistence_metrics.record(persistence_time_ms)
                    self.write_batch = WriteBatch()
    
    async def flush(self):
        """Manually flush all pending updates."""
        if self._persist_callback:
            await self._flush_batch()
    
    def get_metrics(self) -> dict:
        """Get current performance metrics."""
        return {
            "p95_persistence_time_ms": self.persistence_metrics.get_p95(),
            "mean_persistence_time_ms": self.persistence_metrics.get_mean(),
            "max_persistence_time_ms": self.persistence_metrics.get_max(),
            "pending_updates": len(self.write_batch.updates),
            "total_samples": len(self.persistence_metrics.samples),
            "target_persistence_time_ms": self.TARGET_PERSISTENCE_TIME_MS,
        }
    
    def is_meeting_target(self) -> bool:
        """Check if we're meeting the persistence time target."""
        p95 = self.persistence_metrics.get_p95()
        return p95 <= self.TARGET_PERSISTENCE_TIME_MS if p95 > 0 else True


# Global instance
_optimizer: Optional[StateOptimizer] = None


def get_state_optimizer(persist_callback=None) -> StateOptimizer:
    """Get or create the singleton StateOptimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = StateOptimizer(persist_callback)
    return _optimizer
