import os
import pickle
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

# Add backend to sys path so we can import it
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "IRISVOICE"))

from backend.agent.tts import TTSManager, get_tts_manager

@pytest.fixture
def clean_tts_manager():
    # Reset singleton
    TTSManager._instance = None
    TTSManager._initialized = False
    manager = get_tts_manager()
    manager._lux_encode_dict = None
    return manager

@pytest.fixture
def mock_lux():
    lux = MagicMock()
    lux.encode_prompt.return_value = {"mock_tensor": "mock_data"}
    return lux

def test_cache_loading_success(clean_tts_manager, mock_lux):
    """Test that valid cache is loaded successfully."""
    mock_encode_dict = {"cached_tensor": "cached_data"}
    
    with patch("backend.agent.tts._CACHE_FILE") as mock_cache_file:
        mock_cache_file.exists.return_value = True
        
        # Mock file reading and pickle.load
        with patch("builtins.open", mock_open(read_data=b"data")), \
             patch("pickle.load", return_value=mock_encode_dict):
             
            result = clean_tts_manager._get_encode_dict(mock_lux)
            
            assert result == mock_encode_dict
            assert clean_tts_manager._lux_encode_dict == mock_encode_dict
            # Ensure we didn't call encode_prompt
            mock_lux.encode_prompt.assert_not_called()

def test_cache_loading_corrupted(clean_tts_manager, mock_lux, caplog):
    """Test fallback when cache file is corrupted."""
    with patch("backend.agent.tts._CACHE_FILE") as mock_cache_file, \
         patch("backend.agent.tts._CLONE_REF") as mock_clone_ref, \
         patch("backend.agent.tts._CACHE_DIR") as mock_cache_dir:
         
        mock_cache_file.exists.return_value = True
        mock_clone_ref.exists.return_value = True
        
        # Simulate unpickle error
        with patch("builtins.open", mock_open()), \
             patch("pickle.load", side_effect=Exception("Corrupted pickle")), \
             patch("pickle.dump"):
             
            result = clean_tts_manager._get_encode_dict(mock_lux)
            
            # Should have fallen back to encoding
            assert result == {"mock_tensor": "mock_data"}
            mock_lux.encode_prompt.assert_called_once()
            assert "Cached encode_dict corrupted" in caplog.text

def test_cache_saving_success(clean_tts_manager, mock_lux):
    """Test saving to cache after successful encoding."""
    with patch("backend.agent.tts._CACHE_FILE") as mock_cache_file, \
         patch("backend.agent.tts._CLONE_REF") as mock_clone_ref, \
         patch("backend.agent.tts._CACHE_DIR") as mock_cache_dir:
         
        mock_cache_file.exists.return_value = False
        mock_clone_ref.exists.return_value = True
        
        with patch("builtins.open", mock_open()) as m_open, \
             patch("pickle.dump") as m_dump:
             
            result = clean_tts_manager._get_encode_dict(mock_lux)
            
            assert result == {"mock_tensor": "mock_data"}
            mock_lux.encode_prompt.assert_called_once()
            
            mock_cache_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
            m_open.assert_called_once_with(mock_cache_file, "wb")
            m_dump.assert_called_once_with({"mock_tensor": "mock_data"}, m_open())

def test_missing_clone_ref(clean_tts_manager, mock_lux):
    """Test when both cache and clone ref are missing."""
    with patch("backend.agent.tts._CACHE_FILE") as mock_cache_file, \
         patch("backend.agent.tts._CLONE_REF") as mock_clone_ref:
         
        mock_cache_file.exists.return_value = False
        mock_clone_ref.exists.return_value = False
        
        result = clean_tts_manager._get_encode_dict(mock_lux)
        
        assert result is None
        mock_lux.encode_prompt.assert_not_called()
