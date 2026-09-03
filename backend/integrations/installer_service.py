"""
Installer Service

Handles installation, uninstallation, and updates of MCP servers from the marketplace.
Manages npm/pip installs and registry entry generation.

_Requirements: 8.7, 8.8, 8.9
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Callable

from .models import IntegrationConfig, MCPServerConfig, OAuthConfig
from .registry_loader import RegistryLoader, get_registry_loader
from .lifecycle_manager import IntegrationLifecycleManager
from .credential_store import CredentialStore

logger = logging.getLogger(__name__)

# Installation directories
INSTALL_BASE_DIR = Path.home() / ".iris" / "servers"


@dataclass
class InstallProgress:
    """Tracks installation progress."""
    stage: str = "downloading"  # downloading, installing, configuring, complete, error
    progress: float = 0.0  # 0-100
    message: str = ""
    error: Optional[str] = None


class InstallerService:
    """
    Service for installing and managing MCP servers.
    
    Handles:
    - Downloading and installing packages (npm, pip)
    - Creating registry entries
    - Post-install auth flow triggers
    - Update checking
    - Uninstallation
    """
    
    def __init__(
        self,
        registry_loader: Optional[RegistryLoader] = None,
        lifecycle_manager: Optional[IntegrationLifecycleManager] = None,
        credential_store: Optional[CredentialStore] = None,
    ):
        self.registry_loader = registry_loader or get_registry_loader()
        self.lifecycle_manager = lifecycle_manager
        self.credential_store = credential_store
        
        # Ensure install directory exists
        INSTALL_BASE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Progress callbacks
        self._progress_callbacks: Dict[str, List[Callable]] = {}
    
    def _notify_progress(self, install_id: str, progress: InstallProgress):
        """Notify progress listeners."""
        callbacks = self._progress_callbacks.get(install_id, [])
        for callback in callbacks:
            try:
                callback(progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    def register_progress_callback(self, install_id: str, callback: Callable):
        """Register a callback for installation progress updates."""
        if install_id not in self._progress_callbacks:
            self._progress_callbacks[install_id] = []
        self._progress_callbacks[install_id].append(callback)
    
    async def install(
        self,
        server_id: str,
        package_name: str,
        package_type: str,  # 'npm', 'pypi', 'docker'
        version: Optional[str] = None,
        install_id: Optional[str] = None,
    ) -> IntegrationConfig:
        """
        Install an MCP server from the marketplace.
        
        Args:
            server_id: Unique server identifier
            package_name: Package name (e.g., '@anthropic/mcp-server-filesystem')
            package_type: Package manager type ('npm', 'pypi', 'docker')
            version: Specific version to install (default: latest)
            install_id: Optional tracking ID for progress callbacks
            
        Returns:
            IntegrationConfig for the installed server
            
        Raises:
            InstallationError: If installation fails
        """
        install_dir = INSTALL_BASE_DIR / server_id
        
        try:
            # Stage 1: Download
            self._notify_progress(install_id or server_id, InstallProgress(
                stage="downloading",
                progress=10,
                message="Downloading package...",
            ))
            
            # Stage 2: Install
            self._notify_progress(install_id or server_id, InstallProgress(
                stage="installing",
                progress=30,
                message="Installing dependencies...",
            ))
            
            if package_type == "npm":
                await self._install_npm(package_name, install_dir, version)
            elif package_type == "pypi":
                await self._install_pip(package_name, install_dir, version)
            elif package_type == "docker":
                await self._install_docker(package_name, install_dir, version)
            else:
                raise InstallationError(f"Unsupported package type: {package_type}")
            
            # Stage 3: Configure
            self._notify_progress(install_id or server_id, InstallProgress(
                stage="configuring",
                progress=70,
                message="Configuring server...",
            ))
            
            # Generate registry entry
            config = await self._generate_registry_entry(
                server_id=server_id,
                package_name=package_name,
                package_type=package_type,
                install_dir=install_dir,
            )
            
            # Save to user registry
            self._save_to_user_registry(config)
            
            # Stage 4: Complete
            self._notify_progress(install_id or server_id, InstallProgress(
                stage="complete",
                progress=100,
                message="Installation complete",
            ))
            
            logger.info(f"Successfully installed {server_id}")
            return config
            
        except Exception as e:
            logger.error(f"Installation failed for {server_id}: {e}")
            self._notify_progress(install_id or server_id, InstallProgress(
                stage="error",
                progress=0,
                message="Installation failed",
                error=str(e),
            ))
            # Clean up on failure
            if install_dir.exists():
                shutil.rmtree(install_dir)
            raise InstallationError(f"Failed to install {server_id}: {e}") from e
    
    async def _install_npm(
        self,
        package_name: str,
        install_dir: Path,
        version: Optional[str] = None,
    ):
        """Install an npm package."""
        install_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize package.json
        package_json = {"name": f"iris-server-{install_dir.name}", "version": "1.0.0"}
        (install_dir / "package.json").write_text(json.dumps(package_json, indent=2))
        
        # Install package
        package_spec = f"{package_name}@{version}" if version else package_name
        
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", package_spec,
            cwd=install_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise InstallationError(f"npm install failed: {stderr.decode()}")
    
    async def _install_pip(
        self,
        package_name: str,
        install_dir: Path,
        version: Optional[str] = None,
    ):
        """Install a pip package."""
        install_dir.mkdir(parents=True, exist_ok=True)
        
        # Create virtual environment
        venv_dir = install_dir / ".venv"
        
        proc = await asyncio.create_subprocess_exec(
            "python", "-m", "venv", str(venv_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise InstallationError(f"venv creation failed: {stderr.decode()}")
        
        # Install package
        pip_path = venv_dir / "bin" / "pip"
        if not pip_path.exists():
            pip_path = venv_dir / "Scripts" / "pip.exe"  # Windows
        
        package_spec = f"{package_name}=={version}" if version else package_name
        
        proc = await asyncio.create_subprocess_exec(
            str(pip_path), "install", package_spec,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise InstallationError(f"pip install failed: {stderr.decode()}")
    
    async def _install_docker(
        self,
        image_name: str,
        install_dir: Path,
        version: Optional[str] = None,
    ):
        """Pull a Docker image."""
        image_spec = f"{image_name}:{version}" if version else image_name
        
        proc = await asyncio.create_subprocess_exec(
            "docker", "pull", image_spec,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise InstallationError(f"docker pull failed: {stderr.decode()}")
        
        # Save image reference
        (install_dir / "docker-image.txt").write_text(image_spec)
    
    async def _generate_registry_entry(
        self,
        server_id: str,
        package_name: str,
        package_type: str,
        install_dir: Path,
    ) -> IntegrationConfig:
        """Generate an IntegrationConfig from installed package."""
        # Try to load package metadata
        metadata = await self._load_package_metadata(install_dir, package_type)
        
        # Determine entry point
        binary = self._determine_binary(package_name, package_type, install_dir)
        
        # Default to credentials auth for marketplace servers
        auth_type = "credentials"
        
        config = IntegrationConfig(
            id=server_id,
            name=metadata.get("name", server_id),
            description=metadata.get("description", ""),
            category=metadata.get("category", "other"),
            icon=metadata.get("icon"),
            auth_type=auth_type,
            oauth=None,
            telegram=None,
            credentials={
                "fields": metadata.get("credential_fields", [
                    {"key": "api_key", "label": "API Key", "type": "password"},
                ]),
            },
            mcp_server=MCPServerConfig(
                module=str(install_dir / "index.js"),
                binary=binary,
                runtime="node" if package_type == "npm" else "python" if package_type == "pypi" else "docker",
                tools=metadata.get("tools", []),
            ),
            permissions_summary=metadata.get("description", ""),
            enabled_by_default=False,
        )
        
        return config
    
    async def _load_package_metadata(
        self,
        install_dir: Path,
        package_type: str,
    ) -> Dict:
        """Load metadata from installed package."""
        metadata = {}
        
        if package_type == "npm":
            # Try to read package.json
            package_json_path = install_dir / "node_modules" / "package.json"
            if package_json_path.exists():
                try:
                    with open(package_json_path) as f:
                        pkg = json.load(f)
                        metadata["name"] = pkg.get("name", "").split("/")[-1]
                        metadata["description"] = pkg.get("description", "")
                        # Look for MCP metadata
                        mcp_meta = pkg.get("mcp", {})
                        metadata["tools"] = mcp_meta.get("tools", [])
                        metadata["category"] = mcp_meta.get("category", "other")
                except Exception as e:
                    logger.warning(f"Failed to read package.json: {e}")
        
        elif package_type == "pypi":
            # Try to read package metadata
            # This is simplified; real implementation would parse dist-info
            pass
        
        return metadata
    
    def _determine_binary(
        self,
        package_name: str,
        package_type: str,
        install_dir: Path,
    ) -> str:
        """Determine the binary/command to run the server."""
        if package_type == "npm":
            # Look for bin in node_modules/.bin
            bin_dir = install_dir / "node_modules" / ".bin"
            package_base = package_name.split("/")[-1]
            
            # Common patterns
            candidates = [
                bin_dir / package_base,
                bin_dir / f"{package_base}-server",
                bin_dir / "mcp-server",
            ]
            
            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)
            
            # Default to npx
            return f"npx {package_name}"
        
        elif package_type == "pypi":
            venv_dir = install_dir / ".venv"
            python_path = venv_dir / "bin" / "python"
            if not python_path.exists():
                python_path = venv_dir / "Scripts" / "python.exe"
            
            package_base = package_name.replace("-", "_")
            return f"{python_path} -m {package_base}"
        
        elif package_type == "docker":
            image_spec = (install_dir / "docker-image.txt").read_text().strip()
            return f"docker run -i --rm {image_spec}"
        
        return package_name
    
    def _save_to_user_registry(self, config: IntegrationConfig):
        """Save the integration config to user registry."""
        user_registry_path = Path.home() / ".iris" / "user-registry.json"
        
        registry = {}
        if user_registry_path.exists():
            with open(user_registry_path) as f:
                registry = json.load(f)
        
        if "integrations" not in registry:
            registry["integrations"] = []
        
        # Check if already exists
        existing_idx = None
        for idx, integration in enumerate(registry["integrations"]):
            if integration["id"] == config.id:
                existing_idx = idx
                break
        
        # Convert config to dict
        config_dict = {
            "id": config.id,
            "name": config.name,
            "category": config.category,
            "icon": config.icon,
            "auth_type": config.auth_type,
            "credentials": config.credentials,
            "mcp_server": {
                "module": config.mcp_server.module,
                "binary": config.mcp_server.binary,
                "runtime": config.mcp_server.runtime,
                "tools": config.mcp_server.tools,
            },
            "permissions_summary": config.permissions_summary,
            "enabled_by_default": config.enabled_by_default,
        }
        
        if existing_idx is not None:
            registry["integrations"][existing_idx] = config_dict
        else:
            registry["integrations"].append(config_dict)
        
        with open(user_registry_path, "w") as f:
            json.dump(registry, f, indent=2)
    
    async def uninstall(self, server_id: str) -> bool:
        """
        Uninstall an MCP server.
        
        Args:
            server_id: The server to uninstall
            
        Returns:
            True if successful
        """
        try:
            # Stop if running
            if self.lifecycle_manager:
                try:
                    await self.lifecycle_manager.disable(server_id, forget_credentials=True)
                except Exception as e:
                    logger.warning(f"Failed to stop server during uninstall: {e}")
            
            # Remove install directory
            install_dir = INSTALL_BASE_DIR / server_id
            if install_dir.exists():
                shutil.rmtree(install_dir)
            
            # Remove from registry
            self._remove_from_user_registry(server_id)
            
            logger.info(f"Successfully uninstalled {server_id}")
            return True
            
        except Exception as e:
            logger.error(f"Uninstall failed for {server_id}: {e}")
            return False
    
    def _remove_from_user_registry(self, server_id: str):
        """Remove an integration from user registry."""
        user_registry_path = Path.home() / ".iris" / "user-registry.json"
        
        if not user_registry_path.exists():
            return
        
        with open(user_registry_path) as f:
            registry = json.load(f)
        
        if "integrations" not in registry:
            return
        
        registry["integrations"] = [
            i for i in registry["integrations"]
            if i["id"] != server_id
        ]
        
        with open(user_registry_path, "w") as f:
            json.dump(registry, f, indent=2)
    
    async def check_for_updates(self) -> List[Dict]:
        """
        Check installed servers for available updates.
        
        Returns:
            List of servers with available updates
        """
        updates = []
        
        # Get installed servers from user registry
        registry = self.registry_loader.load_registries()
        
        for server_id, config in registry.items():
            # Skip built-in integrations
            if server_id in ["gmail", "outlook", "telegram", "discord", "imap_smtp"]:
                continue
            
            # Check if update available (placeholder)
            # Real implementation would query registry for latest version
            pass
        
        return updates


class InstallationError(Exception):
    """Raised when installation fails."""
    pass


# Singleton instance
_installer_service: Optional[InstallerService] = None


def get_installer_service(
    registry_loader: Optional[RegistryLoader] = None,
    lifecycle_manager: Optional[IntegrationLifecycleManager] = None,
) -> InstallerService:
    """Get or create the singleton InstallerService instance."""
    global _installer_service
    
    if _installer_service is None:
        _installer_service = InstallerService(
            registry_loader=registry_loader,
            lifecycle_manager=lifecycle_manager,
        )
    
    return _installer_service
