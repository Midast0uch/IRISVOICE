"""
Tests for Workspace Manager and Configuration Loader
"""

import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from .workspace_manager import WorkspaceManager, WorkspaceConfig, DirectoryStructure
from .config_loader import ConfigurationLoader, WorkspaceConfiguration, ConfigSection


@pytest.fixture
def workspace_manager(tmp_path):
    """Fixture for WorkspaceManager."""
    manager = WorkspaceManager(tmp_path)
    yield manager


@pytest.fixture
def config_loader(tmp_path):
    """Fixture for ConfigurationLoader."""
    config_dir = tmp_path / "configs"
    loader = ConfigurationLoader(config_dir)
    yield loader


class TestWorkspaceManager:
    """Test WorkspaceManager functionality."""
    
    @pytest.mark.asyncio
    async def test_create_workspace(self, workspace_manager):
        """Test workspace creation."""
        config = await workspace_manager.create_workspace(
            name="Test Workspace",
            session_id="test_session_123",
            user_id="test_user",
            workspace_type="main",
            description="Test workspace for unit tests",
            tags={"test", "unit"}
        )
        
        assert config is not None
        assert config.name == "Test Workspace"
        assert config.session_id == "test_session_123"
        assert config.user_id == "test_user"
        assert config.workspace_type == "main"
        assert config.description == "Test workspace for unit tests"
        assert "test" in config.tags
        assert "unit" in config.tags
        assert config.active is True
        assert isinstance(config.created_at, datetime)
        assert isinstance(config.last_modified, datetime)
    
    @pytest.mark.asyncio
    async def test_workspace_directory_structure(self, workspace_manager):
        """Test that workspace directory structure is created."""
        config = await workspace_manager.create_workspace(
            name="Structure Test",
            session_id="structure_test",
            user_id="test_user"
        )
        
        workspace_dir = workspace_manager.get_workspace_directory("structure_test")
        assert workspace_dir is not None
        assert workspace_dir.exists()
        
        # Check that all required directories exist
        structure = workspace_manager.get_workspace_structure("structure_test")
        assert structure is not None
        
        required_dirs = [
            structure.config_dir,
            structure.sessions_dir,
            structure.logs_dir,
            structure.cache_dir,
            structure.data_dir,
            structure.backups_dir,
            structure.temp_dir,
            structure.security_dir,
            structure.vision_dir,
            structure.tools_dir,
            structure.workspace_dir,
            structure.workspace_config_dir,
            structure.workspace_sessions_dir,
            structure.workspace_logs_dir,
            structure.workspace_cache_dir,
            structure.workspace_data_dir,
            structure.workspace_backups_dir,
            structure.workspace_temp_dir,
        ]
        
        for directory in required_dirs:
            assert directory.exists(), f"Directory {directory} should exist"
    
    @pytest.mark.asyncio
    async def test_get_workspace(self, workspace_manager):
        """Test getting workspace by session ID."""
        # Create workspace
        await workspace_manager.create_workspace(
            name="Get Test",
            session_id="get_test",
            user_id="test_user"
        )
        
        # Get workspace
        config = await workspace_manager.get_workspace("get_test")
        assert config is not None
        assert config.name == "Get Test"
        assert config.session_id == "get_test"
        
        # Test non-existent workspace
        non_existent = await workspace_manager.get_workspace("non_existent")
        assert non_existent is None
    
    @pytest.mark.asyncio
    async def test_list_workspaces(self, workspace_manager):
        """Test listing workspaces with filtering."""
        # Create multiple workspaces
        await workspace_manager.create_workspace(
            name="Main Workspace",
            session_id="main_1",
            user_id="user1",
            workspace_type="main"
        )
        
        await workspace_manager.create_workspace(
            name="Vision Workspace",
            session_id="vision_1",
            user_id="user1",
            workspace_type="vision"
        )
        
        await workspace_manager.create_workspace(
            name="Isolated Workspace",
            session_id="isolated_1",
            user_id="user2",
            workspace_type="isolated"
        )
        
        # List all workspaces
        all_workspaces = await workspace_manager.list_workspaces()
        assert len(all_workspaces) == 3
        
        # Filter by user
        user1_workspaces = await workspace_manager.list_workspaces(user_id="user1")
        assert len(user1_workspaces) == 2
        
        # Filter by workspace type
        main_workspaces = await workspace_manager.list_workspaces(workspace_type="main")
        assert len(main_workspaces) == 1
        assert main_workspaces[0].workspace_type == "main"
        
        # Filter by active only
        active_workspaces = await workspace_manager.list_workspaces(active_only=True)
        assert len(active_workspaces) == 3
    
    @pytest.mark.asyncio
    async def test_update_workspace(self, workspace_manager):
        """Test updating workspace configuration."""
        # Create workspace
        await workspace_manager.create_workspace(
            name="Update Test",
            session_id="update_test",
            user_id="test_user"
        )
        
        # Update workspace
        updated = await workspace_manager.update_workspace(
            session_id="update_test",
            description="Updated description",
            tags={"updated", "test"}
        )
        
        assert updated is not None
        assert updated.description == "Updated description"
        assert "updated" in updated.tags
        assert "test" in updated.tags
        
        # Verify changes persisted
        config = await workspace_manager.get_workspace("update_test")
        assert config.description == "Updated description"
        assert "updated" in config.tags
    
    @pytest.mark.asyncio
    async def test_delete_workspace(self, workspace_manager):
        """Test deleting workspace."""
        # Create workspace
        await workspace_manager.create_workspace(
            name="Delete Test",
            session_id="delete_test",
            user_id="test_user"
        )
        
        # Verify workspace exists
        config = await workspace_manager.get_workspace("delete_test")
        assert config is not None
        
        # Delete workspace (force since it's active)
        deleted = await workspace_manager.delete_workspace("delete_test", force=True)
        assert deleted is True
        
        # Verify workspace is gone
        config = await workspace_manager.get_workspace("delete_test")
        assert config is None
        
        # Verify directory is gone
        workspace_dir = workspace_manager.get_workspace_directory("delete_test")
        assert workspace_dir is None or not workspace_dir.exists()
    
    @pytest.mark.asyncio
    async def test_workspace_config_files(self, workspace_manager):
        """Test managing workspace configuration files."""
        # Create workspace
        await workspace_manager.create_workspace(
            name="Config Test",
            session_id="config_test",
            user_id="test_user"
        )
        
        # Add config files
        await workspace_manager.add_config_file("config_test", "settings.json")
        await workspace_manager.add_config_file("config_test", "rules.yaml")
        
        config = await workspace_manager.get_workspace("config_test")
        assert len(config.config_files) == 2
        assert "settings.json" in config.config_files
        assert "rules.yaml" in config.config_files
        
        # Remove config file
        await workspace_manager.remove_config_file("config_test", "settings.json")
        
        config = await workspace_manager.get_workspace("config_test")
        assert len(config.config_files) == 1
        assert "settings.json" not in config.config_files
        assert "rules.yaml" in config.config_files
    
    @pytest.mark.asyncio
    async def test_workspace_info(self, workspace_manager):
        """Test getting workspace information."""
        # Create workspace with some files
        await workspace_manager.create_workspace(
            name="Info Test",
            session_id="info_test",
            user_id="test_user"
        )
        
        # Create some test files
        workspace_dir = workspace_manager.get_workspace_directory("info_test")
        test_file = workspace_dir / "test.txt"
        test_file.write_text("Test content for workspace info")
        
        # Get workspace info
        info = workspace_manager.get_workspace_info("info_test")
        assert info is not None
        assert info["session_id"] == "info_test"
        assert info["name"] == "Info Test"
        assert info["user_id"] == "test_user"
        assert info["workspace_type"] == "main"
        assert info["active"] is True
        assert info["file_count"] >= 1
        assert info["directory_size"] > 0


