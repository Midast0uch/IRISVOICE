"""
Performance test for WebSocket message delivery latency.
Validates that p95 latency is below 50ms.
"""
import pytest
import asyncio
import time
from typing import List
from unittest.mock import AsyncMock, MagicMock

# Add parent directory to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.performance.websocket_optimizer import WebSocketOptimizer, LatencyMetrics


class TestWebSocketLatency:
    """Test WebSocket message delivery latency."""
    
    @pytest.mark.asyncio
    async def test_latency_metrics_p95(self):
        """Test that latency metrics correctly calculate p95."""
        metrics = LatencyMetrics()
        
        # Add 100 samples from 1ms to 100ms
        for i in range(1, 101):
            metrics.record(float(i))
        
        p95 = metrics.get_p95()
        # P95 of 1-100 should be around 95
        assert 94 <= p95 <= 96, f"P95 should be ~95ms, got {p95}ms"
    
    @pytest.mark.asyncio
    async def test_immediate_delivery_for_critical_messages(self):
        """Test that critical messages are delivered immediately without batching."""
        optimizer = WebSocketOptimizer()
        await optimizer.start()
        
        try:
            # Mock send callback
            send_times = []
            async def mock_send(client_id: str, message: dict):
                send_times.append(time.time())
                return True
            
            # Send critical messages
            critical_types = ["initial_state", "text_response", "voice_command_error", "validation_error"]
            
            start_time = time.time()
            for msg_type in critical_types:
                await optimizer.queue_message(
                    "client1",
                    {"type": msg_type, "payload": {}},
                    mock_send
                )
            
            # All messages should be sent immediately
            assert len(send_times) == 4, "All critical messages should be sent"
            
            # Check that all were sent within 10ms
            for send_time in send_times:
                latency_ms = (send_time - start_time) * 1000
                assert latency_ms < 10, f"Critical message took {latency_ms}ms, should be <10ms"
        
        finally:
            await optimizer.stop()
    
    @pytest.mark.asyncio
    async def test_batching_for_high_frequency_updates(self):
        """Test that high-frequency updates are batched."""
        optimizer = WebSocketOptimizer()
        await optimizer.start()
        
        try:
            send_count = 0
            async def mock_send(client_id: str, message: dict):
                nonlocal send_count
                send_count += 1
                return True
            
            # Send 5 audio_level updates rapidly
            for i in range(5):
                await optimizer.queue_message(
                    "client1",
                    {"type": "audio_level", "payload": {"level": i * 0.2}},
                    mock_send
                )
            
            # Should not have sent all messages yet (batching)
            # Note: Some might be sent if batch size is reached
            initial_send_count = send_count
            
            # Wait for batch to age and flush
            await asyncio.sleep(0.02)  # 20ms
            
            # Flush remaining
            await optimizer.flush_client("client1", mock_send)
            
            # All messages should eventually be sent
            assert send_count == 5, f"Expected 5 messages sent, got {send_count}"
        
        finally:
            await optimizer.stop()
    
    @pytest.mark.asyncio
    async def test_batch_flush_on_max_size(self):
        """Test that batches are flushed when max size is reached."""
        optimizer = WebSocketOptimizer()
        optimizer.MAX_BATCH_SIZE = 3  # Set small batch size for testing
        await optimizer.start()
        
        try:
            sent_messages = []
            async def mock_send(client_id: str, message: dict):
                sent_messages.append(message)
                return True
            
            # Send MAX_BATCH_SIZE messages
            for i in range(3):
                await optimizer.queue_message(
                    "client1",
                    {"type": "audio_level", "payload": {"level": i * 0.2}},
                    mock_send
                )
            
            # Should have flushed the batch
            assert len(sent_messages) == 3, "Batch should be flushed at max size"
        
        finally:
            await optimizer.stop()
    
    @pytest.mark.asyncio
    async def test_batch_flush_on_max_age(self):
        """Test that batches are flushed when max age is reached."""
        sent_messages = []
        async def mock_send(client_id: str, message: dict):
            sent_messages.append(message)
            return True
        
        optimizer = WebSocketOptimizer(send_callback=mock_send)
        optimizer.MAX_BATCH_AGE_MS = 10  # 10ms max age
        optimizer.FLUSH_INTERVAL_MS = 5  # Check every 5ms
        await optimizer.start()
        
        try:
            # Send 2 messages (below batch size)
            for i in range(2):
                await optimizer.queue_message(
                    "client1",
                    {"type": "audio_level", "payload": {"level": i * 0.2}},
                    mock_send
                )
            
            # Wait for batch to age and auto-flush
            await asyncio.sleep(0.02)  # 20ms
            
            # Messages should have been flushed due to age
            assert len(sent_messages) == 2, "Batch should be flushed after max age"
        
        finally:
            await optimizer.stop()
    
    @pytest.mark.asyncio
    async def test_p95_latency_under_50ms(self):
        """Test that p95 latency is under 50ms target."""
        optimizer = WebSocketOptimizer()
        await optimizer.start()
        
        try:
            async def mock_send(client_id: str, message: dict):
                # Simulate small network delay
                await asyncio.sleep(0.001)  # 1ms
                return True
            
            # Send 100 messages
            for i in range(100):
                await optimizer.queue_message(
                    "client1",
                    {"type": "text_response", "payload": {"text": f"Message {i}"}},
                    mock_send
                )
                # Small delay between messages
                await asyncio.sleep(0.001)
            
            # Flush any remaining batches
            await optimizer.flush_all(mock_send)
            
            # Check metrics
            metrics = optimizer.get_metrics()
            p95_latency = metrics["p95_latency_ms"]
            
            assert p95_latency < 50, f"P95 latency {p95_latency}ms exceeds 50ms target"
            assert optimizer.is_meeting_target(), "Should be meeting latency target"
        
        finally:
            await optimizer.stop()
    
    @pytest.mark.asyncio
    async def test_per_client_batching(self):
        """Test that batching is per-client to avoid head-of-line blocking."""
        optimizer = WebSocketOptimizer()
        await optimizer.start()
        
        try:
            client1_messages = []
            client2_messages = []
            
            async def mock_send(client_id: str, message: dict):
                if client_id == "client1":
                    client1_messages.append(message)
                else:
                    client2_messages.append(message)
                return True
            
            # Send messages to both clients
            for i in range(3):
                await optimizer.queue_message(
                    "client1",
                    {"type": "audio_level", "payload": {"level": i * 0.2}},
                    mock_send
                )
                await optimizer.queue_message(
                    "client2",
                    {"type": "audio_level", "payload": {"level": i * 0.3}},
                    mock_send
                )
            
            # Flush both clients
            await optimizer.flush_client("client1", mock_send)
            await optimizer.flush_client("client2", mock_send)
            
            # Both clients should have received their messages
            assert len(client1_messages) == 3, "Client 1 should receive all messages"
            assert len(client2_messages) == 3, "Client 2 should receive all messages"
        
        finally:
            await optimizer.stop()
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """Test that metrics are collected correctly."""
        optimizer = WebSocketOptimizer()
        await optimizer.start()
        
        try:
            async def mock_send(client_id: str, message: dict):
                await asyncio.sleep(0.001)  # 1ms delay
                return True
            
            # Send some messages
            for i in range(10):
                await optimizer.queue_message(
                    "client1",
                    {"type": "text_response", "payload": {"text": f"Message {i}"}},
                    mock_send
                )
            
            # Get metrics
            metrics = optimizer.get_metrics()
            
            assert "p95_latency_ms" in metrics
            assert "mean_latency_ms" in metrics
            assert "max_latency_ms" in metrics
            assert "pending_batches" in metrics
            assert "total_samples" in metrics
            assert metrics["total_samples"] > 0, "Should have collected samples"
        
        finally:
            await optimizer.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
