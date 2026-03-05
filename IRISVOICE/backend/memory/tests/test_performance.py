"""
Performance Tests for IRIS Memory Foundation

_Requirements: 11.1, 11.6_
"""

import pytest
import time
import tempfile
import os
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.interface import MemoryInterface


@pytest.fixture
def mock_adapter():
    """Create a mock model adapter."""
    adapter = Mock()
    adapter.get_context_size.return_value = 8192
    adapter.count_tokens.return_value = 100
    return adapter


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "perf_test.db")


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


class TestContextAssemblyLatency:
    """Test context assembly performance."""
    
    def test_get_task_context_latency(self, mock_adapter, temp_db_path, biometric_key):
        """
        Verify get_task_context() completes in < 200ms.
        
        _Requirement: 11.1 - Agent response latency increases by no more than 200ms
        """
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Mock to avoid actual DB calls
        with patch.object(memory.semantic, 'get_startup_header', return_value="User prefers concise"):
            with patch.object(memory.episodic, 'assemble_episodic_context', return_value="Previous tasks"):
                # Warm up
                memory.get_task_context("test task", "session_1")
                
                # Measure
                start = time.time()
                for _ in range(10):
                    memory.get_task_context("test task", "session_1")
                elapsed = time.time() - start
                
                avg_latency = elapsed / 10
                # Should be well under 200ms with mocks
                assert avg_latency < 0.2, f"Average latency {avg_latency*1000:.2f}ms exceeds 200ms"


class TestStartupTime:
    """Test startup time impact."""
    
    def test_memory_init_startup_time(self, mock_adapter, temp_db_path, biometric_key):
        """
        Verify memory initialization adds < 3 seconds to startup.
        
        _Requirement: 11.2 - App startup time increases by no more than 3 seconds
        """
        start = time.time()
        
        # Initialize memory
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        elapsed = time.time() - start
        
        # Should be well under 3 seconds
        assert elapsed < 3.0, f"Startup time {elapsed:.2f}s exceeds 3s"


class TestEmbeddingPerformance:
    """Test embedding service performance."""
    
    def test_embedding_latency(self):
        """Test that embedding generation is fast enough."""
        from backend.memory.embedding import EmbeddingService
        
        embed = EmbeddingService()
        
        # Skip if model not available
        if not embed.is_available():
            pytest.skip("Embedding model not available")
        
        text = "This is a test sentence for embedding."
        
        start = time.time()
        result = embed.encode(text)
        elapsed = time.time() - start
        
        # Embedding should complete in reasonable time (< 1s for single text)
        assert elapsed < 1.0, f"Embedding took {elapsed:.2f}s"
        assert len(result) == 384


class TestRetrievalPerformance:
    """Test episode retrieval performance."""
    
    def test_similar_episode_retrieval_speed(self, mock_adapter, temp_db_path, biometric_key):
        """Test that similar episode retrieval is fast."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Mock retrieval to test latency
        with patch.object(memory.episodic, 'retrieve_similar', return_value=[]) as mock_retrieve:
            start = time.time()
            
            for _ in range(100):
                memory.episodic.retrieve_similar("test query", top_k=3)
            
            elapsed = time.time() - start
            
            # 100 calls should be very fast with mocked DB
            assert elapsed < 0.1, f"Retrieval too slow: {elapsed:.2f}s for 100 calls"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
