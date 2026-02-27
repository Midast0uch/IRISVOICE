"""
Performance test for agent response time.
Validates that p95 response time is below 5 seconds for simple queries.
"""
import pytest
import asyncio
import time
from typing import List

# Add parent directory to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.performance.agent_optimizer import AgentOptimizer, ResponseMetrics


class TestAgentResponseTime:
    """Test agent response time optimization."""
    
    @pytest.mark.asyncio
    async def test_response_metrics_p95(self):
        """Test that response metrics correctly calculate p95."""
        metrics = ResponseMetrics()
        
        # Add 100 samples from 0.1s to 10s
        for i in range(1, 101):
            metrics.record(i * 0.1)
        
        p95 = metrics.get_p95()
        # P95 of 0.1-10s should be around 9.5s (allow for floating point precision)
        assert 9.4 <= p95 <= 9.7, f"P95 should be ~9.5s, got {p95}s"
    
    @pytest.mark.asyncio
    async def test_simple_query_detection(self):
        """Test that simple queries are correctly identified."""
        optimizer = AgentOptimizer()
        
        # Simple queries
        assert optimizer._is_simple_query("what is Python?")
        assert optimizer._is_simple_query("who is the president?")
        assert optimizer._is_simple_query("when is Christmas?")
        assert optimizer._is_simple_query("where is Paris?")
        assert optimizer._is_simple_query("how do I install Python?")
        
        # Complex queries (not simple)
        assert not optimizer._is_simple_query("Explain the theory of relativity in detail with examples")
        assert not optimizer._is_simple_query("Write a Python script that processes CSV files")
    
    @pytest.mark.asyncio
    async def test_response_caching(self):
        """Test that simple queries are cached."""
        optimizer = AgentOptimizer()
        
        query = "what is Python?"
        response = "Python is a programming language."
        
        # First request - cache miss
        cached = optimizer.get_cached_response(query)
        assert cached is None, "Should be cache miss on first request"
        
        # Cache the response
        optimizer.cache_response(query, response)
        
        # Second request - cache hit
        cached = optimizer.get_cached_response(query)
        assert cached == response, "Should be cache hit on second request"
        
        # Check metrics
        metrics = optimizer.get_metrics()
        assert metrics["cache_hits"] == 1
        assert metrics["cache_misses"] == 1
        assert metrics["cache_hit_rate"] == 0.5
    
    @pytest.mark.asyncio
    async def test_cache_normalization(self):
        """Test that queries are normalized for caching."""
        optimizer = AgentOptimizer()
        
        response = "Python is a programming language."
        
        # Cache with one format
        optimizer.cache_response("what is Python?", response)
        
        # Should hit cache with different formatting
        assert optimizer.get_cached_response("What is Python?") == response
        assert optimizer.get_cached_response("WHAT IS PYTHON?") == response
        assert optimizer.get_cached_response("  what is python?  ") == response
    
    @pytest.mark.asyncio
    async def test_cache_expiration(self):
        """Test that cache entries expire after TTL."""
        optimizer = AgentOptimizer()
        optimizer.CACHE_TTL_SECONDS = 1  # 1 second TTL for testing
        
        query = "what is Python?"
        response = "Python is a programming language."
        
        # Cache the response
        optimizer.cache_response(query, response)
        
        # Should hit cache immediately
        assert optimizer.get_cached_response(query) == response
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Should be cache miss after expiration
        assert optimizer.get_cached_response(query) is None
    
    @pytest.mark.asyncio
    async def test_cache_eviction_on_full(self):
        """Test that oldest entries are evicted when cache is full."""
        optimizer = AgentOptimizer()
        optimizer.MAX_CACHE_SIZE = 3  # Small cache for testing
        
        # Fill cache
        for i in range(3):
            optimizer.cache_response(f"what is query {i}?", f"Response {i}")
            await asyncio.sleep(0.01)  # Small delay to ensure different timestamps
        
        # Cache should be full
        assert len(optimizer.response_cache) == 3
        
        # Add one more - should evict oldest
        optimizer.cache_response("what is query 3?", "Response 3")
        
        # Cache should still be at max size
        assert len(optimizer.response_cache) == 3
        
        # Oldest entry should be evicted
        assert optimizer.get_cached_response("what is query 0?") is None
        assert optimizer.get_cached_response("what is query 3?") is not None
    
    @pytest.mark.asyncio
    async def test_response_streaming(self):
        """Test that long responses are streamed in chunks."""
        optimizer = AgentOptimizer()
        optimizer.STREAM_CHUNK_SIZE = 10  # Small chunks for testing
        optimizer.STREAM_DELAY_MS = 5  # Fast streaming for testing
        
        response = "This is a long response that should be streamed in chunks."
        
        chunks = []
        async def stream_callback(chunk: str):
            chunks.append(chunk)
        
        # Stream the response
        await optimizer.stream_response(response, stream_callback)
        
        # Should have multiple chunks
        assert len(chunks) > 1, "Response should be split into chunks"
        
        # Chunks should reconstruct original response
        reconstructed = "".join(chunks)
        assert reconstructed == response
    
    @pytest.mark.asyncio
    async def test_process_query_with_caching(self):
        """Test query processing with caching."""
        optimizer = AgentOptimizer()
        
        call_count = 0
        async def mock_agent(query: str) -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate processing time
            return f"Response to: {query}"
        
        query = "what is Python?"
        
        # First call - should call agent
        response1 = await optimizer.process_query(query, mock_agent)
        assert call_count == 1
        assert "Response to:" in response1
        
        # Second call - should use cache
        response2 = await optimizer.process_query(query, mock_agent)
        assert call_count == 1, "Should not call agent again (cache hit)"
        assert response1 == response2
    
    @pytest.mark.asyncio
    async def test_process_query_with_streaming(self):
        """Test query processing with streaming."""
        optimizer = AgentOptimizer()
        optimizer.STREAM_CHUNK_SIZE = 10
        
        async def mock_agent(query: str) -> str:
            await asyncio.sleep(0.05)
            return "This is a long response that should be streamed."
        
        chunks = []
        async def stream_callback(chunk: str):
            chunks.append(chunk)
        
        # Process with streaming
        response = await optimizer.process_query(
            "Tell me about Python",
            mock_agent,
            stream_callback
        )
        
        # Should have received chunks
        assert len(chunks) > 1, "Should have streamed chunks"
        assert "".join(chunks) == response
    
    @pytest.mark.asyncio
    async def test_p95_response_time_under_5s(self):
        """Test that p95 response time is under 5s target."""
        optimizer = AgentOptimizer()
        
        async def mock_agent(query: str) -> str:
            # Simulate varying response times (0.1s to 1s)
            delay = 0.1 + (hash(query) % 10) * 0.1
            await asyncio.sleep(delay)
            return f"Response to: {query}"
        
        # Process 100 queries
        for i in range(100):
            await optimizer.process_query(f"Query {i}", mock_agent)
        
        # Check metrics
        metrics = optimizer.get_metrics()
        p95_response_time = metrics["p95_response_time_s"]
        
        assert p95_response_time < 5.0, f"P95 response time {p95_response_time}s exceeds 5s target"
        assert optimizer.is_meeting_target(), "Should be meeting response time target"
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """Test that metrics are collected correctly."""
        optimizer = AgentOptimizer()
        
        async def mock_agent(query: str) -> str:
            await asyncio.sleep(0.05)
            return "Response"
        
        # Process some queries
        for i in range(10):
            await optimizer.process_query(f"Query {i}", mock_agent)
        
        # Get metrics
        metrics = optimizer.get_metrics()
        
        assert "p95_response_time_s" in metrics
        assert "mean_response_time_s" in metrics
        assert "max_response_time_s" in metrics
        assert "cache_size" in metrics
        assert "cache_hits" in metrics
        assert "cache_misses" in metrics
        assert "cache_hit_rate" in metrics
        assert metrics["total_samples"] == 10
    
    @pytest.mark.asyncio
    async def test_cache_improves_response_time(self):
        """Test that caching improves response time."""
        optimizer = AgentOptimizer()
        
        async def mock_agent(query: str) -> str:
            await asyncio.sleep(0.5)  # Slow agent
            return "Response"
        
        query = "what is Python?"
        
        # First call - slow
        start = time.time()
        await optimizer.process_query(query, mock_agent)
        first_time = time.time() - start
        
        # Second call - fast (cached)
        start = time.time()
        await optimizer.process_query(query, mock_agent)
        second_time = time.time() - start
        
        # Cached response should be much faster
        assert second_time < first_time * 0.1, "Cached response should be 10x faster"
    
    @pytest.mark.asyncio
    async def test_evict_expired_entries(self):
        """Test manual eviction of expired entries."""
        optimizer = AgentOptimizer()
        optimizer.CACHE_TTL_SECONDS = 1
        
        # Add some entries
        for i in range(5):
            optimizer.cache_response(f"what is query {i}?", f"Response {i}")
        
        assert len(optimizer.response_cache) == 5
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Evict expired
        optimizer.evict_expired()
        
        # All should be evicted
        assert len(optimizer.response_cache) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
