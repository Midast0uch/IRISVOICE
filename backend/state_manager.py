"""
IRIS State Manager
Singleton pattern for managing application state with JSON persistence
"""
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

import aiofiles
from pydantic import ValidationError

from .models import (
    IRISState, 
    ColorTheme, 
    Category, 
    ConfirmedNode, 
    get_subnodes_for_category,
    SUBNODE_CONFIGS
)


class StateManager:
    """
    Singleton state manager for IRIS backend.
    Handles state in-memory storage and async JSON persistence.
    """
    _instance: Optional['StateManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, settings_dir: Optional[str] = None):
        if StateManager._initialized:
            return
            
        # Default settings directory
        if settings_dir is None:
            base_dir = Path(__file__).parent
            settings_dir = base_dir / "settings"
        else:
            settings_dir = Path(settings_dir)
        
        self.settings_dir = Path(settings_dir)
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory state
        self._state: IRISState = IRISState()
        self._lock = False  # Simple lock for async operations
        
        StateManager._initialized = True
    
    @property
    def state(self) -> IRISState:
        """Get current state (read-only, use methods to modify)"""
        return self._state
    
    # ========================================================================
    # State Modification Methods
    # ========================================================================
    
    def set_category(self, category: Optional[Category]) -> None:
        """Set current category"""
        self._state.current_category = category
        self._state.current_subnode = None
    
    def set_subnode(self, subnode_id: Optional[str]) -> None:
        """Set current subnode"""
        self._state.current_subnode = subnode_id
    
    def update_field(self, subnode_id: str, field_id: str, value: Any) -> bool:
        """
        Update a field value using subnode_id as primary key.
        Category is derived from subnode_id for organizational purposes only.
        """
        # Validate the value based on field type
        if not self._validate_field_value(subnode_id, field_id, value):
            return False
        
        # Store flat by subnode_id
        self._state.set_field_value(subnode_id, field_id, value)
        return True
    
    def _get_category_for_subnode(self, subnode_id: str) -> str:
        """Derive category from subnode_id for file organization."""
        category_map = {
            "input": "voice", "output": "voice", "processing": "voice", "model": "voice",
            "identity": "agent", "wake": "agent", "speech": "agent", "memory": "agent",
            "tools": "automate", "workflows": "automate", "favorites": "automate", "shortcuts": "automate",
            "power": "system", "display": "system", "storage": "system", "network": "system",
            "theme": "customize", "startup": "customize", "behavior": "customize", "notifications": "customize",
            "analytics": "monitor", "logs": "monitor", "diagnostics": "monitor", "updates": "monitor",
        }
        return category_map.get(subnode_id, "misc")
    
    def _validate_field_value(self, subnode_id: str, field_id: str, value: Any) -> bool:
        """Validate a field value against its configuration"""
        # Get category for this subnode
        category = self._get_category_for_subnode(subnode_id)
        
        # Get subnode config for this category
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
    
    def confirm_subnode(self, category: str, subnode_id: str, values: Dict[str, Any]) -> float:
        """
        Confirm a subnode and add it to orbit.
        Returns the orbit angle assigned.
        """
        # Calculate orbit angle (space 45 degrees apart, starting at -90)
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
            self._state.add_confirmed_node(confirmed)
        
        return orbit_angle
    
    def update_theme(self, glow_color: Optional[str] = None, font_color: Optional[str] = None, state_colors: Optional[dict] = None) -> None:
        """Update theme colors and state colors"""
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
    
    def clear_confirmed_nodes(self) -> None:
        """Clear all confirmed nodes (e.g., when going back to main menu)"""
        self._state.confirmed_nodes = []
    
    # ========================================================================
    # Persistence Methods
    # ========================================================================
    
    async def load_all(self) -> None:
        """Load all persisted state from JSON files"""
        try:
            self._migrate_legacy_category_files()
            # Load theme
            theme_data = await self._load_json("theme.json")
            if theme_data:
                self._state.active_theme = ColorTheme(**theme_data)
            
            # Load field values for each category
            for category in SUBNODE_CONFIGS.keys():
                category_data = await self._load_json(f"{category}.json")
                if category_data:
                    fields = category_data.get('fields', {})
                    
                    # MIGRATION: Check if fields are stored under category key (old format)
                    # or subnode_id keys (new format)
                    if category in fields and isinstance(fields[category], dict):
                        # Old format: fields[category] = {field_id: value}
                        # Convert to new format by detecting subnode from field_id
                        fields = self._migrate_category_fields(category, fields)
                    
                    self._state.field_values.update(fields)
                    
                    # Restore confirmed nodes
                    confirmed = category_data.get('confirmed', [])
                    for conf in confirmed:
                        node = ConfirmedNode(**conf)
                        if not any(n.id == node.id for n in self._state.confirmed_nodes):
                            self._state.confirmed_nodes.append(node)
            
        except Exception as e:
            print(f"Error loading state: {e}")
            # Continue with default state

    def _migrate_category_fields(self, category: str, fields: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Migrate old category-based field structure to subnodeId-based.
        Old: {category: {field_id: value}}
        New: {subnode_id: {field_id: value}}
        """
        migrated = {}
        category_fields = fields.get(category, {})
        
        # Get subnode configs for this category
        subnodes = get_subnodes_for_category(category)
        subnode_field_map = {}
        for subnode in subnodes:
            for field in subnode.fields:
                subnode_field_map[field.id] = subnode.id
        
        # Migrate each field to its subnode
        for field_id, value in category_fields.items():
            subnode_id = subnode_field_map.get(field_id)
            if subnode_id:
                if subnode_id not in migrated:
                    migrated[subnode_id] = {}
                migrated[subnode_id][field_id] = value
            else:
                # Unknown field, put under category as fallback
                if category not in migrated:
                    migrated[category] = {}
                migrated[category][field_id] = value
        
        print(f"[Migration] Converted {len(category_fields)} fields from category '{category}' to subnode structure")
        return migrated

    def _migrate_legacy_category_files(self) -> None:
        """Rename legacy category files to new names with .bak backups."""
        legacy_map = {
            "ai_model": "voice",
            "memory": "agent",
            "analytics": "monitor",
            "system": "customize",
        }

        for legacy, current in legacy_map.items():
            legacy_path = self.settings_dir / f"{legacy}.json"
            current_path = self.settings_dir / f"{current}.json"

            if not legacy_path.exists() or current_path.exists():
                continue

            backup_path = legacy_path.with_suffix(".json.bak")
            try:
                shutil.copy2(legacy_path, backup_path)
                os.replace(str(legacy_path), str(current_path))
            except Exception as e:
                print(f"Error migrating {legacy_path.name}: {e}")
    
    async def save_category(self, category: str) -> bool:
        """
        Persist a category's state to JSON.
        Gathers all subnodes that belong to this category.
        """
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
            print(f"Error saving category {category}: {e}")
            return False
    
    async def save_theme(self) -> bool:
        """Persist theme to JSON"""
        try:
            data = self._state.active_theme.model_dump()
            data['last_updated'] = datetime.now().isoformat()
            await self._save_json("theme.json", data)
            return True
        except Exception as e:
            print(f"Error saving theme: {e}")
            return False
    
    async def _load_json(self, filename: str) -> Optional[Dict[str, Any]]:
        """Load JSON file asynchronously"""
        filepath = self.settings_dir / filename
        
        if not filepath.exists():
            return None
        
        try:
            async with aiofiles.open(filepath, 'r') as f:
                content = await f.read()
                return json.loads(content)
        except json.JSONDecodeError:
            print(f"Corrupted JSON in {filename}")
            return None
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            return None
    
    async def _save_json(self, filename: str, data: Dict[str, Any]) -> None:
        """
        Save JSON file atomically.
        1. Write to temp file
        2. Sync to disk
        3. Atomic rename
        """
        filepath = self.settings_dir / filename
        temp_path = filepath.with_suffix('.tmp')
        
        # Write to temp file
        async with aiofiles.open(temp_path, 'w') as f:
            await f.write(json.dumps(data, indent=2))
        
        # Atomic rename (sync first if possible)
        if hasattr(os, 'fsync'):
            # Open in binary mode for fsync
            fd = os.open(str(temp_path), os.O_RDWR | os.O_BINARY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        
        # Atomic rename
        os.replace(str(temp_path), str(filepath))
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def get_field_value(self, subnode_id: str, field_id: str, default: Any = None) -> Any:
        """Get a specific field value by subnode_id"""
        return self._state.field_values.get(subnode_id, {}).get(field_id, default)
    
    def get_subnode_field_values(self, subnode_id: str) -> Dict[str, Any]:
        """Get all field values for a subnode"""
        return self._state.field_values.get(subnode_id, {})
    
    def get_category_field_values(self, category: str) -> Dict[str, Dict[str, Any]]:
        """Get all field values for all subnodes in a category"""
        result = {}
        for subnode_id, values in self._state.field_values.items():
            if self._get_category_for_subnode(subnode_id) == category:
                result[subnode_id] = values
        return result


# Global instance getter
def get_state_manager() -> StateManager:
    """Get the singleton StateManager instance"""
    return StateManager()
