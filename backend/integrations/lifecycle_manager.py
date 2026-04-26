"""
Integration Lifecycle Manager

Manages MCP server process lifecycle: spawn, monitor, restart, and shutdown.
Integrates with RegistryLoader and CredentialStore.
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, List

from .models import IntegrationConfig, IntegrationState, IntegrationStatus
from .credential_store import CredentialStore, CredentialDecryptionError, get_credential_store
from .registry_loader import RegistryLoader, get_registry_loader

# Type hint for memory interface - avoids circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from backend.memory.interface import MemoryInterface

logger = logging.getLogger(__name__)


class ProcessError(Exception):
    """Raised when process operations fail."""
    pass


class CredentialError(Exception):
    """Raised when credential operations fail."""
    pass


@dataclass
class ProcessInfo:
    """Information about a running MCP server process."""
    integration_id: str
    process: subprocess.Popen
    started_at: datetime
    restart_count: int = 0
    last_exit_code: Optional[int] = None
    last_error: Optional[str] = None
    credential_in_env: bool = True  # Track if credential was passed to process
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "integration_id": self.integration_id,
            "pid": self.process.pid if self.process else None,
            "started_at": self.started_at.isoformat(),
            "restart_count": self.restart_count,
            "last_exit_code": self.last_exit_code,
            "last_error": self.last_error,
        }


class IntegrationLifecycleManager:
    """
    Manages the lifecycle of MCP server processes.
    
    Responsibilities:
    - Spawn MCP server processes with credentials via environment
    - Monitor process health and detect crashes
    - Implement automatic restart with backoff
    - Handle graceful shutdown on disable
    - Emit state change events
    """
    
    MAX_RESTART_ATTEMPTS = 3
    RESTART_DELAY_BASE = 2  # seconds
    RESTART_DELAY_MAX = 30  # seconds
    SHUTDOWN_TIMEOUT = 5  # seconds to wait for graceful shutdown
    
    def __init__(
        self,
        credential_store: Optional[CredentialStore] = None,
        registry_loader: Optional[RegistryLoader] = None,
        mcp_host: Optional[Any] = None,  # MCPHost for registering servers
        memory_interface: Optional['MemoryInterface'] = None,
    ):
        self.credential_store = credential_store or get_credential_store()
        self.registry_loader = registry_loader or get_registry_loader()
        self.mcp_host = mcp_host  # For registering with MCP router
        self.memory_interface = memory_interface  # For episodic memory logging
        
        # Process tracking: integration_id -> ProcessInfo
        self._processes: Dict[str, ProcessInfo] = {}
        
        # State tracking: integration_id -> IntegrationState
        self._states: Dict[str, IntegrationState] = {}
        
        # Event callbacks: event_name -> list of callbacks
        self._event_handlers: Dict[str, list] = {
            "state_change": [],
            "process_spawn": [],
            "process_exit": [],
            "process_crash": [],
            "restart_exhausted": [],
        }

        # Tasks for monitoring
        self._monitor_tasks: Dict[str, asyncio.Task] = {}

        # Track callback tasks for cleanup
        self._callback_tasks: Set[asyncio.Task] = set()

        logger.info("IntegrationLifecycleManager initialized")
    
    def on(self, event: str, callback: Callable) -> None:
        """Register an event handler."""
        if event in self._event_handlers:
            self._event_handlers[event].append(callback)
        else:
            raise ValueError(f"Unknown event: {event}")
    
    def _emit(self, event: str, **kwargs) -> None:
        """Emit an event to all registered handlers."""
        for callback in self._event_handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    async def _safe_callback(cb, kw):
                        try:
                            await cb(**kw)
                        except Exception as e:
                            logger.error(f"[LifecycleManager] callback {cb} failed: {e}")

                    task = asyncio.create_task(_safe_callback(callback, kwargs))
                    self._callback_tasks.add(task)
                    task.add_done_callback(self._callback_tasks.discard)
                else:
                    callback(**kwargs)
            except Exception as e:
                logger.error(f"Event handler error for {event}: {e}")
    
    async def _update_state(
        self,
        integration_id: str,
        status: IntegrationStatus,
        error_message: Optional[str] = None,
    ) -> IntegrationState:
        """Update and emit state change for an integration."""
        state = self._states.get(integration_id)
        if state:
            old_status = state.status
            state.status = status
            if error_message:
                state.error_message = error_message
            logger.info(
                f"Integration {integration_id} state: {old_status.value} -> {status.value}"
            )
        else:
            # Create new state
            state = IntegrationState(
                integration_id=integration_id,
                status=status,
                error_message=error_message,
            )
            self._states[integration_id] = state
            logger.info(f"Integration {integration_id} initialized with state: {status.value}")
        
        self._emit("state_change", integration_id=integration_id, state=state)
        return state
    
    async def enable(self, integration_id: str) -> bool:
        """
        Enable an integration by spawning its MCP server.
        
        Flow:
        1. Load integration config from registry
        2. Check for existing credentials
        3. Spawn process with credentials in environment
        4. Register with MCP host
        5. Start monitoring
        
        Returns True if successful, False otherwise.
        """
        logger.info(f"Enabling integration: {integration_id}")
        
        # Check if already running
        if integration_id in self._processes:
            logger.warning(f"Integration {integration_id} is already running")
            return True
        
        # Get config
        config = self.registry_loader.get_integration(integration_id)
        if not config:
            logger.error(f"Integration {integration_id} not found in registry")
            await self._update_state(
                integration_id,
                IntegrationStatus.ERROR,
                f"Integration not found in registry"
            )
            return False
        
        # Check credentials
        try:
            credential_exists = await self.credential_store.exists(integration_id)
            if not credential_exists:
                logger.info(f"No credentials found for {integration_id}, entering AUTH_PENDING")
                await self._update_state(integration_id, IntegrationStatus.AUTH_PENDING)
                return False
            
            # Load and decrypt credentials
            credential = await self.credential_store.load(integration_id)
        except CredentialDecryptionError as e:
            # Decryption failed - credential was corrupted or key changed
            # Credential has been wiped, trigger re-authentication
            logger.warning(
                f"Credential decryption failed for {integration_id}: {e}. "
                "Triggering re-authentication flow."
            )
            await self._update_state(
                integration_id,
                IntegrationStatus.AUTH_PENDING,
                "Stored credential was corrupted. Please re-authenticate."
            )
            return False
        except Exception as e:
            logger.error(f"Failed to load credentials for {integration_id}: {e}")
            await self._update_state(
                integration_id,
                IntegrationStatus.ERROR,
                f"Failed to load credentials: {str(e)}"
            )
            return False
        
        try:
            # Spawn the process
            process = await self._spawn_process(integration_id, config, credential)
            
            # Create process info
            process_info = ProcessInfo(
                integration_id=integration_id,
                process=process,
                started_at=datetime.utcnow(),
            )
            self._processes[integration_id] = process_info
            
            # Register with MCP host if available
            if self.mcp_host:
                await self._register_with_mcp_host(integration_id, process)
            
            # Update state
            await self._update_state(integration_id, IntegrationStatus.RUNNING)
            
            # Start monitoring
            self._start_monitoring(integration_id)
            
            self._emit("process_spawn", integration_id=integration_id, process=process)
            
            # Log successful enable to memory
            await self._log_to_memory(
                integration_id=integration_id,
                event_type="enable",
                description=f"Successfully enabled integration {integration_id} (PID: {process.pid})",
                outcome="success",
                details={"pid": process.pid, "config": config.to_dict() if hasattr(config, 'to_dict') else str(config)},
            )
            
            logger.info(f"Integration {integration_id} enabled successfully (PID: {process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to spawn process for {integration_id}: {e}")
            await self._update_state(
                integration_id,
                IntegrationStatus.ERROR,
                f"Failed to spawn process: {str(e)}"
            )
            
            # Log failure to memory
            await self._log_to_memory(
                integration_id=integration_id,
                event_type="enable",
                description=f"Failed to enable integration {integration_id}",
                outcome="failure",
                details={"error": str(e)},
            )
            
            return False
    
    async def _spawn_process(
        self,
        integration_id: str,
        config: IntegrationConfig,
        credential: Dict[str, Any],
    ) -> subprocess.Popen:
        """Spawn an MCP server process with credentials in environment."""
        mcp_config = config.mcp_server
        
        # Prepare environment
        env = os.environ.copy()
        env["IRIS_CREDENTIAL"] = json.dumps(credential)
        env["IRIS_INTEGRATION_ID"] = integration_id
        env["IRIS_MCP_VERSION"] = "1.0"
        
        # Determine command
        binary = mcp_config.get("binary")
        module = mcp_config.get("module")
        runtime = mcp_config.get("runtime", "node")
        
        if binary:
            # Use pre-built binary
            cmd = [binary]
        elif module:
            # Run via runtime
            if runtime == "python":
                cmd = [sys.executable, "-m", module]
            else:
                cmd = ["node", module]
        else:
            raise ProcessError(f"No binary or module specified for {integration_id}")
        
        # Spawn process with stdio pipes
        logger.debug(f"Spawning: {' '.join(cmd)}")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                bufsize=0,  # Unbuffered for real-time communication
            )
            
            # Verify process started
            if process.poll() is not None:
                raise ProcessError(f"Process exited immediately with code {process.returncode}")
            
            return process
            
        except FileNotFoundError as e:
            raise ProcessError(f"Binary not found: {e}")
        except Exception as e:
            raise ProcessError(f"Failed to spawn process: {e}")
    
    async def _register_with_mcp_host(
        self,
        integration_id: str,
        process: subprocess.Popen,
    ) -> None:
        """Register the process with the MCP host for tool routing."""
        if not self.mcp_host:
            return
        
        try:
            # MCP host expects stdin/stdout for stdio transport
            await self.mcp_host.register_server(
                server_id=integration_id,
                stdin=process.stdin,
                stdout=process.stdout,
            )
            logger.debug(f"Registered {integration_id} with MCP host")
        except Exception as e:
            logger.error(f"Failed to register {integration_id} with MCP host: {e}")
            # Don't fail the enable - the process is running
    
    def _start_monitoring(self, integration_id: str) -> None:
        """Start a background task to monitor the process."""
        task = asyncio.create_task(
            self._monitor_process(integration_id),
            name=f"monitor-{integration_id}"
        )
        self._monitor_tasks[integration_id] = task
    
    async def _monitor_process(self, integration_id: str) -> None:
        """Monitor a process and handle crashes/restarts."""
        while integration_id in self._processes:
            process_info = self._processes.get(integration_id)
            if not process_info:
                break
            
            process = process_info.process
            
            # Check if process has exited
            exit_code = process.poll()
            
            if exit_code is None:
                # Process still running, wait and check again
                await asyncio.sleep(1)
                continue
            
            # Process exited
            process_info.last_exit_code = exit_code
            self._emit("process_exit", integration_id=integration_id, exit_code=exit_code)
            
            if exit_code == 0:
                # Graceful exit (likely from disable)
                logger.info(f"Process {integration_id} exited cleanly")
                del self._processes[integration_id]
                await self._update_state(integration_id, IntegrationStatus.DISABLED)
                break
            
            # Process crashed
            logger.warning(f"Process {integration_id} crashed with code {exit_code}")
            await self._handle_crash(integration_id, exit_code)
            break  # handle_crash will restart or give up
    
    async def _handle_crash(self, integration_id: str, exit_code: int) -> None:
        """Handle a process crash with restart logic."""
        process_info = self._processes.get(integration_id)
        if not process_info:
            return
        
        process_info.restart_count += 1
        self._emit("process_crash", integration_id=integration_id, exit_code=exit_code)
        
        if process_info.restart_count >= self.MAX_RESTART_ATTEMPTS:
            logger.error(
                f"Integration {integration_id} exhausted restart attempts "
                f"({self.MAX_RESTART_ATTEMPTS})"
            )
            del self._processes[integration_id]
            await self._update_state(
                integration_id,
                IntegrationStatus.ERROR,
                f"Process crashed {self.MAX_RESTART_ATTEMPTS} times. Last exit code: {exit_code}"
            )
            self._emit("restart_exhausted", integration_id=integration_id)
            
            # Log restart exhaustion to memory
            await self._log_to_memory(
                integration_id=integration_id,
                event_type="crash",
                description=f"Integration {integration_id} crashed {self.MAX_RESTART_ATTEMPTS} times and exhausted restart attempts",
                outcome="failure",
                details={
                    "exit_code": exit_code,
                    "restart_count": process_info.restart_count,
                    "last_error": process_info.last_error,
                },
            )
            
            return
        
        # Calculate backoff delay
        delay = min(
            self.RESTART_DELAY_BASE * (2 ** (process_info.restart_count - 1)),
            self.RESTART_DELAY_MAX
        )
        
        logger.info(
            f"Restarting {integration_id} in {delay}s "
            f"(attempt {process_info.restart_count}/{self.MAX_RESTART_ATTEMPTS})"
        )
        
        await self._update_state(
            integration_id,
            IntegrationStatus.ERROR,
            f"Process crashed (exit {exit_code}), restarting in {delay}s..."
        )
        
        await asyncio.sleep(delay)
        
        # Attempt restart
        success = await self.enable(integration_id)
        if success:
            logger.info(f"Successfully restarted {integration_id}")
        else:
            logger.error(f"Failed to restart {integration_id}")
    
    async def disable(
        self,
        integration_id: str,
        forget_credentials: bool = False,
    ) -> bool:
        """
        Disable an integration.
        
        Args:
            integration_id: The integration to disable
            forget_credentials: If True, wipe stored credentials
        
        Returns True if successful.
        """
        logger.info(f"Disabling integration: {integration_id} (forget={forget_credentials})")
        
        # Stop monitoring
        if integration_id in self._monitor_tasks:
            task = self._monitor_tasks[integration_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._monitor_tasks[integration_id]
        
        # Kill process if running
        process_info = self._processes.get(integration_id)
        if process_info:
            await self._kill_process(integration_id, process_info)
            del self._processes[integration_id]
        
        # Deregister from MCP host
        if self.mcp_host:
            try:
                await self.mcp_host.deregister_server(integration_id)
            except Exception as e:
                logger.error(f"Failed to deregister {integration_id} from MCP host: {e}")
        
        # Wipe credentials if requested
        if forget_credentials:
            try:
                await self.credential_store.wipe(integration_id)
                logger.info(f"Wiped credentials for {integration_id}")
            except Exception as e:
                logger.error(f"Failed to wipe credentials for {integration_id}: {e}")
            await self._update_state(integration_id, IntegrationStatus.WIPED)
        else:
            await self._update_state(integration_id, IntegrationStatus.DISABLED)
        
        self._emit("state_change", integration_id=integration_id, state=self._states.get(integration_id))
        
        # Log disable to memory
        await self._log_to_memory(
            integration_id=integration_id,
            event_type="disable",
            description=f"Disabled integration {integration_id}" + (" (credentials wiped)" if forget_credentials else ""),
            outcome="success",
            details={"forget_credentials": forget_credentials},
        )
        
        logger.info(f"Integration {integration_id} disabled")
        return True
    
    async def _kill_process(self, integration_id: str, process_info: ProcessInfo) -> None:
        """Kill a process gracefully, then forcefully if needed."""
        process = process_info.process
        
        if process.poll() is not None:
            # Already dead
            return
        
        # Try graceful shutdown first (SIGTERM)
        logger.debug(f"Sending SIGTERM to {integration_id} (PID: {process.pid})")
        try:
            if sys.platform == "win32":
                process.terminate()
            else:
                process.send_signal(signal.SIGTERM)
            
            # Wait for graceful exit
            try:
                process.wait(timeout=self.SHUTDOWN_TIMEOUT)
                logger.debug(f"Process {integration_id} exited gracefully")
                return
            except subprocess.TimeoutExpired:
                logger.warning(f"Process {integration_id} did not exit gracefully, forcing...")
        except Exception as e:
            logger.error(f"Error during graceful shutdown of {integration_id}: {e}")
        
        # Force kill (SIGKILL)
        try:
            if sys.platform == "win32":
                process.kill()
            else:
                process.send_signal(signal.SIGKILL)
            
            process.wait(timeout=2)
            logger.debug(f"Process {integration_id} killed forcefully")
        except Exception as e:
            logger.error(f"Failed to kill process {integration_id}: {e}")
    
    async def restart(self, integration_id: str) -> bool:
        """Restart an integration."""
        logger.info(f"Restarting integration: {integration_id}")
        
        # Disable without forgetting credentials
        await self.disable(integration_id, forget_credentials=False)
        
        # Small delay for cleanup
        await asyncio.sleep(0.5)
        
        # Re-enable
        return await self.enable(integration_id)
    
    def get_state(self, integration_id: str) -> Optional[IntegrationState]:
        """Get current state for an integration."""
        return self._states.get(integration_id)
    
    def get_all_states(self) -> Dict[str, IntegrationState]:
        """Get all integration states."""
        return self._states.copy()
    
    def is_running(self, integration_id: str) -> bool:
        """Check if an integration is currently running."""
        process_info = self._processes.get(integration_id)
        if not process_info:
            return False
        return process_info.process.poll() is None
    
    def get_process_info(self, integration_id: str) -> Optional[ProcessInfo]:
        """Get process information for a running integration."""
        return self._processes.get(integration_id)
    
    async def shutdown_all(self) -> None:
        """Disable all integrations. Called on app shutdown."""
        logger.info("Shutting down all integrations...")

        # Cancel pending callback tasks
        for task in list(self._callback_tasks):
            task.cancel()

        integration_ids = list(self._processes.keys())

        # Disable all concurrently
        tasks = [
            self.disable(int_id, forget_credentials=False)
            for int_id in integration_ids
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("All integrations shut down")
    
    async def get_server_tools(self, integration_id: str) -> list:
        """Get available tools for an integration (delegates to MCP host)."""
        if not self.mcp_host:
            return []
        
        try:
            return await self.mcp_host.get_server_tools(integration_id)
        except Exception as e:
            logger.error(f"Failed to get tools for {integration_id}: {e}")
            return []
    
    def get_running_integrations(self) -> list:
        """Get list of currently running integration IDs."""
        running = []
        for integration_id, process_info in self._processes.items():
            if process_info.process.poll() is None:
                running.append(integration_id)
        return running
    
    def clear_all_states(self) -> None:
        """Clear all in-memory state (used during app shutdown cleanup)."""
        logger.info("Clearing all integration states from memory")
        
        # Clear states (keep them for next launch)
        for state in self._states.values():
            state.status = IntegrationStatus.DISABLED
            state.last_error = None
            state.process_pid = None
        
        # Clear process references
        self._processes.clear()
        
        # Cancel any pending monitor tasks
        for task in self._monitor_tasks.values():
            if not task.done():
                task.cancel()
        self._monitor_tasks.clear()
        
        logger.info("All integration states cleared from memory")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Episodic Memory Integration
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _log_to_memory(
        self,
        integration_id: str,
        event_type: str,
        description: str,
        outcome: str = "info",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log an integration lifecycle event to episodic memory.
        
        Args:
            integration_id: The integration ID
            event_type: Type of event (install, configure, enable, disable, error, etc.)
            description: Human-readable description
            outcome: Event outcome type (success|failure|partial|abandoned|info)
            details: Additional event details
        """
        if not self.memory_interface:
            return
        
        try:
            # Import here to avoid circular imports
            from backend.memory.episodic import Episode
            
            # Build the task summary
            task_summary = f"Integration {integration_id}: {event_type}"
            
            # Build full content with details
            full_content = f"{description}\n\n"
            if details:
                full_content += f"Details: {json.dumps(details, indent=2)}"
            
            # Create episode
            episode = Episode(
                session_id=f"integration_{integration_id}",
                task_summary=task_summary,
                full_content=full_content,
                tool_sequence=[{"type": "integration", "action": event_type, "integration": integration_id}],
                outcome_type=outcome,
                failure_reason=details.get("error") if details and outcome == "failure" else None,
                source_channel="integration_lifecycle",
            )
            
            # Calculate score based on outcome
            score_map = {
                "success": 1.0,
                "info": 0.5,
                "partial": 0.5,
                "abandoned": 0.0,
                "failure": 0.0,
            }
            score = score_map.get(outcome, 0.5)
            
            # Store in episodic memory
            self.memory_interface.episodic.store(episode, score)
            logger.debug(f"[LifecycleManager] Logged to memory: {task_summary}")
            
        except Exception as e:
            logger.error(f"[LifecycleManager] Failed to log to memory: {e}")
    
    async def get_previous_attempts(
        self,
        integration_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Query episodic memory for previous integration attempts.
        
        Args:
            integration_id: The integration to query
            limit: Maximum number of attempts to return
            
        Returns:
            List of previous attempt records
        """
        if not self.memory_interface:
            return []
        
        try:
            # Search for episodes related to this integration
            query = f"Integration {integration_id}"
            episodes = self.memory_interface.episodic.search(query, limit=limit * 2)
            
            # Filter to only integration-related episodes
            results = []
            for episode in episodes:
                if integration_id in episode.task_summary:
                    results.append({
                        "timestamp": episode.timestamp if hasattr(episode, 'timestamp') else None,
                        "event_type": episode.tool_sequence[0].get("action") if episode.tool_sequence else "unknown",
                        "outcome": episode.outcome_type,
                        "summary": episode.task_summary,
                        "description": episode.full_content[:200] if episode.full_content else "",
                    })
                    if len(results) >= limit:
                        break
            
            return results
            
        except Exception as e:
            logger.error(f"[LifecycleManager] Failed to query memory: {e}")
            return []
    
    async def has_previous_failure(self, integration_id: str) -> bool:
        """
        Check if there were previous failed attempts for an integration.
        
        Args:
            integration_id: The integration to check
            
        Returns:
            True if there were previous failures
        """
        attempts = await self.get_previous_attempts(integration_id, limit=5)
        return any(a["outcome"] == "failure" for a in attempts)
    
    # ═══════════════════════════════════════════════════════════════════════
    # Marketplace Preference Storage
    # ═══════════════════════════════════════════════════════════════════════
    
    async def store_marketplace_preference(
        self,
        user_id: str,
        preference_type: str,
        value: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Store a marketplace preference to semantic memory.
        
        Args:
            user_id: The user ID
            preference_type: Type of preference (e.g., 'category_viewed', 'integration_viewed', 'search_query')
            value: The preference value
            metadata: Additional metadata about the preference
            
        Returns:
            True if stored successfully
        """
        if not self.memory_interface:
            logger.debug("[LifecycleManager] No memory interface available for preference storage")
            return False
        
        try:
            # Build preference key
            preference_key = f"marketplace_pref_{user_id}_{preference_type}"
            
            # Build content for semantic memory
            content_parts = [f"Marketplace preference: {preference_type}"]
            if isinstance(value, str):
                content_parts.append(f"Value: {value}")
            elif isinstance(value, (list, dict)):
                content_parts.append(f"Value: {json.dumps(value)}")
            else:
                content_parts.append(f"Value: {str(value)}")
            
            if metadata:
                content_parts.append(f"Metadata: {json.dumps(metadata)}")
            
            full_content = "\n".join(content_parts)
            
            # Store in semantic memory for persistence
            self.memory_interface.semantic.store(
                content=full_content,
                metadata={
                    "type": "marketplace_preference",
                    "user_id": user_id,
                    "preference_type": preference_type,
                    "value": value,
                    "timestamp": datetime.now().isoformat(),
                    **(metadata or {}),
                }
            )
            
            logger.debug(f"[LifecycleManager] Stored marketplace preference: {preference_type}")
            return True
            
        except Exception as e:
            logger.error(f"[LifecycleManager] Failed to store marketplace preference: {e}")
            return False
    
    async def get_marketplace_preferences(
        self,
        user_id: str,
        preference_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve marketplace preferences from semantic memory.
        
        Args:
            user_id: The user ID
            preference_type: Optional filter by preference type
            limit: Maximum number of preferences to return
            
        Returns:
            List of preference dictionaries
        """
        if not self.memory_interface:
            logger.debug("[LifecycleManager] No memory interface available for preference retrieval")
            return []
        
        try:
            # Query for marketplace preferences
            query = f"marketplace_preference {user_id}"
            if preference_type:
                query += f" {preference_type}"
            
            # Search semantic memory
            results = self.memory_interface.semantic.search(
                query=query,
                limit=limit,
                metadata_filter={"type": "marketplace_preference", "user_id": user_id},
            )
            
            preferences = []
            for result in results:
                if hasattr(result, 'metadata') and result.metadata:
                    preferences.append({
                        "preference_type": result.metadata.get("preference_type"),
                        "value": result.metadata.get("value"),
                        "timestamp": result.metadata.get("timestamp"),
                        "metadata": {k: v for k, v in result.metadata.items()
                                    if k not in ["type", "user_id", "preference_type", "value", "timestamp"]},
                    })
            
            return preferences
            
        except Exception as e:
            logger.error(f"[LifecycleManager] Failed to retrieve marketplace preferences: {e}")
            return []
    
    async def get_recommended_integrations(
        self,
        user_id: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Get recommended integrations based on user preferences.
        
        Args:
            user_id: The user ID
            limit: Maximum number of recommendations
            
        Returns:
            List of recommended integration IDs with relevance scores
        """
        if not self.memory_interface:
            return []
        
        try:
            # Get user's category preferences
            category_prefs = await self.get_marketplace_preferences(
                user_id=user_id,
                preference_type="category_viewed",
                limit=20,
            )
            
            # Get user's integration view history
            viewed_integrations = await self.get_marketplace_preferences(
                user_id=user_id,
                preference_type="integration_viewed",
                limit=20,
            )
            
            # Build user profile from preferences
            viewed_ids = set()
            category_counts = {}
            
            for pref in viewed_integrations:
                if pref.get("value"):
                    viewed_ids.add(pref["value"])
            
            for pref in category_prefs:
                cat = pref.get("value")
                if cat:
                    category_counts[cat] = category_counts.get(cat, 0) + 1
            
            # Get all available integrations from registry
            all_integrations = self.registry_loader.list_integrations()
            
            # Score integrations based on user preferences
            scored_integrations = []
            for integration_id, config in all_integrations.items():
                if integration_id in viewed_ids:
                    continue  # Skip already viewed
                
                score = 0
                integration_categories = config.tags or []
                
                # Boost score based on category matches
                for cat in integration_categories:
                    if cat in category_counts:
                        score += category_counts[cat] * 10
                
                # Add to results if there's any relevance
                if score > 0:
                    scored_integrations.append({
                        "integration_id": integration_id,
                        "name": config.name,
                        "description": config.description,
                        "category": config.category,
                        "score": score,
                        "reason": "Based on your category interests",
                    })
            
            # Sort by score descending and limit
            scored_integrations.sort(key=lambda x: x["score"], reverse=True)
            return scored_integrations[:limit]
            
        except Exception as e:
            logger.error(f"[LifecycleManager] Failed to get recommendations: {e}")
            return []


# Singleton instance
_lifecycle_manager: Optional[IntegrationLifecycleManager] = None


def get_lifecycle_manager(
    credential_store: Optional[CredentialStore] = None,
    registry_loader: Optional[RegistryLoader] = None,
    mcp_host: Optional[Any] = None,
) -> IntegrationLifecycleManager:
    """Get or create the singleton lifecycle manager instance."""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = IntegrationLifecycleManager(
            credential_store=credential_store,
            registry_loader=registry_loader,
            mcp_host=mcp_host,
        )
    return _lifecycle_manager


def reset_lifecycle_manager() -> None:
    """Reset the singleton (for testing)."""
    global _lifecycle_manager
    _lifecycle_manager = None
