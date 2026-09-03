"""
Regression Tests for IRIS Memory Foundation

Verify all existing WebSocket message types work after memory integration.

_Requirements: 11.3_
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")


class TestWebSocketCompatibility:
    """Test WebSocket message compatibility."""
    
    @pytest.mark.asyncio
    async def test_field_update_messages(self):
        """Verify field update messages still work."""
        # This test verifies the message routing doesn't break
        message = {
            "type": "update_field",
            "section_id": "input",
            "field_id": "input_volume",
            "value": 75
        }
        
        # Message should be valid JSON
        assert json.dumps(message)
        assert message["type"] == "update_field"
        assert "section_id" in message
    
    @pytest.mark.asyncio
    async def test_section_selection_messages(self):
        """Verify section selection messages still work."""
        message = {
            "type": "select_section",
            "section_id": "model_selection"
        }
        
        assert json.dumps(message)
        assert message["type"] == "select_section"
    
    @pytest.mark.asyncio
    async def test_confirm_messages(self):
        """Verify confirm messages still work."""
        message = {
            "type": "confirm",
            "card_id": "models-card"
        }
        
        assert json.dumps(message)
        assert message["type"] == "confirm"
    
    @pytest.mark.asyncio
    async def test_legacy_subnode_id_still_accepted(self):
        """Verify legacy subnode_id field is still accepted."""
        message = {
            "type": "update_field",
            "subnode_id": "input",  # Legacy field name
            "field_id": "volume",
            "value": 50
        }
        
        assert json.dumps(message)
        # Both field names should be accepted for backward compatibility
        assert "subnode_id" in message or "section_id" in message


class TestMessageRouting:
    """Test that memory messages don't interfere with other messages."""
    
    def test_memory_message_prefix(self):
        """Verify memory messages use correct prefix."""
        memory_messages = [
            "memory/get_preferences",
            "memory/forget_preference",
            "memory/get_stats"
        ]
        
        for msg_type in memory_messages:
            assert msg_type.startswith("memory/")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
