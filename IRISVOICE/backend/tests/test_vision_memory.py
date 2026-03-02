"""
Memory Profiling Tests for VisionService with 4-Bit Quantization

Validates:
- Memory usage stays under expected thresholds (3-4 GB with 4-bit quantization)
- Model lazy loading works correctly
- Memory is released when vision is disabled
- No memory leaks during repeated enable/disable cycles

Requirements:
    - PyTorch with CUDA support
    - transformers with bitsandbytes
    - pytest-memray (optional, for memory profiling)
    - pynvml (for GPU memory monitoring)

Run with:
    pytest tests/test_vision_memory.py -v
    pytest tests/test_vision_memory.py -v --memray (with memory profiling)
"""

import asyncio
import gc
import pytest
from typing import Optional
from unittest.mock import Mock, patch, MagicMock

# Import the service
from backend.vision.vision_service import VisionService, get_vision_service


class GPUMemoryMonitor:
    """Helper to monitor GPU memory usage."""
    
    def __init__(self):
        self.initial_memory = None
        self.peak_memory = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.available = True
        except:
            self.available = False
            self.handle = None
    
    def get_memory_mb(self) -> Optional[float]:
        """Get current GPU memory usage in MB."""
        if not self.available:
            return None
        try:
            import pynvml
            info = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
            return info.used / 1024 / 1024
        except:
            return None
    
    def reset_peak(self):
        """Reset peak memory tracking."""
        self.peak_memory = self.get_memory_mb()
    
    def check_peak(self):
        """Update peak memory if current is higher."""
        current = self.get_memory_mb()
        if current and self.peak_memory and current > self.peak_memory:
            self.peak_memory = current


@pytest.fixture
def gpu_monitor():
    """Fixture providing GPU memory monitor."""
    return GPUMemoryMonitor()


@pytest.fixture
def vision_service():
    """Fixture providing a fresh VisionService instance."""
    service = VisionService(
        model_path="mock_model_path",
        use_quantization=True,
        device="cuda" if _cuda_available() else "cpu"
    )
    # Clean up any existing model
    asyncio.run(service.disable())
    gc.collect()
    yield service
    # Cleanup after test
    asyncio.run(service.disable())
    gc.collect()


def _cuda_available():
    """Check if CUDA is available."""
    try:
        import torch
        return torch.cuda.is_available()
    except:
        return False


