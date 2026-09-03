
"""
Configuration Version Control for IRISVOICE

Provides versioning, change tracking, and rollback capabilities
for workspace configurations.
"""

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import aiofiles

from backend.config.config_loader import ConfigurationLoader, WorkspaceConfiguration

logger = logging.getLogger(__name__)


@dataclass
class ConfigVersion:
    """Represents a version of a configuration."""
    version_id: str
    workspace_id: str
    timestamp: datetime
    author: str
    description: str
    changes: Dict[str, Any]
    configuration: Dict[str, Any]
    previous_version_id: Optional[str] = None


@dataclass
class ConfigChange:
    """Represents a change in configuration."""
    section: str
    setting: str
    old_value: Any
    new_value: Any
    change_type: str  # "added", "modified", "removed"


class ConfigurationVersionControl:
    """Manages configuration versioning and change tracking."""

    def __init__(self, config_loader: ConfigurationLoader, versions_dir: Optional[Path] = None):
        """Initialize configuration version control."""
        self.config_loader = config_loader
        self.versions_dir = versions_dir or config_loader.config_dir / "versions"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache of versions
        self.versions_cache: Dict[str, List[ConfigVersion]] = {}

        logger.info(f"Configuration version control initialized at: {self.versions_dir}")

    async def create_version(self, workspace_id: str, author: str, description: str) -> str:
        """Create a new version of the workspace configuration."""
        try:
            # Load current configuration
            current_config = await self.config_loader.load_configuration(workspace_id)
            if not current_config:
                raise ValueError(f"Configuration not found for workspace: {workspace_id}")

            # Generate version ID
            now = datetime.now()
            # Add microseconds and a random number to ensure uniqueness
            version_id = f"{workspace_id}_{now.strftime('%Y%m%d_%H%M%S_%f')}_{__import__('random').randint(1000, 9999)}"

            # Get previous version
            previous_versions = await self.get_workspace_versions(workspace_id)
            previous_version_id = previous_versions[-1].version_id if previous_versions else None

            # Calculate changes from previous version
            changes = await self._calculate_changes(workspace_id, current_config, previous_version_id)

            # Create version
            version = ConfigVersion(
                version_id=version_id,
                workspace_id=workspace_id,
                timestamp=datetime.now(),
                author=author,
                description=description,
                changes=changes,
                configuration=current_config.to_dict()
            )

            # Save version
            await self._save_version(version)

            # Update cache
            if workspace_id not in self.versions_cache:
                self.versions_cache[workspace_id] = []
            self.versions_cache[workspace_id].append(version)
            self.versions_cache[workspace_id].sort(key=lambda v: v.timestamp)

            logger.info(f"Created version {version_id} for workspace {workspace_id}")
            return version_id

        except Exception as e:
            logger.error(f"Failed to create version for workspace {workspace_id}: {e}")
            raise

    async def get_workspace_versions(self, workspace_id: str) -> List[ConfigVersion]:
        """Get all versions for a workspace."""
        if workspace_id in self.versions_cache:
            return self.versions_cache[workspace_id].copy()

        versions = []
        workspace_versions_dir = self.versions_dir / workspace_id
        if workspace_versions_dir.exists():
            for version_file in workspace_versions_dir.glob("*.json"):
                try:
                    async with aiofiles.open(version_file, 'r') as f:
                        data = json.loads(await f.read())
                    version = ConfigVersion(
                        version_id=data["version_id"],
                        workspace_id=data["workspace_id"],
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                        author=data["author"],
                        description=data["description"],
                        changes=data["changes"],
                        configuration=data["configuration"],
                        previous_version_id=data.get("previous_version_id")
                    )
                    versions.append(version)
                except Exception as e:
                    logger.error(f"Failed to load version {version_file}: {e}")

        # Sort by timestamp
        versions.sort(key=lambda v: v.timestamp)
        self.versions_cache[workspace_id] = versions
        return versions.copy()

    async def get_version(self, workspace_id: str, version_id: str) -> Optional[ConfigVersion]:
        """Get a specific version."""
        versions = await self.get_workspace_versions(workspace_id)
        for version in versions:
            if version.version_id == version_id:
                return version
        return None

    async def rollback_to_version(self, workspace_id: str, version_id: str) -> bool:
        """Rollback to a specific version."""
        try:
            version = await self.get_version(workspace_id, version_id)
            if not version:
                logger.error(f"Version {version_id} not found for workspace {workspace_id}")
                return False

            # Create configuration from version
            config = WorkspaceConfiguration.from_dict(version.configuration)
            config.workspace_id = workspace_id  # Ensure correct workspace ID
            config.last_modified = datetime.now()

            # Save as current configuration
            await self.config_loader.save_configuration(config)

            logger.info(f"Rolled back workspace {workspace_id} to version {version_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to rollback workspace {workspace_id} to version {version_id}: {e}")
            return False

    async def compare_versions(self, workspace_id: str, version_id1: str, version_id2: str) -> List[ConfigChange]:
        """Compare two versions and return the differences."""
        version1 = await self.get_version(workspace_id, version_id1)
        version2 = await self.get_version(workspace_id, version_id2)

        if not version1 or not version2:
            return []

        changes = await self._calculate_changes(workspace_id, WorkspaceConfiguration.from_dict(version2.configuration), version_id1)

        return changes

    async def _calculate_changes(self, workspace_id: str, current_config: WorkspaceConfiguration, previous_version_id: Optional[str]) -> Dict[str, Any]:
        """Calculate changes from previous version."""
        if not previous_version_id:
            return {"type": "initial", "sections_added": list(current_config.sections.keys())}

        previous_version = await self.get_version(workspace_id, previous_version_id)
        if not previous_version:
            return {"type": "unknown_previous", "sections_added": list(current_config.sections.keys())}

        # Compare configurations directly
        changes = []
        config1 = previous_version.configuration.get("sections", {})
        config2 = current_config.to_dict().get("sections", {})

        all_sections = set(config1.keys()) | set(config2.keys())

        for section in all_sections:
            settings1 = config1.get(section, {}).get("settings", {})
            settings2 = config2.get(section, {}).get("settings", {})

            all_settings = set(settings1.keys()) | set(settings2.keys())

            for setting in all_settings:
                value1 = settings1.get(setting)
                value2 = settings2.get(setting)

                if value1 != value2:
                    if value1 is None and value2 is not None:
                        change_type = "added"
                    elif value1 is not None and value2 is None:
                        change_type = "removed"
                    else:
                        change_type = "modified"

                    changes.append(ConfigChange(
                        section=section,
                        setting=setting,
                        old_value=value1,
                        new_value=value2,
                        change_type=change_type
                    ))

        return {
            "type": "update",
            "sections_modified": list(set(change.section for change in changes)),
            "settings_changed": len(changes),
            "change_details": [
                {
                    "section": change.section,
                    "setting": change.setting,
                    "old_value": change.old_value,
                    "new_value": change.new_value,
                    "change_type": change.change_type
                }
                for change in changes
            ]
        }

    async def _save_version(self, version: ConfigVersion):
        """Save a version to disk."""
        workspace_versions_dir = self.versions_dir / version.workspace_id
        workspace_versions_dir.mkdir(parents=True, exist_ok=True)

        version_file = workspace_versions_dir / f"{version.version_id}.json"
        version_data = asdict(version)
        version_data["timestamp"] = version.timestamp.isoformat()

        async with aiofiles.open(version_file, 'w') as f:
            await f.write(json.dumps(version_data, indent=2))

        logger.debug(f"Saved version {version.version_id} for workspace {version.workspace_id}")

    async def cleanup_old_versions(self, workspace_id: str, keep_count: int = 10) -> int:
        """Clean up old versions, keeping only the specified number."""
        try:
            versions = await self.get_workspace_versions(workspace_id)
            if len(versions) <= keep_count:
                return 0

            # Sort by timestamp (newest first)
            versions.sort(key=lambda v: v.timestamp, reverse=True)
            versions_to_remove = versions[keep_count:]

            removed_count = 0
            workspace_versions_dir = self.versions_dir / workspace_id

            for version in versions_to_remove:
                version_file = workspace_versions_dir / f"{version.version_id}.json"
                if version_file.exists():
                    version_file.unlink()
                    removed_count += 1

            # Update cache
            if workspace_id in self.versions_cache:
                self.versions_cache[workspace_id] = versions[:keep_count]

            logger.info(f"Cleaned up {removed_count} old versions for workspace {workspace_id}")
            return removed_count

        except Exception as e:
            logger.error(f"Failed to cleanup old versions for workspace {workspace_id}: {e}")
            return 0
