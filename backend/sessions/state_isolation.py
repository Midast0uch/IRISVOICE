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

from ..models import IRISState, Category, ConfirmedNode, ColorTheme, get_subnodes_for_category
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
        
        # Track memory usage of state objects
        self._memory_tracker.track_object_creation(self._state)
    
    async def initialize(self, persistence_dir: Optional[str] = None):
        """Initialize the isolated state manager"""
        if persistence_dir:
            self._persistence_dir = Path(persistence_dir) / self.session_id
            self._persistence_dir.mkdir(parents=True, exist_ok=True)
            
            # Load existing state if available
            await self._load_state()
            
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
        
        # Final save
        if self._persistence_dir:
            await self._save_state()
        
        # Clean up memory tracking
        self._memory_tracker.cleanup()
    
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
                confirmed_nodes=self._state.confirmed_nodes.copy()
            )
            return state_copy
    
    async def set_category(self, category: Optional[Category]) -> None:
        """Set current category with memory tracking"""
        async with self._lock:
            print(f"[{self.session_id}] set_category: before - {self._state.current_category}, new - {category}")
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
            old_subnode = self._state.current_subnode
            self._state.current_subnode = subnode_id
            
            # Track memory change
            self._memory_tracker.track_state_change("subnode", old_subnode, subnode_id)

            # Auto-save if persistence is enabled
            if self._persistence_dir:
                await self._save_state()
    
    async def update_field(self, subnode_id: str, field_id: str, value: Any) -> bool:
        """Update a field value with validation and memory tracking"""
        async with self._lock:
            # Validate the value
            if not await self._validate_field_value(subnode_id, field_id, value):
                return False
            
            # Get old value for tracking
            old_value = self._state.field_values.get(subnode_id, {}).get(field_id)
            
            # Update the field
            if subnode_id not in self._state.field_values:
                self._state.field_values[subnode_id] = {}
            
            self._state.field_values[subnode_id][field_id] = value
            
            # Track memory change
            self._memory_tracker.track_field_change(subnode_id, field_id, old_value, value)

            # Auto-save if persistence is enabled
            if self._persistence_dir:
                await self._save_state()
            return True
    
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
    
    async def _validate_field_value(self, subnode_id: str, field_id: str, value: Any) -> bool:
        """Validate a field value against its configuration"""
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
        """Save the entire state to a single file."""
        if not self._persistence_dir:
            print("No persistence directory set")
            return

        state_file = self._persistence_dir / "session_state.json"
        print(f"Saving state to {state_file}")
        try:
            async with aiofiles.open(state_file, 'w') as f:
                await f.write(self._state.model_dump_json(indent=2))
        except Exception as e:
            print(f"Error saving state for session {self.session_id}: {e}")

    async def _load_state(self) -> None:
        """Load state from persistence directory"""
        if not self._persistence_dir:
            return
        
        try:
            state_file = self._persistence_dir / "session_state.json"
            print(f"Loading state from {state_file}")
            if state_file.exists():
                async with aiofiles.open(state_file, 'r') as f:
                    data = await f.read()
                    print(f"Read state data: {data}")
                    self._state = IRISState.model_validate_json(data)
            else:
                print("State file does not exist")
        except Exception as e:
            print(f"Error loading state for session {self.session_id}: {e}")

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
            async with aiofiles.open(filepath, 'r') as f:
                content = await f.read()
                return json.loads(content)
        except json.JSONDecodeError:
            print(f"Corrupted JSON in {filename} for session {self.session_id}")
            return None
        except Exception as e:
            print(f"Error reading {filename} for session {self.session_id}: {e}")
            return None
    
    async def _save_json(self, filename: str, data: Dict[str, Any]) -> None:
        """Save JSON file atomically"""
        if not self._persistence_dir:
            return
        
        filepath = self._persistence_dir / filename
        temp_path = filepath.with_suffix('.tmp')
        
        try:
            import aiofiles
            # Write to temp file
            async with aiofiles.open(temp_path, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            
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
            
        except Exception as e:
            print(f"Error saving {filename} for session {self.session_id}: {e}")
    
    # Utility methods
    async def get_field_value(self, subnode_id: str, field_id: str, default: Any = None) -> Any:
        """Get a specific field value by subnode_id"""
        return self._state.field_values.get(subnode_id, {}).get(field_id, default)
    
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