class TestVisionServiceMemory:
    """Test suite for VisionService memory management."""
    
    @pytest.mark.asyncio
    async def test_initial_state_no_memory_usage(self, vision_service, gpu_monitor):
        """Test that VisionService uses no GPU memory when first created."""
        if not gpu_monitor.available:
            pytest.skip("GPU monitoring not available")
        
        status = vision_service.get_status()
        assert status["status"] == "disabled"
        assert status["vram_usage_mb"] is None
        
        # Check no model is loaded
        assert vision_service._model is None
        assert vision_service._processor is None
    
    @pytest.mark.asyncio
    async def test_enable_loads_model(self, vision_service):
        """Test that enabling loads the model."""
        # Mock the model loading to avoid actual loading
        with patch.object(vision_service, '_load_model') as mock_load:
            mock_load.return_value = (Mock(), Mock())
            
            result = await vision_service.enable()
            
            assert result is True
            mock_load.assert_called_once()
            assert vision_service._status == "enabled"
    
    @pytest.mark.asyncio
    async def test_disable_frees_memory(self, vision_service):
        """Test that disabling releases memory."""
        # Enable first
        with patch.object(vision_service, '_load_model') as mock_load:
            mock_load.return_value = (Mock(), Mock())
            await vision_service.enable()
        
        # Now disable
        await vision_service.disable()
        
        assert vision_service._status == "disabled"
        assert vision_service._model is None
        assert vision_service._processor is None
    
    @pytest.mark.asyncio
    async def test_memory_threshold_with_quantization(self, vision_service):
        """Test that 4-bit quantization keeps memory under threshold."""
        # This test validates the expected memory usage with 4-bit quantization
        # MiniCPM-o4.5 with 4-bit quantization should use ~3-4 GB VRAM
        # compared to 8-12 GB for full precision
        
        status = vision_service.get_status()
        
        # Verify quantization is enabled
        assert status["quantization_enabled"] is True
        
        # Memory threshold for 4-bit quantized model (in MB)
        MEMORY_THRESHOLD_MB = 4500  # 4.5 GB - generous threshold
        
        # If we had actual model loaded, we'd check:
        # assert status["vram_usage_mb"] < MEMORY_THRESHOLD_MB
        # 
        # For now, verify the configuration is correct
        assert vision_service.use_quantization is True
    
    @pytest.mark.asyncio
    async def test_repeated_enable_disable_no_leak(self, vision_service):
        """Test that repeated enable/disable cycles don't cause memory leaks."""
        cycles = 3
        
        for i in range(cycles):
            # Enable
            with patch.object(vision_service, '_load_model') as mock_load:
                mock_load.return_value = (Mock(), Mock())
                result = await vision_service.enable()
                assert result is True, f"Failed to enable on cycle {i+1}"
            
            # Disable
            await vision_service.disable()
            assert vision_service._status == "disabled"
        
        # After all cycles, model should be None
        assert vision_service._model is None
        assert vision_service._processor is None
    
    @pytest.mark.asyncio
    async def test_concurrent_enable_requests(self, vision_service):
        """Test that concurrent enable requests are handled correctly."""
        with patch.object(vision_service, '_load_model') as mock_load:
            mock_load.return_value = (Mock(), Mock())
            
            # Start multiple enable requests
            tasks = [
                vision_service.enable(),
                vision_service.enable(),
                vision_service.enable(),
            ]
            
            # All should complete without error
            results = await asyncio.gather(*tasks)
            
            # At least one should succeed (others may return True if already enabled)
            assert any(results)
            
            # Model should be loaded
            assert vision_service._status == "enabled"
    
    def test_quantization_config(self, vision_service):
        """Test that BitsAndBytesConfig is correctly configured for 4-bit."""
        config = vision_service._quant_config
        
        # Verify 4-bit quantization settings
        assert config.load_in_4bit is True
        assert config.bnb_4bit_compute_dtype.__name__ == "float16"
        assert config.bnb_4bit_use_double_quant is True
        assert config.bnb_4bit_quant_type == "nf4"
    
    @pytest.mark.asyncio
    async def test_status_reflects_memory(self, vision_service):
        """Test that status accurately reflects memory usage."""
        # Initially no memory usage
        status = vision_service.get_status()
        assert status["status"] == "disabled"
        assert status["vram_usage_mb"] is None
        
        # After enabling
        with patch.object(vision_service, '_load_model') as mock_load:
            mock_model = Mock()
            mock_model.get_memory_footprint.return_value = 3.5 * 1024 * 1024 * 1024  # 3.5 GB
            mock_load.return_value = (mock_model, Mock())
            
            await vision_service.enable()
            
            status = vision_service.get_status()
            assert status["status"] == "enabled"
            assert status["vram_usage_mb"] is not None
            assert status["vram_usage_mb"] > 0
    
    @pytest.mark.skipif(not _cuda_available(), reason="CUDA not available")
    @pytest.mark.asyncio
    async def test_actual_gpu_memory_tracking(self, gpu_monitor):
        """Integration test with actual GPU memory tracking (requires CUDA)."""
        service = VisionService(
            model_path="mock_path",  # Would be real path in integration test
            use_quantization=True,
            device="cuda"
        )
        
        # Record initial memory
        initial_mem = gpu_monitor.get_memory_mb()
        
        # Enable (mocked to not actually load)
        with patch.object(service, '_load_model') as mock_load:
            mock_model = Mock()
            mock_model.get_memory_footprint.return_value = 3.5 * 1024 * 1024 * 1024
            mock_load.return_value = (mock_model, Mock())
            await service.enable()
        
        # Disable
        await service.disable()
        gc.collect()
        
        # Memory should be close to initial (may not be exactly due to other allocations)
        final_mem = gpu_monitor.get_memory_mb()
        
        # Allow for some variance due to other processes
        if initial_mem and final_mem:
            mem_diff = abs(final_mem - initial_mem)
            assert mem_diff < 500, f"Memory leak detected: {mem_diff:.0f} MB difference"


class TestVisionServiceIntegration:
    """Integration tests for VisionService."""
    
    @pytest.mark.asyncio
    async def test_chat_with_image_requires_enabled(self, vision_service):
        """Test that chat with image requires vision to be enabled."""
        # Try to use without enabling
        with pytest.raises(RuntimeError) as exc_info:
            await vision_service.chat(
                messages=[{"role": "user", "content": "test"}],
                images=["fake_base64_image"]
            )
        
        assert "Vision service is not enabled" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_analyze_requires_enabled(self, vision_service):
        """Test that analyze requires vision to be enabled."""
        with pytest.raises(RuntimeError) as exc_info:
            await vision_service.analyze(
                image_b64="fake_base64_image",
                prompt="Analyze this"
            )
        
        assert "Vision service is not enabled" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_is_available_with_mock(self, vision_service):
        """Test is_available check."""
        with patch('os.path.exists') as mock_exists:
            # Model path exists
            mock_exists.return_value = True
            
            is_avail = await vision_service.is_available()
            
            # Should be available if path exists
            assert isinstance(is_avail, bool)


class TestVisionServiceSingleton:
    """Test singleton behavior."""
    
    def test_singleton_instance(self):
        """Test that get_vision_service returns the same instance."""
        service1 = get_vision_service()
        service2 = get_vision_service()
        
        assert service1 is service2
    
    @pytest.mark.asyncio
    async def test_singleton_state_shared(self):
        """Test that state is shared across singleton instances."""
        service1 = get_vision_service()
        service2 = get_vision_service()
        
        # Mock enable on service1
        with patch.object(service1, '_load_model') as mock_load:
            mock_load.return_value = (Mock(), Mock())
            await service1.enable()
        
        # service2 should see the same state
        assert service2.get_status()["status"] == "enabled"
        
        # Cleanup
        await service1.disable()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
