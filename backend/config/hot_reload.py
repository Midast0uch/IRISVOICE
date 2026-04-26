
"""
Hot-Reload for IRISVOICE Configurations

Implements a system for monitoring configuration files for changes and
dynamically reloading them without requiring a server restart.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Callable, Awaitable, Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from backend.config.config_loader import ConfigurationLoader

logger = logging.getLogger(__name__)


class ConfigChangeHandler(FileSystemEventHandler):
    """Handles file system events for configuration changes."""

    def __init__(self, callback: Callable[[str], Awaitable[None]]):
        """Initialize the handler with a callback function."""
        self.callback = callback
        self.loop = asyncio.get_running_loop()

    def on_modified(self, event: FileModifiedEvent):
        """Called when a file is modified."""
        if not event.is_directory:
            logger.info(f"Configuration file modified: {event.src_path}")
            asyncio.run_coroutine_threadsafe(self.callback(event.src_path), self.loop)


class HotReloadManager:
    """Manages hot-reloading of configurations."""

    def __init__(self, config_loader: ConfigurationLoader):
        """Initialize the hot-reload manager."""
        self.config_loader = config_loader
        self.observer = Observer()
        self.watched_workspaces: Dict[str, asyncio.Task] = {}

        logger.info("Hot-reload manager initialized.")

    async def watch_workspace(self, workspace_id: str,
                              callback: Callable[[str, Dict[str, Any]], Awaitable[None]]):
        """Start watching a workspace's configuration for changes."""
        if workspace_id in self.watched_workspaces:
            logger.warning(f"Workspace {workspace_id} is already being watched.")
            return

        config_path = self.config_loader.config_dir / f"{workspace_id}_config.json"
        if not config_path.exists():
            logger.error(f"Configuration file for workspace {workspace_id} not found.")
            return

        async def reload_callback(file_path: str):
            """Callback function to reload configuration."""
            try:
                logger.info(f"Reloading configuration for workspace: {workspace_id}")
                new_config = await self.config_loader.load_configuration(workspace_id)
                if new_config:
                    await callback(workspace_id, new_config.to_dict())
                    logger.info(f"Successfully reloaded configuration for workspace: {workspace_id}")
                else:
                    logger.error(f"Failed to reload configuration for workspace: {workspace_id}")
            except Exception as e:
                logger.error(f"Error during configuration reload for {workspace_id}: {e}")

        event_handler = ConfigChangeHandler(reload_callback)
        self.observer.schedule(event_handler, str(config_path.parent), recursive=False)

        if not self.observer.is_alive():
            self.observer.start()

        self.watched_workspaces[workspace_id] = asyncio.create_task(self._keep_alive())
        logger.info(f"Started watching workspace: {workspace_id}")

    async def stop_watching_workspace(self, workspace_id: str):
        """Stop watching a workspace's configuration."""
        if workspace_id not in self.watched_workspaces:
            logger.warning(f"Workspace {workspace_id} is not being watched.")
            return

        task = self.watched_workspaces.pop(workspace_id)
        task.cancel()
        # Note: Watchdog observer does not support removing watches, so we just stop the task.
        # To fully unwatch, the observer would need to be restarted.
        logger.info(f"Stopped watching workspace: {workspace_id}")

    def stop_all(self):
        """Stop watching all workspaces and shut down the observer."""
        for task in self.watched_workspaces.values():
            task.cancel()
        self.watched_workspaces.clear()

        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
        logger.info("Hot-reload manager stopped.")

    async def _keep_alive(self):
        """Keep the asyncio task alive to allow callbacks to be scheduled."""
        try:
            while True:
                await asyncio.sleep(3600)  # Sleep for a long time
        except asyncio.CancelledError:
            logger.debug("Keep-alive task cancelled.")
