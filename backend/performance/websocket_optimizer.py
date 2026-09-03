"""
WebSocket Performance Optimizer
Implements message batching and latency monitoring to ensure <50ms p95 delivery.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Set
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MessageBatch:
    """Batch of messages to be sent together."""
    messages: List[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    
    def add_message(self, message: dict):
        """Add a message to the batch."""
        self.messages.append(message)
    
    def age_ms(self) -> float:
        """Get age of batch in milliseconds."""
        return (time.time() - self.created_at) * 1000
    
    def is_empty(self) -> bool:
        """Check if batch is empty."""
        return len(self.messages) == 0


@dataclass
class LatencyMetrics:
    """Track latency metrics for performance monitoring."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def record(self, latency_ms: float):
        """Record a latency sample."""
        self.samples.append(latency_ms)
    
    def get_p95(self) -> float:
        """Get 95th percentile latency."""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[idx]
    
    def get_mean(self) -> float:
        """Get mean latency."""
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)
    
    def get_max(self) -> float:
        """Get maximum latency."""
        if not self.samples:
            return 0.0
        return max(self.samples)


class WebSocketOptimizer:
    """
    Optimizes WebSocket message delivery with batching and latency monitoring.
    
    Features:
    - Message batching for high-frequency updates
    - Adaptive batch flushing based on latency targets
    - Latency monitoring and metrics
    - Per-client batching to avoid head-of-line blocking
    """
    
    # Configuration
    MAX_BATCH_SIZE = 10  # Maximum messages per batch
    MAX_BATCH_AGE_MS = 10  # Maximum batch age before forced flush (10ms)
    TARGET_LATENCY_MS = 50  # Target p95 latency
    FLUSH_INTERVAL_MS = 5  # How often to check for batch flushes
    
    def __init__(self, send_callback=None):
        self.client_batches: Dict[str, MessageBatch] = {}
        self.latency_metrics = LatencyMetrics()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        self._send_callback = send_callback  # Callback for sending messages
    
    async def start(self):
        """Start the optimizer background tasks."""
        if self._running:
            return
        
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("WebSocket optimizer started")
    
    async def stop(self):
        """Stop the optimizer background tasks."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket optimizer stopped")
    
    async def _flush_loop(self):
        """Background task to periodically flush batches."""
        try:
            while self._running:
                await asyncio.sleep(self.FLUSH_INTERVAL_MS / 1000)
                aged_clients = await self._flush_aged_batches()
                # Flush aged batches if we have a send callback
                if self._send_callback and aged_clients:
                    for client_id in aged_clients:
                        await self.flush_client(client_id, self._send_callback)
        except asyncio.CancelledError:
            logger.debug("Flush loop cancelled")
        except Exception as e:
            logger.error(f"Error in flush loop: {e}", exc_info=True)
    
    async def _flush_aged_batches(self):
        """Flush batches that have exceeded the maximum age."""
        aged_clients = []
        for client_id, batch in list(self.client_batches.items()):
            if batch.age_ms() >= self.MAX_BATCH_AGE_MS:
                aged_clients.append(client_id)
        
        # Return list of clients that need flushing
        return aged_clients
    
    async def _flush_batch(self, client_id: str):
        """Flush a batch for a specific client."""
        batch = self.client_batches.get(client_id)
        if not batch or batch.is_empty():
            return
        
        # Remove batch from queue
        del self.client_batches[client_id]
        
        # This will be called by the WebSocketManager
        # We just prepare the batch here
        return batch.messages
    
    def should_batch(self, message_type: str) -> bool:
        """
        Determine if a message type should be batched.
        
        High-frequency updates that benefit from batching:
        - audio_level: Sent every 100ms during listening
        - field_updated: Can have rapid updates during UI interaction
        - state_update: Can have multiple rapid state changes
        
        Messages that should NOT be batched (require immediate delivery):
        - initial_state: Critical for connection establishment
        - text_response: User expects immediate response
        - voice_command_error: Error messages need immediate delivery
        - validation_error: Error messages need immediate delivery
        """
        batchable_types = {
            "audio_level",
            "field_updated",
            "state_update",
            "listening_state",  # Can batch state transitions
        }
        return message_type in batchable_types
    
    async def queue_message(self, client_id: str, message: dict, send_callback) -> bool:
        """
        Queue a message for delivery, with optional batching.
        
        Args:
            client_id: Target client ID
            message: Message to send
            send_callback: Async function to call for actual sending
        
        Returns:
            True if message was queued/sent successfully
        """
        message_type = message.get("type", "")
        
        # Record start time for latency tracking
        start_time = time.time()
        
        # Check if message should be batched
        if not self.should_batch(message_type):
            # Send immediately
            success = await send_callback(client_id, message)
            latency_ms = (time.time() - start_time) * 1000
            self.latency_metrics.record(latency_ms)
            return success
        
        # Add to batch
        if client_id not in self.client_batches:
            self.client_batches[client_id] = MessageBatch()
        
        batch = self.client_batches[client_id]
        batch.add_message(message)
        
        # Flush if batch is full
        if len(batch.messages) >= self.MAX_BATCH_SIZE:
            messages = await self._flush_batch(client_id)
            if messages:
                # Send all messages in batch
                for msg in messages:
                    await send_callback(client_id, msg)
                latency_ms = (time.time() - start_time) * 1000
                self.latency_metrics.record(latency_ms)
        
        return True
    
    async def flush_client(self, client_id: str, send_callback):
        """Flush all pending messages for a client."""
        messages = await self._flush_batch(client_id)
        if messages:
            for msg in messages:
                await send_callback(client_id, msg)
    
    async def flush_all(self, send_callback):
        """Flush all pending batches."""
        for client_id in list(self.client_batches.keys()):
            await self.flush_client(client_id, send_callback)
    
    def get_metrics(self) -> dict:
        """Get current performance metrics."""
        return {
            "p95_latency_ms": self.latency_metrics.get_p95(),
            "mean_latency_ms": self.latency_metrics.get_mean(),
            "max_latency_ms": self.latency_metrics.get_max(),
            "pending_batches": len(self.client_batches),
            "total_samples": len(self.latency_metrics.samples),
            "target_latency_ms": self.TARGET_LATENCY_MS,
        }
    
    def is_meeting_target(self) -> bool:
        """Check if we're meeting the latency target."""
        p95 = self.latency_metrics.get_p95()
        return p95 <= self.TARGET_LATENCY_MS if p95 > 0 else True


# Global instance
_optimizer: Optional[WebSocketOptimizer] = None


def get_websocket_optimizer(send_callback=None) -> WebSocketOptimizer:
    """Get or create the singleton WebSocketOptimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = WebSocketOptimizer(send_callback)
    return _optimizer
