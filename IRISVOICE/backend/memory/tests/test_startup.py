"""
Startup Time Tests for IRIS Memory Foundation

_Requirements: 11.2, 11.6_
"""

import pytest
import time
import tempfile
from unittest.mock import Mock, patch, AsyncMock

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory import initialise_memory


class TestStartupTime:
    """Test startup time impact of memory initialization."""
    
    @pytest.mark.asyncio
    async def test_initialise_memory_startup_time(self):
        """
        Verify initialise_memory adds < 3 seconds to app startup.
        
        _Requirement: 11.2 - App startup time increases by no more than 3 seconds
        """
        mock_adapter = Mock()
        mock_adapter.get_context_size.return_value = 8192
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            
            with patch('backend.memory.load_config') as mock_load:
                mock_load.return_value = Mock()
                mock_load.return_value.db_path = db_path
                
                with patch('backend.core.biometric.initialize_memory_encryption') as mock_key:
                    mock_key.return_value = b"test_key_32_bytes_long_for_testing_"
                    
                    start = time.time()
                    
                    memory = await initialise_memory(
                        adapter=mock_adapter,
                        db_path=db_path
                    )
                    
                    elapsed = time.time() - start
                    
                    assert elapsed < 3.0, f"Memory init took {elapsed:.2f}s, exceeds 3s limit"


class TestLazyLoading:
    """Test that heavy components are lazily loaded."""
    
    def test_embedding_model_lazy_load(self):
        """Test that embedding model is not loaded on startup."""
        from backend.memory.embedding import EmbeddingService
        
        embed = EmbeddingService()
        
        # Model should not be loaded immediately
        assert embed._model is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
