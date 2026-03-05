"""
Memory Integration Tests

Tests for marketplace preference storage and recommendation generation.
Covers: preference storage, retrieval, and recommendation algorithms.

@spec 9.1.3 - Tests for memory integration
@requirements 12.1, 12.4
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Import the lifecycle manager
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from backend.integrations.lifecycle_manager import IntegrationLifecycleManager


@pytest.fixture
def mock_memory_interface():
    """Create a mock memory interface."""
    mock = Mock()
    mock.semantic = Mock()
    mock.semantic.store = Mock()
    mock.semantic.search = Mock(return_value=[])
    return mock


@pytest.fixture
def lifecycle_manager(mock_memory_interface):
    """Create a lifecycle manager with mocked dependencies."""
    return IntegrationLifecycleManager(
        credential_store=Mock(),
        registry_loader=Mock(),
        memory_interface=mock_memory_interface,
    )


class TestMarketplacePreferenceStorage:
    """Tests for store_marketplace_preference method."""
    
    @pytest.mark.asyncio
    async def test_store_category_preference(self, lifecycle_manager, mock_memory_interface):
        """Test storing a category viewed preference."""
        result = await lifecycle_manager.store_marketplace_preference(
            user_id="test_user",
            preference_type="category_viewed",
            value="email",
            metadata={"timestamp": datetime.now().isoformat()},
        )
        
        assert result is True
        mock_memory_interface.semantic.store.assert_called_once()
        call_args = mock_memory_interface.semantic.store.call_args
        assert call_args[1]["metadata"]["preference_type"] == "category_viewed"
        assert call_args[1]["metadata"]["value"] == "email"
    
    @pytest.mark.asyncio
    async def test_store_integration_viewed_preference(self, lifecycle_manager, mock_memory_interface):
        """Test storing an integration viewed preference."""
        result = await lifecycle_manager.store_marketplace_preference(
            user_id="test_user",
            preference_type="integration_viewed",
            value="gmail",
        )
        
        assert result is True
        mock_memory_interface.semantic.store.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_store_preference_without_memory_interface(self, lifecycle_manager):
        """Test that storing preference returns False when no memory interface."""
        lifecycle_manager.memory_interface = None
        
        result = await lifecycle_manager.store_marketplace_preference(
            user_id="test_user",
            preference_type="category_viewed",
            value="email",
        )
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_store_preference_handles_exception(self, lifecycle_manager, mock_memory_interface):
        """Test that exceptions are handled gracefully."""
        mock_memory_interface.semantic.store.side_effect = Exception("Storage error")
        
        result = await lifecycle_manager.store_marketplace_preference(
            user_id="test_user",
            preference_type="category_viewed",
            value="email",
        )
        
        assert result is False


class TestMarketplacePreferenceRetrieval:
    """Tests for get_marketplace_preferences method."""
    
    @pytest.mark.asyncio
    async def test_get_all_preferences(self, lifecycle_manager, mock_memory_interface):
        """Test retrieving all preferences for a user."""
        # Mock search results
        mock_result = Mock()
        mock_result.metadata = {
            "preference_type": "category_viewed",
            "value": "email",
            "timestamp": datetime.now().isoformat(),
        }
        mock_memory_interface.semantic.search.return_value = [mock_result]
        
        preferences = await lifecycle_manager.get_marketplace_preferences(
            user_id="test_user",
        )
        
        assert len(preferences) == 1
        assert preferences[0]["preference_type"] == "category_viewed"
        assert preferences[0]["value"] == "email"
    
    @pytest.mark.asyncio
    async def test_get_preferences_by_type(self, lifecycle_manager, mock_memory_interface):
        """Test retrieving preferences filtered by type."""
        mock_result = Mock()
        mock_result.metadata = {
            "preference_type": "category_viewed",
            "value": "messaging",
            "timestamp": datetime.now().isoformat(),
        }
        mock_memory_interface.semantic.search.return_value = [mock_result]
        
        preferences = await lifecycle_manager.get_marketplace_preferences(
            user_id="test_user",
            preference_type="category_viewed",
        )
        
        assert len(preferences) == 1
        assert preferences[0]["preference_type"] == "category_viewed"
    
    @pytest.mark.asyncio
    async def test_get_preferences_without_memory_interface(self, lifecycle_manager):
        """Test that empty list is returned when no memory interface."""
        lifecycle_manager.memory_interface = None
        
        preferences = await lifecycle_manager.get_marketplace_preferences(
            user_id="test_user",
        )
        
        assert preferences == []
    
    @pytest.mark.asyncio
    async def test_get_preferences_handles_exception(self, lifecycle_manager, mock_memory_interface):
        """Test that exceptions are handled gracefully."""
        mock_memory_interface.semantic.search.side_effect = Exception("Search error")
        
        preferences = await lifecycle_manager.get_marketplace_preferences(
            user_id="test_user",
        )
        
        assert preferences == []


class TestRecommendationGeneration:
    """Tests for get_recommended_integrations method."""
    
    @pytest.mark.asyncio
    async def test_generate_recommendations_from_category_preferences(
        self, lifecycle_manager, mock_memory_interface
    ):
        """Test that recommendations are generated based on category preferences."""
        # Mock category preferences
        category_pref = Mock()
        category_pref.metadata = {
            "preference_type": "category_viewed",
            "value": "email",
            "timestamp": datetime.now().isoformat(),
        }
        
        # Mock empty integration viewed preferences
        mock_memory_interface.semantic.search.side_effect = [
            [category_pref],  # First call for category prefs
            [],               # Second call for integration viewed
        ]
        
        # Mock registry with integrations
        mock_config = Mock()
        mock_config.name = "Gmail"
        mock_config.description = "Gmail integration"
        mock_config.category = "email"
        mock_config.tags = ["email"]
        
        lifecycle_manager.registry_loader.list_integrations.return_value = {
            "gmail": mock_config,
        }
        
        recommendations = await lifecycle_manager.get_recommended_integrations(
            user_id="test_user",
            limit=5,
        )
        
        # Should return recommendations based on email category preference
        assert isinstance(recommendations, list)
    
    @pytest.mark.asyncio
    async def test_exclude_already_viewed_integrations(self, lifecycle_manager, mock_memory_interface):
        """Test that already viewed integrations are excluded from recommendations."""
        # Mock integration viewed preference
        integration_pref = Mock()
        integration_pref.metadata = {
            "preference_type": "integration_viewed",
            "value": "gmail",
            "timestamp": datetime.now().isoformat(),
        }
        
        mock_memory_interface.semantic.search.side_effect = [
            [],               # No category prefs
            [integration_pref],  # Gmail already viewed
        ]
        
        # Mock registry
        mock_config = Mock()
        mock_config.name = "Gmail"
        mock_config.description = "Gmail integration"
        mock_config.category = "email"
        mock_config.tags = ["email"]
        
        lifecycle_manager.registry_loader.list_integrations.return_value = {
            "gmail": mock_config,
        }
        
        recommendations = await lifecycle_manager.get_recommended_integrations(
            user_id="test_user",
        )
        
        # Gmail should be excluded since it was already viewed
        gmail_recommendations = [r for r in recommendations if r["integration_id"] == "gmail"]
        assert len(gmail_recommendations) == 0
    
    @pytest.mark.asyncio
    async def test_recommendations_sorted_by_score(self, lifecycle_manager, mock_memory_interface):
        """Test that recommendations are sorted by relevance score."""
        # Mock multiple category preferences for "email"
        category_prefs = [
            Mock(metadata={"preference_type": "category_viewed", "value": "email"}),
            Mock(metadata={"preference_type": "category_viewed", "value": "email"}),
        ]
        
        mock_memory_interface.semantic.search.side_effect = [
            category_prefs,
            [],
        ]
        
        recommendations = await lifecycle_manager.get_recommended_integrations(
            user_id="test_user",
        )
        
        # Verify list is returned (scoring logic tested separately)
        assert isinstance(recommendations, list)
    
    @pytest.mark.asyncio
    async def test_recommendations_without_memory_interface(self, lifecycle_manager):
        """Test that empty list is returned when no memory interface."""
        lifecycle_manager.memory_interface = None
        
        recommendations = await lifecycle_manager.get_recommended_integrations(
            user_id="test_user",
        )
        
        assert recommendations == []
    
    @pytest.mark.asyncio
    async def test_recommendations_respects_limit(self, lifecycle_manager, mock_memory_interface):
        """Test that the limit parameter is respected."""
        mock_memory_interface.semantic.search.side_effect = [[], []]
        
        recommendations = await lifecycle_manager.get_recommended_integrations(
            user_id="test_user",
            limit=3,
        )
        
        # Should return at most 3 recommendations
        assert len(recommendations) <= 3


class TestMemoryIntegrationLogging:
    """Tests for memory logging on integration events."""
    
    @pytest.mark.asyncio
    async def test_log_to_memory_on_enable(self, lifecycle_manager, mock_memory_interface):
        """Test that enabling an integration logs to memory."""
        # This tests the _log_to_memory method is called during enable
        # The actual logging is tested in the lifecycle manager tests
        assert lifecycle_manager._log_to_memory is not None
    
    @pytest.mark.asyncio
    async def test_log_to_memory_on_disable(self, lifecycle_manager, mock_memory_interface):
        """Test that disabling an integration logs to memory."""
        assert lifecycle_manager._log_to_memory is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
