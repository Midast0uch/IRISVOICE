"""
Tests for the vision security components.
"""
import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta

from .semantic_snapshot import SemanticSnapshot, ARIANode, ARIATreeSerializer
from .action_allowlist import ActionAllowlist, ActionType, UIAction, ActionRule
from .snapshot_cache import SnapshotCache

@pytest.fixture
def snapshot_manager():
    """Fixture for SemanticSnapshot."""
    return SemanticSnapshot()

@pytest.fixture
def allowlist_manager(tmp_path):
    """Fixture for ActionAllowlist."""
    config_path = tmp_path / "ui_actions.json"
    return ActionAllowlist(config_path=config_path)

@pytest.fixture
def cache_manager(tmp_path):
    """Fixture for SnapshotCache."""
    cache_dir = tmp_path / "snapshot_cache"
    return SnapshotCache(cache_dir=cache_dir, max_size_mb=1, max_entries=10)

class TestSemanticSnapshot:
    """Tests for SemanticSnapshot."""
    
    @pytest.mark.asyncio
    async def test_create_snapshot(self, snapshot_manager):
        """Test creating a semantic snapshot."""
        screenshot_data = b"fake_screenshot_data"
        root_node = await snapshot_manager.create_snapshot(screenshot_data)
        
        assert root_node.role == "application"
        assert root_node.name == "IRISVOICE Application"
        assert len(root_node.children) > 0
    
    @pytest.mark.asyncio
    async def test_snapshot_caching(self, snapshot_manager):
        """Test snapshot caching."""
        screenshot_data = b"fake_screenshot_data_cache"
        
        # First call should create and cache
        root_node1 = await snapshot_manager.create_snapshot(screenshot_data)
        assert snapshot_manager.get_cache_stats()["cache_size"] == 1
        
        # Second call should hit the cache
        root_node2 = await snapshot_manager.create_snapshot(screenshot_data)
        assert snapshot_manager.get_cache_stats()["cache_size"] == 1
        assert root_node1 is root_node2
    
    @pytest.mark.asyncio
    async def test_cache_eviction(self, snapshot_manager):
        """Test cache eviction."""
        snapshot_manager.max_cache_size = 2
        
        # Fill the cache
        await snapshot_manager.create_snapshot(b"data1")
        await snapshot_manager.create_snapshot(b"data2")
        assert snapshot_manager.get_cache_stats()["cache_size"] == 2
        
        # This should evict the first entry
        await snapshot_manager.create_snapshot(b"data3")
        assert snapshot_manager.get_cache_stats()["cache_size"] == 2
        
        # Verify that the first entry is gone
        cache_key1 = snapshot_manager._generate_cache_key(b"data1")
        assert snapshot_manager.get_cached_snapshot(cache_key1) is None

class TestActionAllowlist:
    """Tests for ActionAllowlist."""
    
    def test_default_rules(self, allowlist_manager):
        """Test loading of default rules."""
        assert len(allowlist_manager.rules) > 0
        assert any(rule.name == "safe_interactions" for rule in allowlist_manager.rules)
    
    def test_safe_action_allowed(self, allowlist_manager):
        """Test that a safe action is allowed."""
        action = UIAction(action_type=ActionType.CLICK, target_role="button")
        result = allowlist_manager.validate_action(action)
        assert result["allowed"] is True
        assert result["rule_matched"] == "safe_interactions"
    
    def test_dangerous_action_denied(self, allowlist_manager):
        """Test that a dangerous action is denied."""
        action = UIAction(action_type=ActionType.RIGHT_CLICK, target_role="button")
        result = allowlist_manager.validate_action(action)
        assert result["allowed"] is False
        assert result["rule_matched"] == "dangerous_actions"
    
    def test_system_ui_denied(self, allowlist_manager):
        """Test that interacting with system UI is denied."""
        action = UIAction(action_type=ActionType.CLICK, target_role="dialog")
        result = allowlist_manager.validate_action(action)
        assert result["allowed"] is False
        assert result["rule_matched"] == "system_ui_protection"
    
    def test_custom_rule_loading(self, allowlist_manager, tmp_path):
        """Test loading custom rules from config."""
        custom_rules = {
            "rules": [
                {
                    "name": "allow_drag_on_canvas",
                    "description": "Allow drag on canvas elements",
                    "action_types": ["drag"],
                    "allowed_roles": ["canvas"],
                    "priority": 500
                }
            ]
        }
        
        config_path = tmp_path / "ui_actions.json"
        with open(config_path, 'w') as f:
            json.dump(custom_rules, f)
        
        # Create new allowlist manager to load the config
        new_allowlist = ActionAllowlist(config_path=config_path)
        
        action = UIAction(action_type=ActionType.DRAG, target_role="canvas")
        result = new_allowlist.validate_action(action)
        
        assert result["allowed"] is True
        assert result["rule_matched"] == "allow_drag_on_canvas"

