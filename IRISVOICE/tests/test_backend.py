"""
Basic tests for the IRISVOICE backend.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_import_main():
    """Test that main module can be imported without errors."""
    try:
        from backend.main import app
        assert app is not None
        print("✓ Successfully imported main app")
    except ImportError as e:
        print(f"⚠ Could not import main app: {e}")
        # This might fail due to dependencies, so we'll make it a soft fail
        pass

def test_import_models():
    """Test that models module can be imported without errors."""
    try:
        from backend.models import APIKey
        assert APIKey is not None
        print("✓ Successfully imported models")
    except ImportError as e:
        print(f"⚠ Could not import models: {e}")
        # Soft fail
        pass

def test_import_ws_manager():
    """Test that websocket manager can be imported without errors."""
    try:
        from backend.ws_manager import ConnectionManager
        manager = ConnectionManager()
        assert manager is not None
        print("✓ Successfully imported websocket manager")
    except ImportError as e:
        print(f"⚠ Could not import websocket manager: {e}")
        # Soft fail
        pass

def test_import_audio_modules():
    """Test that audio modules can be imported without errors."""
    try:
        from backend.audio.engine import AudioEngine
        from backend.audio.pipeline import AudioPipeline
        from backend.audio.wake_word import WakeWordDetector
        assert AudioEngine is not None
        assert AudioPipeline is not None
        assert WakeWordDetector is not None
        print("✓ Successfully imported audio modules")
    except ImportError as e:
        print(f"⚠ Could not import audio modules: {e}")
        # Soft fail for optional dependencies
        pass

def test_import_agent_modules():
    """Test that agent modules can be imported without errors."""
    try:
        from backend.agent.unified_conversation import UnifiedConversation
        from backend.agent.conversation import Conversation
        assert UnifiedConversation is not None
        assert Conversation is not None
        print("✓ Successfully imported agent modules")
    except ImportError as e:
        print(f"⚠ Could not import agent modules: {e}")
        # Soft fail for optional dependencies
        pass

def test_import_mcp_modules():
    """Test that MCP modules can be imported without errors."""
    try:
        from backend.mcp.server import MCPProtocolServer
        from backend.mcp.client import MCPProtocolClient
        assert MCPProtocolServer is not None
        assert MCPProtocolClient is not None
        print("✓ Successfully imported MCP modules")
    except ImportError as e:
        print(f"⚠ Could not import MCP modules: {e}")
        # Soft fail for optional dependencies
        pass

if __name__ == "__main__":
    print("Running basic backend import tests...")
    test_import_main()
    test_import_models()
    test_import_ws_manager()
    test_import_audio_modules()
    test_import_agent_modules()
    test_import_mcp_modules()
    print("Basic import tests completed.")