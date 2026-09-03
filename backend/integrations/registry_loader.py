"""
Registry Loader - Loads and merges bundled and user registries
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .models import IntegrationConfig

logger = logging.getLogger(__name__)


class RegistryLoader:
    """
    Loads and merges bundled registry with user-installed registry.

    The bundled registry (integrations/registry.json) is read-only and ships with Iris.
    The user registry (~/.iris/user-registry.json) is writable and stores marketplace installs.

    User registry entries override bundled entries with the same ID.
    """

    BUNDLED_REGISTRY_PATH = Path("integrations/registry.json")
    USER_REGISTRY_FILENAME = "user-registry.json"
    IRIS_DIR = ".iris"

    def __init__(
        self,
        bundled_path: Optional[Path] = None,
        user_registry_dir: Optional[Path] = None
    ):
        """
        Initialize the registry loader.

        Args:
            bundled_path: Path to bundled registry.json. Defaults to ./integrations/registry.json
            user_registry_dir: Directory for user registry. Defaults to ~/.iris
        """
        self._bundled_path = bundled_path or self.BUNDLED_REGISTRY_PATH

        if user_registry_dir:
            self._user_registry_dir = Path(user_registry_dir)
        else:
            self._user_registry_dir = Path.home() / self.IRIS_DIR

        self._user_registry_path = self._user_registry_dir / self.USER_REGISTRY_FILENAME

        # Cache for loaded registries
        self._bundled_integrations: Dict[str, IntegrationConfig] = {}
        self._user_integrations: Dict[str, IntegrationConfig] = {}
        self._merged_integrations: Dict[str, IntegrationConfig] = {}

    def _ensure_user_registry_exists(self) -> None:
        """Create user registry file if it doesn't exist"""
        if not self._user_registry_path.exists():
            logger.info(f"[RegistryLoader] Creating user registry at {self._user_registry_path}")
            self._user_registry_dir.mkdir(parents=True, exist_ok=True)

            # Create empty registry
            empty_registry = {"integrations": []}
            with open(self._user_registry_path, 'w') as f:
                json.dump(empty_registry, f, indent=2)

            logger.info("[RegistryLoader] User registry created successfully")

    def _load_bundled_registry(self) -> Dict[str, IntegrationConfig]:
        """Load the bundled (read-only) registry"""
        try:
            if not self._bundled_path.exists():
                logger.warning(f"[RegistryLoader] Bundled registry not found at {self._bundled_path}")
                return {}

            with open(self._bundled_path, 'r') as f:
                data = json.load(f)

            integrations = {}
            for item in data.get("integrations", []):
                try:
                    config = IntegrationConfig.from_dict(item)
                    integrations[config.id] = config
                except Exception as e:
                    logger.error(f"[RegistryLoader] Failed to parse bundled integration {item.get('id')}: {e}")

            logger.info(f"[RegistryLoader] Loaded {len(integrations)} bundled integrations")
            return integrations

        except json.JSONDecodeError as e:
            logger.error(f"[RegistryLoader] Failed to parse bundled registry: {e}")
            return {}
        except Exception as e:
            logger.error(f"[RegistryLoader] Error loading bundled registry: {e}")
            return {}

    def _load_user_registry(self) -> Dict[str, IntegrationConfig]:
        """Load the user (writable) registry"""
        try:
            self._ensure_user_registry_exists()

            with open(self._user_registry_path, 'r') as f:
                data = json.load(f)

            integrations = {}
            for item in data.get("integrations", []):
                try:
                    config = IntegrationConfig.from_dict(item)
                    integrations[config.id] = config
                except Exception as e:
                    logger.error(f"[RegistryLoader] Failed to parse user integration {item.get('id')}: {e}")

            logger.info(f"[RegistryLoader] Loaded {len(integrations)} user-installed integrations")
            return integrations

        except json.JSONDecodeError as e:
            logger.error(f"[RegistryLoader] Failed to parse user registry: {e}")
            return {}
        except Exception as e:
            logger.error(f"[RegistryLoader] Error loading user registry: {e}")
            return {}

    def load_registries(self, force_reload: bool = False) -> Dict[str, IntegrationConfig]:
        """
        Load and merge bundled and user registries.

        User registry entries override bundled entries with the same ID.

        Args:
            force_reload: If True, reload from disk even if already cached

        Returns:
            Dictionary mapping integration_id to IntegrationConfig
        """
        if not force_reload and self._merged_integrations:
            return self._merged_integrations

        # Load both registries
        self._bundled_integrations = self._load_bundled_registry()
        self._user_integrations = self._load_user_registry()

        # Merge: user overrides bundled
        merged = dict(self._bundled_integrations)  # Start with bundled
        merged.update(self._user_integrations)  # Override with user

        self._merged_integrations = merged

        logger.info(f"[RegistryLoader] Total integrations after merge: {len(merged)}")
        return merged

    def get_integration(self, integration_id: str) -> Optional[IntegrationConfig]:
        """
        Get a specific integration by ID.

        Args:
            integration_id: The integration ID

        Returns:
            IntegrationConfig if found, None otherwise
        """
        if not self._merged_integrations:
            self.load_registries()

        return self._merged_integrations.get(integration_id)

    def get_all_integrations(self) -> List[IntegrationConfig]:
        """
        Get all integrations as a list.

        Returns:
            List of IntegrationConfig objects
        """
        if not self._merged_integrations:
            self.load_registries()

        return list(self._merged_integrations.values())

    def get_integrations_by_category(self, category: str) -> List[IntegrationConfig]:
        """
        Get integrations filtered by category.

        Args:
            category: Category name (e.g., "email", "messaging")

        Returns:
            List of IntegrationConfig objects in that category
        """
        all_integrations = self.get_all_integrations()
        return [i for i in all_integrations if i.category == category]

    def get_categories(self) -> List[str]:
        """
        Get all unique categories.

        Returns:
            List of category names
        """
        all_integrations = self.get_all_integrations()
        categories = sorted(set(i.category for i in all_integrations))
        return categories

    def add_user_integration(self, config: IntegrationConfig) -> bool:
        """
        Add a new user-installed integration to the user registry.

        Args:
            config: The integration configuration to add

        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure user registry exists
            self._ensure_user_registry_exists()

            # Load current user registry
            with open(self._user_registry_path, 'r') as f:
                data = json.load(f)

            # Check if integration already exists
            existing = [i for i in data.get("integrations", []) if i.get("id") == config.id]
            if existing:
                # Update existing
                for i, item in enumerate(data["integrations"]):
                    if item.get("id") == config.id:
                        data["integrations"][i] = config.to_dict()
                        break
            else:
                # Add new
                data["integrations"].append(config.to_dict())

            # Write back
            with open(self._user_registry_path, 'w') as f:
                json.dump(data, f, indent=2)

            # Update cache
            self._user_integrations[config.id] = config
            self._merged_integrations[config.id] = config

            logger.info(f"[RegistryLoader] Added user integration: {config.id}")
            return True

        except Exception as e:
            logger.error(f"[RegistryLoader] Failed to add user integration: {e}")
            return False

    def remove_user_integration(self, integration_id: str) -> bool:
        """
        Remove a user-installed integration from the user registry.

        Args:
            integration_id: The integration ID to remove

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self._user_registry_path.exists():
                return False

            # Load current user registry
            with open(self._user_registry_path, 'r') as f:
                data = json.load(f)

            # Filter out the integration
            original_count = len(data.get("integrations", []))
            data["integrations"] = [
                i for i in data.get("integrations", [])
                if i.get("id") != integration_id
            ]

            if len(data["integrations"]) == original_count:
                logger.warning(f"[RegistryLoader] Integration not found in user registry: {integration_id}")
                return False

            # Write back
            with open(self._user_registry_path, 'w') as f:
                json.dump(data, f, indent=2)

            # Update cache
            if integration_id in self._user_integrations:
                del self._user_integrations[integration_id]

            # Restore from bundled if it exists there
            if integration_id in self._bundled_integrations:
                self._merged_integrations[integration_id] = self._bundled_integrations[integration_id]
            else:
                del self._merged_integrations[integration_id]

            logger.info(f"[RegistryLoader] Removed user integration: {integration_id}")
            return True

        except Exception as e:
            logger.error(f"[RegistryLoader] Failed to remove user integration: {e}")
            return False


# Global instance for convenience
_registry_loader: Optional[RegistryLoader] = None


def get_registry_loader() -> RegistryLoader:
    """Get the global registry loader instance"""
    global _registry_loader
    if _registry_loader is None:
        _registry_loader = RegistryLoader()
    return _registry_loader
