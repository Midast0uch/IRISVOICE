"""
Configuration Management Tests for IRIS Memory Foundation

_Requirements: 15.1, 15.2, 15.3, 15.4_
"""

import pytest
import tempfile
import json
import os

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.config import MemoryConfig, load_config


class TestMemoryConfig:
    """Test MemoryConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = MemoryConfig()
        
        assert config.db_path == "data/memory.db"
        assert config.compression_threshold == 0.8
        assert config.embedding_dim == 384
    
    def test_custom_values(self):
        """Test custom configuration values."""
        config = MemoryConfig(
            db_path="custom/path.db",
            compression_threshold=0.9
        )
        
        assert config.db_path == "custom/path.db"
        assert config.compression_threshold == 0.9
    
    def test_validation(self):
        """Test configuration validation."""
        config = MemoryConfig()
        
        # Should not raise
        config.validate()


class TestLoadConfig:
    """Test configuration loading."""
    
    def test_load_from_file(self):
        """Test loading config from JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = f"{tmpdir}/config.json"
            
            # Write test config
            with open(config_path, 'w') as f:
                json.dump({"db_path": "test.db", "compression_threshold": 0.7}, f)
            
            config = load_config(config_path)
            
            assert config.db_path == "test.db"
            assert config.compression_threshold == 0.7
    
    def test_load_missing_file_uses_defaults(self):
        """Test that missing config file uses defaults."""
        config = load_config("/nonexistent/path.json")
        
        assert config.db_path == "data/memory.db"  # Default


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