class TestSnapshotCache:
    """Tests for SnapshotCache."""
    
    @pytest.mark.asyncio
    async def test_cache_set_and_get(self, cache_manager):
        """Test setting and getting from cache."""
        screenshot_data = b"test_data"
        cache_key = cache_manager.get_cache_key(screenshot_data)
        snapshot_data = {"role": "application", "name": "Test App"}
        
        await cache_manager.set(cache_key, snapshot_data)
        retrieved = await cache_manager.get(cache_key)
        
        assert retrieved is not None
        assert retrieved["name"] == "Test App"
    
    @pytest.mark.asyncio
    async def test_disk_persistence(self, cache_manager, tmp_path):
        """Test that cache is persisted to disk."""
        screenshot_data = b"persistent_data"
        cache_key = cache_manager.get_cache_key(screenshot_data)
        snapshot_data = {"role": "button", "name": "Save"}
        
        await cache_manager.set(cache_key, snapshot_data)
        
        # Create a new cache manager to simulate restart
        new_cache_manager = SnapshotCache(cache_dir=tmp_path / "snapshot_cache")
        retrieved = await new_cache_manager.get(cache_key)
        
        assert retrieved is not None
        assert retrieved["name"] == "Save"
    
    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache_manager):
        """Test LRU eviction."""
        cache_manager.max_entries = 2
        
        await cache_manager.set("key1", {"data": 1})
        await cache_manager.set("key2", {"data": 2})
        
        # Access key1 to make it most recently used
        await cache_manager.get("key1")
        
        # This should evict key2
        await cache_manager.set("key3", {"data": 3})
        
        assert await cache_manager.get("key1") is not None
        assert await cache_manager.get("key2") is None
        assert await cache_manager.get("key3") is not None

class TestARIATreeSerializer:
    """Tests for ARIATreeSerializer."""
    
    @pytest.fixture
    def sample_aria_tree(self):
        """Fixture for a sample ARIA tree."""
        return ARIANode(
            role="application",
            name="Test App",
            children=[
                ARIANode(role="button", name="OK"),
                ARIANode(role="textbox", name="Username", properties={"readonly": False})
            ]
        )
    
    def test_to_dict(self, sample_aria_tree):
        """Test converting ARIA tree to dict."""
        tree_dict = ARIATreeSerializer.to_dict(sample_aria_tree)
        assert tree_dict["role"] == "application"
        assert len(tree_dict["children"]) == 2
    
    def test_to_json(self, sample_aria_tree):
        """Test converting ARIA tree to JSON."""
        tree_json = ARIATreeSerializer.to_json(sample_aria_tree)
        data = json.loads(tree_json)
        assert data["name"] == "Test App"
    
    def test_find_interactive_elements(self, sample_aria_tree):
        """Test finding interactive elements."""
        interactive = ARIATreeSerializer.find_interactive_elements(sample_aria_tree)
        assert len(interactive) == 2
        assert interactive[0].role == "button"
        assert interactive[1].role == "textbox"