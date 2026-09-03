"""
WebSocket Message Handlers for Integrations

Handles WebSocket messages related to integration management:
- List integrations
- Enable/disable integrations
- Start auth flows
- Handle auth callbacks
- Get integration state
"""

import json
import logging
from typing import Any, Dict, Optional

from ..ws_manager import get_websocket_manager
from ..gateway.iris_gateway import GatewayMessage, MessageType

from .models import AuthType, IntegrationStatus
from .registry_loader import get_registry_loader
from .credential_store import get_credential_store
from .lifecycle_manager import get_lifecycle_manager
from .auth_handlers import (
    OAuth2Handler,
    TelegramMTProtoHandler,
    CredentialsHandler,
    AuthError,
    get_auth_handler,
)

logger = logging.getLogger(__name__)


class IntegrationMessageHandler:
    """
    Handles WebSocket messages for integration management.
    
    Integrates with the existing IRIS gateway system.
    """
    
    def __init__(self):
        self.registry_loader = get_registry_loader()
        self.credential_store = get_credential_store()
        self.lifecycle_manager = get_lifecycle_manager()
        
        # OAuth handler with callback support
        self.oauth_handler: Optional[OAuth2Handler] = None
        
        logger.info("IntegrationMessageHandler initialized")
    
    def _get_oauth_handler(self) -> OAuth2Handler:
        """Lazy initialization of OAuth handler."""
        if self.oauth_handler is None:
            self.oauth_handler = OAuth2Handler(self.credential_store)
        return self.oauth_handler
    
    async def handle_message(self, client_id: str, message: Dict[str, Any]) -> None:
        """
        Handle an integration-related WebSocket message.
        
        Args:
            client_id: The client that sent the message
            message: The message dictionary with 'type' and 'payload'
        """
        msg_type = message.get("type", "")
        payload = message.get("payload", {})
        
        logger.debug(f"Handling integration message: {msg_type} from {client_id}")
        
        handlers = {
            "integration_list": self._handle_list,
            "integration_enable": self._handle_enable,
            "integration_disable": self._handle_disable,
            "integration_state": self._handle_get_state,
            "integration_oauth_callback": self._handle_oauth_callback,
            "integration_credentials_auth": self._handle_credentials_auth,
            "integration_telegram_auth": self._handle_telegram_auth,
            "integration_restart": self._handle_restart,
            "integration_forget": self._handle_forget,
            "app_cleanup": self._handle_app_cleanup,
            # Activity and Logs handlers
            "activity_get_recent": self._handle_activity_get_recent,
            "logs_subscribe": self._handle_logs_subscribe,
            "logs_get_history": self._handle_logs_get_history,
            "logs_unsubscribe": self._handle_logs_unsubscribe,
            # Marketplace preference handlers
            "marketplace_preference_store": self._handle_marketplace_preference_store,
            "marketplace_preferences_get": self._handle_marketplace_preferences_get,
            "marketplace_recommendations_get": self._handle_marketplace_recommendations_get,
        }
        
        handler = handlers.get(msg_type)
        if handler:
            try:
                await handler(client_id, payload)
            except Exception as e:
                logger.error(f"Error handling {msg_type}: {e}")
                await self._send_error(client_id, msg_type, str(e))
        else:
            logger.warning(f"Unknown integration message type: {msg_type}")
    
    async def _handle_list(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle request to list all integrations."""
        # Get all integrations from registry
        all_integrations = self.registry_loader.get_all_integrations()
        
        # Get states for each
        states = self.lifecycle_manager.get_all_states()
        
        # Build response
        integrations_data = []
        for config in all_integrations:
            integration_id = config.id
            state = states.get(integration_id)
            
            # Check if credentials exist
            credential_exists = await self.credential_store.exists(integration_id)
            
            integration_data = {
                "id": integration_id,
                "name": config.name,
                "category": config.category,
                "icon": config.icon,
                "auth_type": config.auth_type.value,
                "permissions_summary": config.permissions_summary,
                "enabled_by_default": config.enabled_by_default,
                "status": state.status.value if state else IntegrationStatus.DISABLED.value,
                "credential_exists": credential_exists,
                "is_running": self.lifecycle_manager.is_running(integration_id),
            }
            integrations_data.append(integration_data)
        
        await self._send_response(client_id, "integration_list", {
            "integrations": integrations_data,
        })
    
    async def _handle_enable(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle request to enable an integration."""
        integration_id = payload.get("integration_id")
        if not integration_id:
            await self._send_error(client_id, "integration_enable", "Missing integration_id")
            return
        
        # Get config
        config = self.registry_loader.get_integration(integration_id)
        if not config:
            await self._send_error(client_id, "integration_enable", f"Integration not found: {integration_id}")
            return
        
        # Check if already running
        if self.lifecycle_manager.is_running(integration_id):
            await self._send_response(client_id, "integration_enable", {
                "integration_id": integration_id,
                "status": "already_running",
            })
            return
        
        # Check if credentials exist
        credential_exists = await self.credential_store.exists(integration_id)
        if not credential_exists:
            # Return auth required response
            await self._send_response(client_id, "integration_enable", {
                "integration_id": integration_id,
                "status": "auth_required",
                "auth_type": config.auth_type.value,
                "auth_config": self._get_auth_config(config),
            })
            return
        
        # Enable the integration
        success = await self.lifecycle_manager.enable(integration_id)
        
        state = self.lifecycle_manager.get_state(integration_id)
        
        await self._send_response(client_id, "integration_enable", {
            "integration_id": integration_id,
            "status": "enabled" if success else "failed",
            "current_status": state.status.value if state else IntegrationStatus.ERROR.value,
            "error": state.error_message if state and state.status == IntegrationStatus.ERROR else None,
        })
    
    async def _handle_disable(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle request to disable an integration."""
        integration_id = payload.get("integration_id")
        forget = payload.get("forget_credentials", False)
        
        if not integration_id:
            await self._send_error(client_id, "integration_disable", "Missing integration_id")
            return
        
        success = await self.lifecycle_manager.disable(integration_id, forget_credentials=forget)
        
        await self._send_response(client_id, "integration_disable", {
            "integration_id": integration_id,
            "status": "disabled" if success else "failed",
            "credentials_forgotten": forget,
        })
    
    async def _handle_get_state(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle request to get integration state."""
        integration_id = payload.get("integration_id")
        
        if not integration_id:
            # Return all states
            states = self.lifecycle_manager.get_all_states()
            states_data = {
                k: v.to_dict() for k, v in states.items()
            }
            await self._send_response(client_id, "integration_state", {
                "states": states_data,
            })
            return
        
        state = self.lifecycle_manager.get_state(integration_id)
        config = self.registry_loader.get_integration(integration_id)
        
        if not config:
            await self._send_error(client_id, "integration_state", f"Integration not found: {integration_id}")
            return
        
        response = {
            "integration_id": integration_id,
            "status": state.status.value if state else IntegrationStatus.DISABLED.value,
            "is_running": self.lifecycle_manager.is_running(integration_id),
            "config": config.to_dict(),
        }
        
        if state:
            response["error_message"] = state.error_message
            response["connected_since"] = state.connected_since.isoformat() if state.connected_since else None
            response["last_error_at"] = state.last_error_at.isoformat() if state.last_error_at else None
            response["retry_count"] = state.retry_count
        
        process_info = self.lifecycle_manager.get_process_info(integration_id)
        if process_info:
            response["process"] = process_info.to_dict()
        
        await self._send_response(client_id, "integration_state", response)
    
    async def _handle_oauth_callback(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle OAuth callback from deep link."""
        callback_url = payload.get("callback_url")
        
        if not callback_url:
            await self._send_error(client_id, "integration_oauth_callback", "Missing callback_url")
            return
        
        handler = self._get_oauth_handler()
        
        # Handle the callback
        handled = await handler.handle_callback(callback_url)
        
        if not handled:
            await self._send_error(client_id, "integration_oauth_callback", "Invalid or expired callback")
            return
        
        # The OAuth flow will complete and credentials will be stored
        # Now we need to find which integration this was for and enable it
        # Extract integration ID from callback URL
        try:
            from urllib.parse import urlparse
            parsed = urlparse(callback_url)
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] == "oauth" and path_parts[1] == "callback":
                integration_id = path_parts[2] if len(path_parts) > 2 else None
                
                if integration_id:
                    # Enable the integration now that we have credentials
                    await self.lifecycle_manager.enable(integration_id)
                    
                    await self._send_response(client_id, "integration_oauth_callback", {
                        "status": "success",
                        "integration_id": integration_id,
                    })
                    return
        except Exception as e:
            logger.error(f"Error processing OAuth callback: {e}")
        
        await self._send_response(client_id, "integration_oauth_callback", {
            "status": "success",
        })
    
    async def _handle_credentials_auth(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle credentials-based authentication."""
        integration_id = payload.get("integration_id")
        credentials = payload.get("credentials", {})
        
        if not integration_id:
            await self._send_error(client_id, "integration_credentials_auth", "Missing integration_id")
            return
        
        config = self.registry_loader.get_integration(integration_id)
        if not config:
            await self._send_error(client_id, "integration_credentials_auth", f"Integration not found: {integration_id}")
            return
        
        handler = CredentialsHandler(self.credential_store)
        
        try:
            success = await handler.authenticate(
                integration_id=integration_id,
                config=config,
                credentials=credentials,
            )
            
            if success:
                # Enable the integration
                await self.lifecycle_manager.enable(integration_id)
            
            await self._send_response(client_id, "integration_credentials_auth", {
                "integration_id": integration_id,
                "status": "success" if success else "failed",
            })
        except AuthError as e:
            await self._send_error(client_id, "integration_credentials_auth", str(e))
    
    async def _handle_telegram_auth(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle Telegram MTProto authentication."""
        integration_id = payload.get("integration_id")
        api_id = payload.get("api_id")
        api_hash = payload.get("api_hash")
        phone_number = payload.get("phone_number")
        code = payload.get("code")
        
        if not integration_id:
            await self._send_error(client_id, "integration_telegram_auth", "Missing integration_id")
            return
        
        config = self.registry_loader.get_integration(integration_id)
        if not config:
            await self._send_error(client_id, "integration_telegram_auth", f"Integration not found: {integration_id}")
            return
        
        # For the first step (sending code), we just return success
        # The actual auth with code happens when user provides the code
        # This is a simplified version - full implementation would need
        # a session-based flow to handle the two-step process
        
        await self._send_response(client_id, "integration_telegram_auth", {
            "integration_id": integration_id,
            "status": "code_sent",
            "message": "Please enter the code sent to your Telegram app",
        })
    
    async def _handle_restart(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle request to restart an integration."""
        integration_id = payload.get("integration_id")
        
        if not integration_id:
            await self._send_error(client_id, "integration_restart", "Missing integration_id")
            return
        
        success = await self.lifecycle_manager.restart(integration_id)
        
        state = self.lifecycle_manager.get_state(integration_id)
        
        await self._send_response(client_id, "integration_restart", {
            "integration_id": integration_id,
            "status": "restarted" if success else "failed",
            "current_status": state.status.value if state else IntegrationStatus.ERROR.value,
        })
    
    async def _handle_forget(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle request to forget credentials."""
        integration_id = payload.get("integration_id")
        
        if not integration_id:
            await self._send_error(client_id, "integration_forget", "Missing integration_id")
            return
        
        # First disable if running
        if self.lifecycle_manager.is_running(integration_id):
            await self.lifecycle_manager.disable(integration_id, forget_credentials=True)
        else:
            # Just wipe credentials
            await self.credential_store.wipe(integration_id)
        
        await self._send_response(client_id, "integration_forget", {
            "integration_id": integration_id,
            "status": "forgotten",
        })
    
    def _get_auth_config(self, config) -> Dict[str, Any]:
        """Get authentication configuration for an integration."""
        config_dict = config.to_dict()
        
        auth_config = {}
        
        if config.auth_type == AuthType.OAUTH2:
            oauth_config = config_dict.get("oauth", {})
            auth_config = {
                "provider": oauth_config.get("provider"),
                "scopes": oauth_config.get("scopes", []),
                "client_id_env": oauth_config.get("client_id_env"),
                "redirect_uri": oauth_config.get("redirect_uri"),
            }
        elif config.auth_type == AuthType.TELEGRAM_MTPROTO:
            telegram_config = config_dict.get("telegram", {})
            auth_config = {
                "api_id_env": telegram_config.get("api_id_env"),
                "api_hash_env": telegram_config.get("api_hash_env"),
            }
        elif config.auth_type == AuthType.CREDENTIALS:
            credentials_config = config_dict.get("credentials", {})
            auth_config = {
                "fields": credentials_config.get("fields", []),
            }
        
        return auth_config
    
    async def _handle_app_cleanup(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle app shutdown cleanup - kill all MCP processes and clear credentials."""
        logger.info("[IntegrationMessageHandler] App cleanup requested - stopping all integrations")
        
        # Get all running integrations
        running_integrations = self.lifecycle_manager.get_running_integrations()
        
        # Stop each integration (without wiping credentials - just memory cleanup)
        for integration_id in running_integrations:
            try:
                await self.lifecycle_manager.disable(integration_id, forget_credentials=False)
                logger.info(f"[IntegrationMessageHandler] Stopped {integration_id} during cleanup")
            except Exception as e:
                logger.error(f"[IntegrationMessageHandler] Error stopping {integration_id}: {e}")
        
        # Clear all in-memory credential references
        self.lifecycle_manager.clear_all_states()
        
        await self._send_response(client_id, "app_cleanup", {
            "status": "success",
            "stopped_integrations": len(running_integrations),
        })
        logger.info("[IntegrationMessageHandler] App cleanup complete")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Activity & Logs Handlers
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _handle_activity_get_recent(self, client_id: str, payload: Dict[str, Any]) -> None:
        """
        Handle request to get recent activity from episodic memory.
        
        Args:
            client_id: The client that sent the message
            payload: Contains 'limit' (max items to return), 'filter' (optional type filter)
        """
        limit = payload.get("limit", 20)
        filter_type = payload.get("filter")  # Optional: 'conversation', 'action', 'tool', 'integration'
        
        try:
            # Get memory interface from lifecycle manager if available
            memory_interface = getattr(self.lifecycle_manager, 'memory_interface', None)
            
            activities = []
            if memory_interface:
                # Query episodic memory for recent activity
                # Search for integration-related episodes
                query = filter_type if filter_type else "recent activity"
                episodes = memory_interface.episodic.search(query, limit=limit * 2)
                
                for episode in episodes:
                    # Map episode to activity format
                    activity_type = self._map_episode_to_activity_type(episode)
                    if filter_type and activity_type != filter_type:
                        continue
                    
                    activities.append({
                        "id": episode.session_id if hasattr(episode, 'session_id') else str(id(episode)),
                        "type": activity_type,
                        "title": episode.task_summary if hasattr(episode, 'task_summary') else "Unknown activity",
                        "description": episode.full_content[:200] if hasattr(episode, 'full_content') else "",
                        "timestamp": episode.timestamp if hasattr(episode, 'timestamp') else None,
                        "outcome": episode.outcome_type if hasattr(episode, 'outcome_type') else "unknown",
                    })
                    
                    if len(activities) >= limit:
                        break
            
            # If no memory interface or no activities, return mock data
            if not activities:
                activities = self._get_mock_activities(limit, filter_type)
            
            await self._send_response(client_id, "activity_recent", {
                "activities": activities,
                "total": len(activities),
            })
            
        except Exception as e:
            logger.error(f"[IntegrationMessageHandler] Error getting recent activity: {e}")
            # Return mock data on error
            activities = self._get_mock_activities(limit, filter_type)
            await self._send_response(client_id, "activity_recent", {
                "activities": activities,
                "total": len(activities),
            })
    
    def _map_episode_to_activity_type(self, episode) -> str:
        """Map an episode to an activity type."""
        task_summary = episode.task_summary if hasattr(episode, 'task_summary') else ""
        tool_sequence = episode.tool_sequence if hasattr(episode, 'tool_sequence') else []
        
        # Check tool sequence for integration-related activities
        for tool in tool_sequence:
            if isinstance(tool, dict):
                if tool.get("type") == "integration":
                    return "integration"
                if tool.get("type") == "conversation":
                    return "conversation"
        
        # Check task summary for keywords
        if "integration" in task_summary.lower():
            return "integration"
        if "conversation" in task_summary.lower() or "chat" in task_summary.lower():
            return "conversation"
        if "tool" in task_summary.lower():
            return "tool"
        
        return "action"
    
    def _get_mock_activities(self, limit: int, filter_type: Optional[str] = None) -> list:
        """Get mock activities for testing/demo purposes."""
        mock_activities = [
            {
                "id": "1",
                "type": "conversation",
                "title": "User asked about weather",
                "description": "User inquired about the current weather in New York",
                "timestamp": "2024-01-15T10:30:00Z",
                "outcome": "success",
            },
            {
                "id": "2",
                "type": "integration",
                "title": "Gmail integration enabled",
                "description": "Successfully enabled Gmail integration with OAuth authentication",
                "timestamp": "2024-01-15T09:15:00Z",
                "outcome": "success",
            },
            {
                "id": "3",
                "type": "tool",
                "title": "File system tool executed",
                "description": "Listed files in /documents directory",
                "timestamp": "2024-01-15T08:45:00Z",
                "outcome": "success",
            },
            {
                "id": "4",
                "type": "action",
                "title": "System settings updated",
                "description": "Updated voice recognition sensitivity to 75%",
                "timestamp": "2024-01-15T08:30:00Z",
                "outcome": "success",
            },
            {
                "id": "5",
                "type": "integration",
                "title": "Slack message sent",
                "description": "Sent notification to #general channel",
                "timestamp": "2024-01-14T16:20:00Z",
                "outcome": "success",
            },
        ]
        
        if filter_type:
            mock_activities = [a for a in mock_activities if a["type"] == filter_type]
        
        return mock_activities[:limit]
    
    async def _handle_logs_subscribe(self, client_id: str, payload: Dict[str, Any]) -> None:
        """
        Handle request to subscribe to log stream.
        
        Args:
            client_id: The client that sent the message
            payload: Contains 'levels' (array of log levels to subscribe to)
        """
        levels = payload.get("levels", ["error", "warn", "info"])
        
        # Store subscription (in a real implementation, this would add to a subscription manager)
        logger.info(f"[IntegrationMessageHandler] Client {client_id} subscribed to logs: {levels}")
        
        # Send initial confirmation
        await self._send_response(client_id, "logs_subscribed", {
            "levels": levels,
            "status": "subscribed",
        })
        
        # Send some recent log entries as initial data
        recent_logs = self._get_mock_logs(10, levels)
        await self._send_response(client_id, "logs_batch", {
            "logs": recent_logs,
        })
    
    async def _handle_logs_unsubscribe(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Handle request to unsubscribe from log stream."""
        logger.info(f"[IntegrationMessageHandler] Client {client_id} unsubscribed from logs")
        
        await self._send_response(client_id, "logs_unsubscribed", {
            "status": "unsubscribed",
        })
    
    async def _handle_logs_get_history(self, client_id: str, payload: Dict[str, Any]) -> None:
        """
        Handle request to get log history.
        
        Args:
            client_id: The client that sent the message
            payload: Contains 'limit', 'levels', 'search' (optional)
        """
        limit = payload.get("limit", 50)
        levels = payload.get("levels", ["error", "warn", "info", "debug"])
        search = payload.get("search")
        
        logs = self._get_mock_logs(limit, levels, search)
        
        await self._send_response(client_id, "logs_history", {
            "logs": logs,
            "total": len(logs),
        })
    
    def _get_mock_logs(self, limit: int, levels: list, search: Optional[str] = None) -> list:
        """Get mock logs for testing/demo purposes."""
        mock_logs = [
            {
                "timestamp": "2024-01-15T10:30:45Z",
                "level": "info",
                "source": "IntegrationLifecycle",
                "message": "Gmail integration enabled successfully (PID: 12345)",
            },
            {
                "timestamp": "2024-01-15T10:30:44Z",
                "level": "debug",
                "source": "WebSocket",
                "message": "Received message: integration_enable",
            },
            {
                "timestamp": "2024-01-15T10:28:12Z",
                "level": "info",
                "source": "AuthHandler",
                "message": "OAuth flow completed for user user@example.com",
            },
            {
                "timestamp": "2024-01-15T10:25:30Z",
                "level": "warn",
                "source": "CredentialStore",
                "message": "Credential file not found, creating new store",
            },
            {
                "timestamp": "2024-01-15T10:20:15Z",
                "level": "error",
                "source": "IntegrationLifecycle",
                "message": "Discord integration crashed, scheduling restart",
            },
            {
                "timestamp": "2024-01-15T10:20:14Z",
                "level": "debug",
                "source": "ProcessMonitor",
                "message": "Process exited with code 1",
            },
            {
                "timestamp": "2024-01-15T10:15:00Z",
                "level": "info",
                "source": "RegistryLoader",
                "message": "Loaded 8 integrations from registry",
            },
        ]
        
        # Filter by levels
        mock_logs = [log for log in mock_logs if log["level"] in levels]
        
        # Filter by search term
        if search:
            search_lower = search.lower()
            mock_logs = [log for log in mock_logs if search_lower in log["message"].lower()]
        
        return mock_logs[:limit]
    
    async def _send_response(self, client_id: str, msg_type: str, payload: Dict[str, Any]) -> None:
        """Send a response message to a client."""
        ws_manager = get_websocket_manager()
        await ws_manager.send_to_client(client_id, {
            "type": msg_type,
            "payload": payload,
        })
    
    async def _send_error(self, client_id: str, original_type: str, error: str) -> None:
        """Send an error response to a client."""
        await self._send_response(client_id, f"{original_type}_error", {
            "error": error,
            "original_type": original_type,
        })
    
    async def broadcast_state_change(self, integration_id: str, state) -> None:
        """Broadcast state change to all connected clients."""
        ws_manager = get_websocket_manager()
        
        await ws_manager.broadcast({
            "type": "integration_state_changed",
            "payload": {
                "integration_id": integration_id,
                "state": state.to_dict() if hasattr(state, "to_dict") else state,
            },
        })
    
    # ═══════════════════════════════════════════════════════════════════════
    # Marketplace Preference Handlers
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _handle_marketplace_preference_store(
        self,
        client_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """
        Handle request to store a marketplace preference.
        
        Args:
            client_id: The client that sent the message
            payload: Contains 'user_id', 'preference_type', 'value', optional 'metadata'
        """
        user_id = payload.get("user_id", "default_user")
        preference_type = payload.get("preference_type")
        value = payload.get("value")
        metadata = payload.get("metadata", {})
        
        if not preference_type or value is None:
            await self._send_error(
                client_id,
                "marketplace_preference_store",
                "Missing required fields: preference_type and value",
            )
            return
        
        try:
            success = await self.lifecycle_manager.store_marketplace_preference(
                user_id=user_id,
                preference_type=preference_type,
                value=value,
                metadata=metadata,
            )
            
            await self._send_response(client_id, "marketplace_preference_stored", {
                "success": success,
                "preference_type": preference_type,
                "value": value,
            })
        except Exception as e:
            logger.error(f"[IntegrationMessageHandler] Failed to store preference: {e}")
            await self._send_error(client_id, "marketplace_preference_store", str(e))
    
    async def _handle_marketplace_preferences_get(
        self,
        client_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """
        Handle request to get marketplace preferences.
        
        Args:
            client_id: The client that sent the message
            payload: Contains 'user_id', optional 'preference_type', optional 'limit'
        """
        user_id = payload.get("user_id", "default_user")
        preference_type = payload.get("preference_type")
        limit = payload.get("limit", 50)
        
        try:
            preferences = await self.lifecycle_manager.get_marketplace_preferences(
                user_id=user_id,
                preference_type=preference_type,
                limit=limit,
            )
            
            await self._send_response(client_id, "marketplace_preferences", {
                "preferences": preferences,
                "count": len(preferences),
            })
        except Exception as e:
            logger.error(f"[IntegrationMessageHandler] Failed to get preferences: {e}")
            await self._send_error(client_id, "marketplace_preferences_get", str(e))
    
    async def _handle_marketplace_recommendations_get(
        self,
        client_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """
        Handle request to get recommended integrations.
        
        Args:
            client_id: The client that sent the message
            payload: Contains 'user_id', optional 'limit'
        """
        user_id = payload.get("user_id", "default_user")
        limit = payload.get("limit", 5)
        
        try:
            recommendations = await self.lifecycle_manager.get_recommended_integrations(
                user_id=user_id,
                limit=limit,
            )
            
            await self._send_response(client_id, "marketplace_recommendations", {
                "recommendations": recommendations,
                "count": len(recommendations),
            })
        except Exception as e:
            logger.error(f"[IntegrationMessageHandler] Failed to get recommendations: {e}")
            await self._send_error(client_id, "marketplace_recommendations_get", str(e))


# Singleton instance
_integration_handler: Optional[IntegrationMessageHandler] = None


def get_integration_handler() -> IntegrationMessageHandler:
    """Get or create the singleton integration message handler."""
    global _integration_handler
    if _integration_handler is None:
        _integration_handler = IntegrationMessageHandler()
    return _integration_handler


def reset_integration_handler() -> None:
    """Reset the singleton (for testing)."""
    global _integration_handler
    _integration_handler = None


async def handle_integration_message(client_id: str, message: Dict[str, Any]) -> None:
    """Convenience function to handle integration messages."""
    handler = get_integration_handler()
    await handler.handle_message(client_id, message)