class TestConfigurationLoader:
    """Test ConfigurationLoader functionality."""
    
    @pytest.mark.asyncio
    async def test_create_configuration(self, config_loader):
        """Test creating workspace configuration."""
        config = await config_loader.create_configuration(
            workspace_id="test_workspace_123",
            workspace_type="main"
        )
        
        assert config is not None
        assert config.workspace_id == "test_workspace_123"
        assert config.version == "1.0"
        assert len(config.sections) > 0
        assert "general" in config.sections
        assert "security" in config.sections
        assert "session" in config.sections
    
    @pytest.mark.asyncio
    async def test_default_configuration_sections(self, config_loader):
        """Test default configuration sections."""
        config = await config_loader.create_configuration("default_test", workspace_type="default")
        
        # Check general section
        general = config.get_section("general")
        assert general is not None
        assert general.settings["auto_save"] is True
        assert general.settings["auto_backup"] is True
        assert general.settings["backup_interval_minutes"] == 30
        
        # Check security section
        security = config.get_section("security")
        assert security is not None
        assert security.settings["enable_security_checks"] is True
        assert security.settings["max_file_size_mb"] == 100
        assert "txt" in security.settings["allowed_file_types"]
        
        # Check session section
        session = config.get_section("session")
        assert session is not None
        assert session.settings["session_timeout_minutes"] == 60
        assert session.settings["max_concurrent_sessions"] == 5
        assert session.settings["enable_session_isolation"] is True
    
    @pytest.mark.asyncio
    async def test_workspace_type_overrides(self, config_loader):
        """Test workspace type specific overrides."""
        # Test main workspace
        main_config = await config_loader.create_configuration(
            workspace_id="main_test",
            workspace_type="main"
        )
        assert main_config.get_setting("session", "session_timeout_minutes") == 120
        assert main_config.get_setting("session", "max_concurrent_sessions") == 10
        assert main_config.get_setting("vision", "enable_vision_system") is True
        
        # Test vision workspace
        vision_config = await config_loader.create_configuration(
            workspace_id="vision_test",
            workspace_type="vision"
        )
        assert vision_config.get_setting("session", "session_timeout_minutes") == 180
        assert vision_config.get_setting("session", "max_concurrent_sessions") == 3
        assert vision_config.get_setting("vision", "screenshot_quality") == 95
        
        # Test isolated workspace
        isolated_config = await config_loader.create_configuration(
            workspace_id="isolated_test",
            workspace_type="isolated"
        )
        assert isolated_config.get_setting("session", "session_timeout_minutes") == 30
        assert isolated_config.get_setting("session", "max_concurrent_sessions") == 1
        assert isolated_config.get_setting("vision", "enable_vision_system") is False
        assert isolated_config.get_setting("automation", "enable_automation") is False
    
    @pytest.mark.asyncio
    async def test_configuration_overrides(self, config_loader):
        """Test user configuration overrides."""
        overrides = {
            "general": {
                "auto_save": False,
                "backup_interval_minutes": 60
            },
            "security": {
                "max_file_size_mb": 200,
                "enable_audit_logging": False
            }
        }
        
        config = await config_loader.create_configuration(
            workspace_id="override_test",
            workspace_type="main",
            overrides=overrides
        )
        
        # Check overrides were applied
        assert config.get_setting("general", "auto_save") is False
        assert config.get_setting("general", "backup_interval_minutes") == 60
        assert config.get_setting("security", "max_file_size_mb") == 200
        assert config.get_setting("security", "enable_audit_logging") is False
        
        # Check non-overridden settings remain default
        assert config.get_setting("general", "auto_backup") is True
        assert config.get_setting("security", "enable_security_checks") is True
    
    @pytest.mark.asyncio
    async def test_save_and_load_configuration(self, config_loader):
        """Test saving and loading configuration."""
        # Create configuration
        original_config = await config_loader.create_configuration("save_load_test")
        
        # Save configuration
        await config_loader.save_configuration(original_config)
        
        # Load configuration
        loaded_config = await config_loader.load_configuration("save_load_test")
        
        assert loaded_config is not None
        assert loaded_config.workspace_id == original_config.workspace_id
        assert loaded_config.version == original_config.version
        assert len(loaded_config.sections) == len(original_config.sections)
        
        # Check that settings are preserved
        assert loaded_config.get_setting("general", "auto_save") == original_config.get_setting("general", "auto_save")
        assert loaded_config.get_setting("security", "max_file_size_mb") == original_config.get_setting("security", "max_file_size_mb")
    
    @pytest.mark.asyncio
    async def test_update_configuration(self, config_loader):
        """Test updating configuration."""
        # Create configuration
        await config_loader.create_configuration("update_test")
        
        # Update configuration
        updated = await config_loader.update_configuration(
            workspace_id="update_test",
            section_name="general",
            settings={
                "auto_save": False,
                "backup_interval_minutes": 45,
                "new_setting": "test_value"
            }
        )
        
        assert updated is True
        
        # Load and verify changes
        config = await config_loader.load_configuration("update_test")
        assert config.get_setting("general", "auto_save") is False
        assert config.get_setting("general", "backup_interval_minutes") == 45
        assert config.get_setting("general", "new_setting") == "test_value"
    
    @pytest.mark.asyncio
    async def test_validate_configuration(self, config_loader):
        """Test configuration validation."""
        # Create valid configuration
        config = await config_loader.create_configuration("validate_test")
        
        # Validate should pass
        errors = await config_loader.validate_configuration(config)
        assert len(errors) == 0
        
        # Create configuration with missing required sections
        invalid_config = WorkspaceConfiguration(
            workspace_id="invalid_test",
            version="1.0",
            sections={},  # Missing required sections
            metadata={},
            created_at=datetime.now(),
            last_modified=datetime.now()
        )
        
        errors = await config_loader.validate_configuration(invalid_config)
        assert len(errors) > 0
        assert any("Missing required section: general" in error for error in errors)
        assert any("Missing required section: security" in error for error in errors)
        assert any("Missing required section: session" in error for error in errors)
    
    @pytest.mark.asyncio
    async def test_export_import_configuration(self, config_loader, tmp_path):
        """Test exporting and importing configuration."""
        # Create configuration
        original_config = await config_loader.create_configuration("export_test")
        
        # Export configuration
        export_path = tmp_path / "exported_config.json"
        exported = await config_loader.export_configuration("export_test", export_path)
        assert exported is True
        assert export_path.exists()
        
        # Import configuration
        imported_config = await config_loader.import_configuration(export_path, "imported_test")
        assert imported_config is not None
        assert imported_config.workspace_id == "imported_test"
        
        # Verify settings are preserved
        assert imported_config.get_setting("general", "auto_save") == original_config.get_setting("general", "auto_save")
        assert imported_config.get_setting("security", "max_file_size_mb") == original_config.get_setting("security", "max_file_size_mb")


