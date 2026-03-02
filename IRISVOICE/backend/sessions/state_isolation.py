"""
IRIS State Isolation
Provides isolated state management for sessions with memory tracking
"""
import asyncio
import aiofiles
import json
import tempfile
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime
import weakref

from ..core_models import IRISState, Category, ConfirmedNode, ColorTheme, AppState
from ..core_models import get_subnodes_for_category
from .memory_bounds import MemoryTracker


class IsolatedStateManager:
    """Isolated state manager for individual sessions"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._state = IRISState()
        self._memory_tracker = MemoryTracker(session_id)
        self._lock = asyncio.Lock()
        self._persistence_dir: Optional[Path] = None
        self._auto_save_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self._state_change_callbacks: list[weakref.ReferenceType] = []
        
        # Navigation history stack for go_back functionality
        self._navigation_history: list[tuple[Optional[Category], Optional[str]]] = []
        
        # Track memory usage of state objects
        self._memory_tracker.track_object_creation(self._state)
    
    async def initialize(self, persistence_dir: Optional[str] = None):
        """Initialize the isolated state manager"""
        if persistence_dir:
            self._persistence_dir = Path(persistence_dir) / self.session_id
            self._persistence_dir.mkdir(parents=True, exist_ok=True)
            
            # Load existing state if available
            await self._load_state()
            
            # Restore model selections to AgentKernel if they exist
            await self._restore_model_selections()
            
            # Start auto-save task
            self._auto_save_task = asyncio.create_task(self._periodic_auto_save())
    
    async def cleanup(self):
        """Clean up resources"""
        self._shutdown = True
        
        if self._auto_save_task:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
        
        # Save final state
        await self._save_state()
    
    async def update_app_state(self, app_state: AppState) -> None:
        """Update the application state"""
        async with self._lock:
            self._state.app_state = app_state
            self._memory_tracker.track_state_change("app_state", app_state.value)
            await self._save_state()
            
            # Notify any state change listeners
            await self._notify_state_change("app_state", app_state.value)
    
    @property
    def state(self) -> IRISState:
        """Get current state (read-only, use methods to modify)"""
        return self._state
    
    async def get_state_copy(self) -> IRISState:
        """Get a deep copy of the current state"""
        async with self._lock:
            # Create a copy to prevent external modification
            state_copy = IRISState(
                current_category=self._state.current_category,
                current_subnode=self._state.current_subnode,
                field_values=self._state.field_values.copy(),
                active_theme=self._state.active_theme,
                confirmed_nodes=self._state.confirmed_nodes.copy(),
                selected_reasoning_model=self._state.selected_reasoning_model,
                selected_tool_execution_model=self._state.selected_tool_execution_model
            )
            return state_copy
    
    async def set_category(self, category: Optional[Category]) -> None:
        """Set current category with memory tracking"""
        async with self._lock:
            print(f"[{self.session_id}] set_category: before - {self._state.current_category}, new - {category}")
            
            # Save current state to navigation history before changing
            self._navigation_history.append((self._state.current_category, self._state.current_subnode))
            
            old_category = self._state.current_category
            self._state.current_category = category
            self._state.current_subnode = None
            print(f"[{self.session_id}] set_category: after - {self._state.current_category}")
            
            # Track memory change
            self._memory_tracker.track_state_change("category", old_category, category)

            # Auto-save if persistence is enabled
            if self._persistence_dir:
                await self._save_state()
    
    async def set_subnode(self, subnode_id: Optional[str]) -> None:
        """Set current subnode with memory tracking"""
        async with self._lock:
            # Save current state to navigation history before changing
            self._navigation_history.append((self._state.current_category, self._state.current_subnode))
            
            old_subnode = self._state.current_subnode
            self._state.current_subnode = subnode_id
            
            # Track memory change
            self._memory_tracker.track_state_change("subnode", old_subnode, subnode_id)

            # Auto-save if persistence is enabled
            if self._persistence_dir:
                await self._save_state()
    
    async def update_field(self, subnode_id: str, field_id: str, value: Any, timestamp: Optional[float] = None) -> tuple[bool, float]:
        """Update a field value with validation, memory tracking, and timestamp handling
        
        Special handling for model selection fields (reasoning_model, tool_execution_model):
        These are stored as top-level state fields rather than in field_values.
        
        Special handling for API keys (openai_api_key):
        These are encrypted before storage for security.
        
        Returns:
            tuple[bool, float]: (success, timestamp) - success indicates if update was applied,
                               timestamp is the timestamp of this update
        """
        async with self._lock:
            try:
                # Generate timestamp if not provided
                if timestamp is None:
                    timestamp = datetime.now().timestamp()
                
                # Special handling for model selection fields
                if field_id == "reasoning_model":
                    self._state.selected_reasoning_model = value
                    print(f"[{self.session_id}] Updated reasoning model selection: {value}")
                    if self._persistence_dir:
                        await self._save_state()
                    return True, timestamp
                elif field_id == "tool_execution_model":
                    self._state.selected_tool_execution_model = value
                    print(f"[{self.session_id}] Updated tool execution model selection: {value}")
                    if self._persistence_dir:
                        await self._save_state()
                    return True, timestamp
                
                # Validate the value
                if not await self._validate_field_value(subnode_id, field_id, value):
                    print(f"[{self.session_id}] Field validation failed for {subnode_id}.{field_id}")
                    return False, timestamp
                
                # Encrypt API keys before storage
                stored_value = value
                if field_id == "openai_api_key" and value:
                    from ..utils.encryption import encrypt_api_key
                    stored_value = encrypt_api_key(value)
                    print(f"[{self.session_id}] Encrypted API key for storage")
                
                # Check if we have a timestamp tracker for this field
                field_key = f"{subnode_id}:{field_id}"
                if not hasattr(self, '_field_timestamps'):
                    self._field_timestamps: Dict[str, float] = {}
                
                # Handle out-of-order updates: only apply if timestamp is newer
                existing_timestamp = self._field_timestamps.get(field_key, 0.0)
                if timestamp < existing_timestamp:
                    # This is an out-of-order update, ignore it
                    return False, timestamp
                
                # Get old value for tracking
                old_value = self._state.field_values.get(subnode_id, {}).get(field_id)
                
                # Update the field with encrypted value
                if subnode_id not in self._state.field_values:
                    self._state.field_values[subnode_id] = {}
                
                self._state.field_values[subnode_id][field_id] = stored_value
                
                # Update timestamp tracker
                self._field_timestamps[field_key] = timestamp
                
                # Track memory change
                self._memory_tracker.track_field_change(subnode_id, field_id, old_value, stored_value)

                # Auto-save if persistence is enabled with retry
                if self._persistence_dir:
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            await self._save_state()
                            break
                        except Exception as save_error:
                            if attempt == max_retries - 1:
                                print(f"[{self.session_id}] Failed to save state after {max_retries} attempts: {save_error}")
                                # Continue anyway - field is updated in memory
                            else:
                                await asyncio.sleep(0.1 * (attempt + 1))  # Exponential backoff
                
                return True, timestamp
            except Exception as e:
                print(f"[{self.session_id}] Error updating field {subnode_id}.{field_id}: {e}")
                return False, timestamp
    
    async def confirm_subnode(self, category: str, subnode_id: str, values: Dict[str, Any]) -> float:
        """Confirm a subnode and add it to orbit with memory tracking"""
        async with self._lock:
            # Calculate orbit angle
            existing_count = len(self._state.confirmed_nodes)
            orbit_angle = -90 + (existing_count * 45)
            
            # Get subnode info
            subnodes = get_subnodes_for_category(category)
            subnode = next((s for s in subnodes if s.id == subnode_id), None)
            
            if subnode:
                confirmed = ConfirmedNode(
                    id=subnode_id,
                    label=subnode.label,
                    icon=subnode.icon,
                    orbit_angle=orbit_angle,
                    values=values,
                    category=category
                )
                
                # Remove existing if same id
                self._state.confirmed_nodes = [n for n in self._state.confirmed_nodes if n.id != confirmed.id]
                self._state.confirmed_nodes.append(confirmed)
                
                # Track memory change
                self._memory_tracker.track_confirmed_node_change(subnode_id, values)
                
                # Auto-save if persistence is enabled
                if self._persistence_dir:
                    await self._save_state()
            
            return orbit_angle
    
    async def update_theme(self, glow_color: Optional[str] = None, font_color: Optional[str] = None, state_colors: Optional[dict] = None) -> None:
        """Update theme colors with memory tracking"""
        async with self._lock:
            old_theme = self._state.active_theme.model_dump()
            
            if glow_color:
                self._state.active_theme.glow = glow_color
                self._state.active_theme.primary = glow_color
            if font_color:
                self._state.active_theme.font = font_color
            if state_colors:
                if "enabled" in state_colors:
                    self._state.active_theme.state_colors_enabled = state_colors["enabled"]
                if "idle" in state_colors:
                    self._state.active_theme.idle_color = state_colors["idle"]
                if "listening" in state_colors:
                    self._state.active_theme.listening_color = state_colors["listening"]
                if "processing" in state_colors:
                    self._state.active_theme.processing_color = state_colors["processing"]
                if "error" in state_colors:
                    self._state.active_theme.error_color = state_colors["error"]
            
            # Track memory change
            new_theme = self._state.active_theme.model_dump()
            self._memory_tracker.track_theme_change(old_theme, new_theme)
            
            # Auto-save theme if persistence is enabled
            if self._persistence_dir:
                await self._save_theme()
    
    async def clear_confirmed_nodes(self) -> None:
        """Clear all confirmed nodes with memory tracking"""
        async with self._lock:
            old_count = len(self._state.confirmed_nodes)
            self._state.confirmed_nodes = []
            
            # Track memory change
            self._memory_tracker.track_confirmed_nodes_clear(old_count)
            
            # Auto-save if persistence is enabled
            if self._persistence_dir:
                await self._save_all_categories()
    
    async def go_back(self) -> None:
        """Navigate back to the previous navigation state"""
        async with self._lock:
            if self._navigation_history:
                # Pop the last navigation state from history
                previous_category, previous_subnode = self._navigation_history.pop()
                
                # Restore the previous state without adding to history
                self._state.current_category = previous_category
                self._state.current_subnode = previous_subnode
                
                # Auto-save if persistence is enabled
                if self._persistence_dir:
                    await self._save_state()
    
    async def collapse_to_idle(self) -> None:
        """Collapse the UI to idle state"""
        async with self._lock:
            # Clear navigation state
            self._state.current_category = None
            self._state.current_subnode = None
            
            # Clear navigation history
            self._navigation_history.clear()
            
            # Auto-save if persistence is enabled
            if self._persistence_dir:
                await self._save_state()
    
    async def _validate_field_value(self, subnode_id: str, field_id: str, value: Any) -> bool:
        """Validate a field value against its configuration"""
        # Import validation utilities
        from ..utils.api_validation import validate_openai_key, validate_api_url
        from ..utils.encryption import encrypt_api_key
        
        # Special validation for OpenAI API key fields
        if field_id == "openai_api_key":
            if not value:  # Allow empty (user might configure later)
                return True
            is_valid, error_msg = validate_openai_key(value)
            if not is_valid:
                print(f"[{self.session_id}] OpenAI API key validation failed: {error_msg}")
                return False
            return True
        
        # Special validation for OpenAI API URL fields
        if field_id == "openai_api_url":
            if not value:  # Allow empty (will use default)
                return True
            is_valid, error_msg = validate_api_url(value)
            if not is_valid:
                print(f"[{self.session_id}] OpenAI API URL validation failed: {error_msg}")
                return False
            return True
        
        # Implementation copied from StateManager but adapted for async
        category = self._get_category_for_subnode(subnode_id)
        subnodes = get_subnodes_for_category(category)
        
        subnode = next((s for s in subnodes if s.id == subnode_id), None)
        if not subnode:
            return True  # Unknown subnode, allow it
        
        for field in subnode.fields:
            if field.id == field_id:
                # Type-specific validation
                if field.type.value == "slider":
                    if not isinstance(value, (int, float)):
                        return False
                    if field.min is not None and value < field.min:
                        return False
                    if field.max is not None and value > field.max:
                        return False
                elif field.type.value == "toggle":
                    if not isinstance(value, bool):
                        return False
                elif field.type.value == "color":
                    if not isinstance(value, str):
                        return False
                    if not value.startswith('#') or len(value) != 7:
                        return False
                elif field.type.value == "dropdown":
                    if field.options and value not in field.options:
                        return False
                
                return True
        
        return True  # Unknown field, allow it
    
    def _get_category_for_subnode(self, subnode_id: str) -> str:
        """Derive category from subnode_id"""
        category_map = {
            "input": "voice", "output": "voice", "processing": "voice", "model": "voice",
            "identity": "agent", "wake": "agent", "speech": "agent", "memory": "agent",
            "tools": "automate", "workflows": "automate", "favorites": "automate", "shortcuts": "automate",
            "power": "system", "display": "system", "storage": "system", "network": "system",
            "theme": "customize", "startup": "customize", "behavior": "customize", "notifications": "customize",
            "analytics": "monitor", "logs": "monitor", "diagnostics": "monitor", "updates": "monitor",
        }
        return category_map.get(subnode_id, "misc")
    
    # Persistence methods
    async def _save_state(self):
        """Save the entire state to a single file with error handling."""
        if not self._persistence_dir:
            print("No persistence directory set")
            return

        state_file = self._persistence_dir / "session_state.json"
        print(f"Saving state to {state_file}")
        try:
            # Create backup before saving
            if state_file.exists():
                backup_file = state_file.with_suffix('.json.bak')
                try:
                    import shutil
                    shutil.copy2(state_file, backup_file)
                except Exception as backup_error:
                    print(f"Warning: Failed to create backup: {backup_error}")
            
            async with aiofiles.open(state_file, 'w', encoding='utf-8') as f:
                await f.write(self._state.model_dump_json(indent=2))
        except PermissionError as e:
            print(f"Permission error saving state for session {self.session_id}: {e}")
            raise
        except OSError as e:
            print(f"OS error saving state for session {self.session_id}: {e}")
            raise
        except Exception as e:
            print(f"Error saving state for session {self.session_id}: {e}")
            raise

    async def _load_state(self) -> None:
        """Load state from persistence directory with corruption recovery"""
        if not self._persistence_dir:
            return
        
        state_file = self._persistence_dir / "session_state.json"
        backup_file = state_file.with_suffix('.json.bak')
        
        # Try loading from main file first
        try:
            print(f"Loading state from {state_file}")
            if state_file.exists():
                async with aiofiles.open(state_file, 'r', encoding='utf-8') as f:
                    data = await f.read()
                    print(f"Read state data: {data}")
                    self._state = IRISState.model_validate_json(data)
                    return
            else:
                print("State file does not exist")
        except json.JSONDecodeError as e:
            print(f"Corrupted state file for session {self.session_id}: {e}")
            # Try loading from backup
            if backup_file.exists():
                try:
                    print(f"Attempting to load from backup: {backup_file}")
                    async with aiofiles.open(backup_file, 'r', encoding='utf-8') as f:
                        data = await f.read()
                        self._state = IRISState.model_validate_json(data)
                        print(f"Successfully restored from backup")
                        # Save the restored state as the main file
                        await self._save_state()
                        return
                except Exception as backup_error:
                    print(f"Failed to load from backup: {backup_error}")
            
            # If both fail, use default state and log warning
            print(f"Warning: Using default state for session {self.session_id} due to corruption")
            self._state = IRISState()
        except Exception as e:
            print(f"Error loading state for session {self.session_id}: {e}")
            # Use default state on any other error
            self._state = IRISState()

    async def get_memory_usage(self) -> int:
        """Get the current memory usage of the state in bytes."""
        return len(json.dumps(self._state.model_dump()))
    
    async def _save_category(self, category: str) -> bool:
        """Save a category's state to JSON"""
        if not self._persistence_dir:
            return False
        
        try:
            # Collect field values for all subnodes in this category
            category_fields = {}
            for subnode_id in self._state.field_values:
                if self._get_category_for_subnode(subnode_id) == category:
                    category_fields[subnode_id] = self._state.field_values[subnode_id]
            
            data = {
                'fields': category_fields,
                'confirmed': [
                    {
                        'id': n.id,
                        'label': n.label,
                        'icon': n.icon,
                        'orbit_angle': n.orbit_angle,
                        'values': n.values,
                        'category': n.category
                    }
                    for n in self._state.confirmed_nodes 
                    if self._get_category_for_subnode(n.id) == category
                ],
                'last_updated': datetime.now().isoformat()
            }
            
            await self._save_json(f"{category}.json", data)
            return True
            
        except Exception as e:
            print(f"Error saving category {category} for session {self.session_id}: {e}")
            return False
    
    async def _save_theme(self) -> bool:
        """Save theme to JSON"""
        if not self._persistence_dir:
            return False
        
        try:
            data = self._state.active_theme.model_dump()
            data['last_updated'] = datetime.now().isoformat()
            await self._save_json("theme.json", data)
            return True
        except Exception as e:
            print(f"Error saving theme for session {self.session_id}: {e}")
            return False
    
    async def _save_all_categories(self) -> None:
        """Save all categories"""
        for category in ["voice", "agent", "automate", "system", "customize", "monitor"]:
            await self._save_category(category)
    
    async def _periodic_auto_save(self):
        """Periodically auto-save state"""
        while not self._shutdown:
            try:
                await asyncio.sleep(30)  # Auto-save every 30 seconds
                
                if self._persistence_dir:
                    await self._save_all_categories()
                    await self._save_theme()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in auto-save for session {self.session_id}: {e}")
    
    # JSON persistence helpers
    async def _load_json(self, filename: str) -> Optional[Dict[str, Any]]:
        """Load JSON file asynchronously"""
        if not self._persistence_dir:
            return None
        
        filepath = self._persistence_dir / filename
        
        if not filepath.exists():
            return None
        
        try:
            import aiofiles
            async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except json.JSONDecodeError:
            print(f"Corrupted JSON in {filename} for session {self.session_id}")
            return None
        except Exception as e:
            print(f"Error reading {filename} for session {self.session_id}: {e}")
            return None
    
    async def _save_json(self, filename: str, data: Dict[str, Any]) -> None:
        """Save JSON file atomically with error handling"""
        if not self._persistence_dir:
            return
        
        filepath = self._persistence_dir / filename
        temp_path = filepath.with_suffix('.tmp')
        
        try:
            import aiofiles
            # Write to temp file
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))
            
            # Atomic rename
            import os
            if hasattr(os, 'fsync'):
                # Open in binary mode for fsync
                fd = os.open(str(temp_path), os.O_RDWR)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            
            os.replace(str(temp_path), str(filepath))
            
        except PermissionError as e:
            print(f"Permission error saving {filename} for session {self.session_id}: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass
            raise
        except OSError as e:
            print(f"OS error saving {filename} for session {self.session_id}: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass
            raise
        except Exception as e:
            print(f"Error saving {filename} for session {self.session_id}: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass
            raise
    
    async def _restore_model_selections(self):
        """Restore model selections to AgentKernel after loading state"""
        try:
            # Import here to avoid circular dependency
            from ..agent.agent_kernel import get_agent_kernel
            
            # Get the AgentKernel for this session
            agent_kernel = get_agent_kernel(self.session_id)
            
            # Restore model selections if they exist in state
            if self._state.selected_reasoning_model or self._state.selected_tool_execution_model:
                success = agent_kernel.set_model_selection(
                    reasoning_model=self._state.selected_reasoning_model,
                    tool_execution_model=self._state.selected_tool_execution_model
                )
                
                if success:
                    print(f"[{self.session_id}] Restored model selections: "
                          f"reasoning={self._state.selected_reasoning_model}, "
                          f"tool_execution={self._state.selected_tool_execution_model}")
                else:
                    print(f"[{self.session_id}] Warning: Failed to restore model selections. "
                          f"Models may not be available.")
        except Exception as e:
            print(f"[{self.session_id}] Error restoring model selections: {e}")
    
    # Utility methods
    async def get_field_value(self, subnode_id: str, field_id: str, default: Any = None) -> Any:
        """Get a specific field value by subnode_id"""
        return self._state.field_values.get(subnode_id, {}).get(field_id, default)
    
    async def get_decrypted_field_value(self, subnode_id: str, field_id: str, default: Any = None) -> Any:
        """
        Get a specific field value, decrypting if it's an API key.
        
        Args:
            subnode_id: The subnode ID
            field_id: The field ID
            default: Default value if field not found
            
        Returns:
            Decrypted value for API keys, plain value for other fields
        """
        value = self._state.field_values.get(subnode_id, {}).get(field_id, default)
        
        # Decrypt API keys
        if field_id == "openai_api_key" and value:
            from ..utils.encryption import decrypt_api_key
            return decrypt_api_key(value)
        
        return value
    
    async def get_masked_field_value(self, subnode_id: str, field_id: str, default: Any = None) -> Any:
        """
        Get a specific field value, masking if it's an API key.
        
        Args:
            subnode_id: The subnode ID
            field_id: The field ID
            default: Default value if field not found
            
        Returns:
            Masked value for API keys, plain value for other fields
        """
        # First decrypt the value
        value = await self.get_decrypted_field_value(subnode_id, field_id, default)
        
        # Mask API keys
        if field_id == "openai_api_key" and value:
            from ..utils.encryption import mask_api_key
            return mask_api_key(value)
        
        return value
    
    async def get_subnode_field_values(self, subnode_id: str) -> Dict[str, Any]:
        """Get all field values for a subnode"""
        return self._state.field_values.get(subnode_id, {}).copy()
    
    async def get_category_field_values(self, category: str) -> Dict[str, Dict[str, Any]]:
        """Get all field values for all subnodes in a category"""
        result = {}
        for subnode_id, values in self._state.field_values.items():
            if self._get_category_for_subnode(subnode_id) == category:
                result[subnode_id] = values.copy()
        return result
    
    def register_state_change_callback(self, callback: Any) -> None:
        """Register a callback to be notified of state changes."""
        self._state_change_callbacks.append(weakref.ref(callback))
    
    async def _notify_state_change(self, key: str, value: Any) -> None:
        """Notify registered callbacks of a state change."""
        for callback_ref in self._state_change_callbacks[:]:  # Iterate over a copy
            callback = callback_ref()
            if callback:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(key, value)
                    else:
                        callback(key, value)
                except Exception as e:
                    print(f"Error in state change callback: {e}")
            else:
                # Remove dead references
                self._state_change_callbacks.remove(callback_ref)