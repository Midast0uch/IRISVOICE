"""
Workspace Manager for IRISVOICE

Implements OpenClaw-style directory structure with session-specific workspaces,
configuration management, and workspace isolation.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, asdict
import aiofiles

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceConfig:
    """Configuration for a workspace."""
    name: str
    session_id: str
    user_id: str
    created_at: datetime
    last_modified: datetime
    workspace_type: str  # "main", "vision", "isolated"
    config_files: List[str]
    active: bool = True
    description: str = ""
    tags: Set[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = set()


@dataclass
class DirectoryStructure:
    """Defines the OpenClaw-style directory structure."""
    root: Path
    
    @property
    def config_dir(self) -> Path:
        """Configuration directory."""
        return self.root / "config"
    
    @property
    def sessions_dir(self) -> Path:
        """Sessions directory."""
        return self.root / "sessions"
    
    @property
    def logs_dir(self) -> Path:
        """Logs directory."""
        return self.root / "logs"
    
    @property
    def cache_dir(self) -> Path:
        """Cache directory."""
        return self.root / "cache"
    
    @property
    def data_dir(self) -> Path:
        """Data directory."""
        return self.root / "data"
    
    @property
    def backups_dir(self) -> Path:
        """Backups directory."""
        return self.root / "backups"
    
    @property
    def temp_dir(self) -> Path:
        """Temporary directory."""
        return self.root / "temp"
    
    @property
    def security_dir(self) -> Path:
        """Security directory."""
        return self.root / "security"
    
    @property
    def vision_dir(self) -> Path:
        """Vision directory."""
        return self.root / "vision"
    
    @property
    def tools_dir(self) -> Path:
        """Tools directory."""
        return self.root / "tools"
    
    @property
    def workspace_dir(self) -> Path:
        """Workspace directory."""
        return self.root / "workspace"
    
    @property
    def workspace_config_dir(self) -> Path:
        """Workspace configuration directory."""
        return self.workspace_dir / "config"
    
    @property
    def workspace_sessions_dir(self) -> Path:
        """Workspace sessions directory."""
        return self.workspace_dir / "sessions"
    
    @property
    def workspace_logs_dir(self) -> Path:
        """Workspace logs directory."""
        return self.workspace_dir / "logs"
    
    @property
    def workspace_cache_dir(self) -> Path:
        """Workspace cache directory."""
        return self.workspace_dir / "cache"
    
    @property
    def workspace_data_dir(self) -> Path:
        """Workspace data directory."""
        return self.workspace_dir / "data"
    
    @property
    def workspace_backups_dir(self) -> Path:
        """Workspace backups directory."""
        return self.workspace_dir / "backups"
    
    @property
    def workspace_temp_dir(self) -> Path:
        """Workspace temporary directory."""
        return self.workspace_dir / "temp"
    
    def create_all_directories(self):
        """Create all directory structure."""
        directories = [
            self.config_dir,
            self.sessions_dir,
            self.logs_dir,
            self.cache_dir,
            self.data_dir,
            self.backups_dir,
            self.temp_dir,
            self.security_dir,
            self.vision_dir,
            self.tools_dir,
            self.workspace_dir,
            self.workspace_config_dir,
            self.workspace_sessions_dir,
            self.workspace_logs_dir,
            self.workspace_cache_dir,
            self.workspace_data_dir,
            self.workspace_backups_dir,
            self.workspace_temp_dir,
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {directory}")


class WorkspaceManager:
    """Manages IRISVOICE workspaces with session isolation."""
    
    def __init__(self, base_path: Path):
        """Initialize workspace manager."""
        self.base_path = base_path
        self.workspaces_dir = base_path / "workspaces"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        
        self.workspaces: Dict[str, WorkspaceConfig] = {}
        self.active_workspaces: Dict[str, WorkspaceConfig] = {}
        
        logger.info(f"Workspace manager initialized at: {self.workspaces_dir}")
    
    async def create_workspace(self, name: str, session_id: str, user_id: str,
                             workspace_type: str = "main",
                             description: str = "",
                             tags: Optional[Set[str]] = None) -> WorkspaceConfig:
        """Create a new workspace."""
        if tags is None:
            tags = set()
        
        # Create workspace directory
        workspace_dir = self.workspaces_dir / session_id
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Create directory structure
        dir_structure = DirectoryStructure(workspace_dir)
        dir_structure.create_all_directories()
        
        # Create workspace configuration
        config = WorkspaceConfig(
            name=name,
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.now(),
            last_modified=datetime.now(),
            workspace_type=workspace_type,
            config_files=[],
            description=description,
            tags=tags
        )
        
        # Save workspace configuration
        await self._save_workspace_config(config)
        
        # Add to active workspaces
        self.workspaces[session_id] = config
        self.active_workspaces[session_id] = config
        
        logger.info(f"Created workspace: {name} for session {session_id}")
        return config
    
    async def get_workspace(self, session_id: str) -> Optional[WorkspaceConfig]:
        """Get workspace configuration by session ID."""
        if session_id in self.workspaces:
            return self.workspaces[session_id]
        
        # Try to load from disk
        config = await self._load_workspace_config(session_id)
        if config:
            self.workspaces[session_id] = config
            if config.active:
                self.active_workspaces[session_id] = config
        
        return config
    
    async def list_workspaces(self, user_id: Optional[str] = None,
                            workspace_type: Optional[str] = None,
                            active_only: bool = True) -> List[WorkspaceConfig]:
        """List workspaces with optional filtering."""
        workspaces = []
        
        # Load all workspaces from disk
        for workspace_dir in self.workspaces_dir.iterdir():
            if workspace_dir.is_dir():
                session_id = workspace_dir.name
                config = await self.get_workspace(session_id)
                if config:
                    workspaces.append(config)
        
        # Apply filters
        filtered_workspaces = []
        for config in workspaces:
            if user_id and config.user_id != user_id:
                continue
            if workspace_type and config.workspace_type != workspace_type:
                continue
            if active_only and not config.active:
                continue
            filtered_workspaces.append(config)
        
        return filtered_workspaces
    
    async def update_workspace(self, session_id: str, **kwargs) -> Optional[WorkspaceConfig]:
        """Update workspace configuration."""
        config = await self.get_workspace(session_id)
        if not config:
            return None
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        # Update timestamp
        config.last_modified = datetime.now()
        
        # Save updated configuration
        await self._save_workspace_config(config)
        
        logger.info(f"Updated workspace for session {session_id}")
        return config
    
    async def delete_workspace(self, session_id: str, force: bool = False) -> bool:
        """Delete a workspace."""
        config = await self.get_workspace(session_id)
        if not config:
            return False
        
        if not force and config.active:
            logger.warning(f"Cannot delete active workspace for session {session_id}")
            return False
        
        # Remove from memory
        if session_id in self.workspaces:
            del self.workspaces[session_id]
        if session_id in self.active_workspaces:
            del self.active_workspaces[session_id]
        
        # Remove from disk
        workspace_dir = self.workspaces_dir / session_id
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
            logger.info(f"Deleted workspace directory: {workspace_dir}")
        
        logger.info(f"Deleted workspace for session {session_id}")
        return True
    
    def get_workspace_directory(self, session_id: str) -> Optional[Path]:
        """Get workspace directory path."""
        workspace_dir = self.workspaces_dir / session_id
        if workspace_dir.exists():
            return workspace_dir
        return None
    
    def get_workspace_structure(self, session_id: str) -> Optional[DirectoryStructure]:
        """Get directory structure for a workspace."""
        workspace_dir = self.get_workspace_directory(session_id)
        if workspace_dir:
            return DirectoryStructure(workspace_dir)
        return None
    
    async def add_config_file(self, session_id: str, config_file: str) -> bool:
        """Add a configuration file to workspace."""
        config = await self.get_workspace(session_id)
        if not config:
            return False
        
        if config_file not in config.config_files:
            config.config_files.append(config_file)
            config.last_modified = datetime.now()
            await self._save_workspace_config(config)
            logger.info(f"Added config file {config_file} to workspace {session_id}")
        
        return True
    
    async def remove_config_file(self, session_id: str, config_file: str) -> bool:
        """Remove a configuration file from workspace."""
        config = await self.get_workspace(session_id)
        if not config:
            return False
        
        if config_file in config.config_files:
            config.config_files.remove(config_file)
            config.last_modified = datetime.now()
            await self._save_workspace_config(config)
            logger.info(f"Removed config file {config_file} from workspace {session_id}")
        
        return True
    
    async def _save_workspace_config(self, config: WorkspaceConfig):
        """Save workspace configuration to disk."""
        workspace_dir = self.workspaces_dir / config.session_id
        config_file = workspace_dir / "workspace_config.json"
        
        config_data = asdict(config)
        # Convert datetime objects to strings
        config_data["created_at"] = config.created_at.isoformat()
        config_data["last_modified"] = config.last_modified.isoformat()
        config_data["tags"] = list(config.tags)
        
        async with aiofiles.open(config_file, 'w') as f:
            await f.write(json.dumps(config_data, indent=2))
        
        logger.debug(f"Saved workspace config for session {config.session_id}")
    
    async def _load_workspace_config(self, session_id: str) -> Optional[WorkspaceConfig]:
        """Load workspace configuration from disk."""
        workspace_dir = self.workspaces_dir / session_id
        config_file = workspace_dir / "workspace_config.json"
        
        if not config_file.exists():
            return None
        
        try:
            async with aiofiles.open(config_file, 'r') as f:
                config_data = json.loads(await f.read())
            
            # Convert strings back to datetime objects
            config_data["created_at"] = datetime.fromisoformat(config_data["created_at"])
            config_data["last_modified"] = datetime.fromisoformat(config_data["last_modified"])
            config_data["tags"] = set(config_data.get("tags", []))
            
            return WorkspaceConfig(**config_data)
        except Exception as e:
            logger.error(f"Failed to load workspace config for session {session_id}: {e}")
            return None
    
    def get_workspace_info(self, session_id: str) -> Dict[str, Any]:
        """Get workspace information for monitoring."""
        config = self.workspaces.get(session_id)
        if not config:
            return {}
        
        workspace_dir = self.get_workspace_directory(session_id)
        if not workspace_dir:
            return {}
        
        # Calculate directory sizes
        total_size = 0
        file_count = 0
        for item in workspace_dir.rglob("*"):
            if item.is_file():
                total_size += item.stat().st_size
                file_count += 1
        
        return {
            "session_id": session_id,
            "name": config.name,
            "workspace_type": config.workspace_type,
            "user_id": config.user_id,
            "created_at": config.created_at.isoformat(),
            "last_modified": config.last_modified.isoformat(),
            "active": config.active,
            "directory_size": total_size,
            "file_count": file_count,
            "config_files": len(config.config_files),
            "tags": list(config.tags)
        }