class TestIntegration:
    """Test integration between WorkspaceManager and ConfigurationLoader."""
    
    @pytest.mark.asyncio
    async def test_workspace_with_configuration(self, tmp_path):
        """Test workspace creation with configuration."""
        # Initialize managers
        workspace_manager = WorkspaceManager(tmp_path)
        config_loader = ConfigurationLoader(tmp_path / "configs")
        
        # Create workspace
        workspace_config = await workspace_manager.create_workspace(
            name="Integration Test",
            session_id="integration_test",
            user_id="test_user",
            workspace_type="main"
        )
        
        # Create configuration for workspace
        config = await config_loader.create_configuration(
            workspace_id="integration_test",
            workspace_type="main"
        )
        
        # Add configuration file to workspace
        await workspace_manager.add_config_file("integration_test", "main_config.json")
        
        # Verify integration
        workspace = await workspace_manager.get_workspace("integration_test")
        assert workspace is not None
        assert "main_config.json" in workspace.config_files
        
        loaded_config = await config_loader.load_configuration("integration_test")
        assert loaded_config is not None
        assert loaded_config.workspace_id == "integration_test"
    
    @pytest.mark.asyncio
    async def test_workspace_type_specific_configs(self, tmp_path):
        """Test different workspace types with appropriate configurations."""
        workspace_manager = WorkspaceManager(tmp_path)
        config_loader = ConfigurationLoader(tmp_path / "configs")
        
        # Test main workspace
        main_workspace = await workspace_manager.create_workspace(
            name="Main Workspace",
            session_id="main_workspace",
            user_id="user1",
            workspace_type="main"
        )
        
        main_config = await config_loader.create_configuration(
            workspace_id="main_workspace",
            workspace_type="main"
        )
        
        assert main_config.get_setting("vision", "enable_vision_system") is True
        assert main_config.get_setting("session", "session_timeout_minutes") == 120
        
        # Test vision workspace
        vision_workspace = await workspace_manager.create_workspace(
            name="Vision Workspace",
            session_id="vision_workspace",
            user_id="user2",
            workspace_type="vision"
        )
        
        vision_config = await config_loader.create_configuration(
            workspace_id="vision_workspace",
            workspace_type="vision"
        )
        
        assert vision_config.get_setting("vision", "screenshot_quality") == 95
        assert vision_config.get_setting("session", "session_timeout_minutes") == 180
        
        # Test isolated workspace
        isolated_workspace = await workspace_manager.create_workspace(
            name="Isolated Workspace",
            session_id="isolated_workspace",
            user_id="user3",
            workspace_type="isolated"
        )
        
        isolated_config = await config_loader.create_configuration(
            workspace_id="isolated_workspace",
            workspace_type="isolated"
        )
        
        assert isolated_config.get_setting("vision", "enable_vision_system") is False
        assert isolated_config.get_setting("automation", "enable_automation") is False
        assert isolated_config.get_setting("session", "session_timeout_minutes") == 30