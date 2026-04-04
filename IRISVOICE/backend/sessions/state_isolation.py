"""
IRIS Isolated State Manager
Per-session state isolation — each session has its own IRISState.
Handles persistence, auto-save, and state restoration.
"""
import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional, Any, Callable, List
from datetime import datetime

logger = logging.getLogger(__name__)


class IsolatedStateManager:
    """
    Per-session state manager. Each session has its own IRISState, persisted
    to a directory under backend/sessions/<session_id>/.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        from backend.core_models import IRISState
        self._state = IRISState()
        from backend.sessions.memory_bounds import MemoryTracker
        self._memory_tracker = MemoryTracker(session_id)
        self._lock = asyncio.Lock()
        self._persistence_dir: Optional[Path] = None
        self._auto_save_task: Optional[asyncio.Task] = None
        self._navigation_history: List = []
        self._state_change_callbacks: List = []
        self._shutdown = False

    async def initialize(self, persistence_dir: Optional[Path] = None) -> None:
        """Initialize state, loading from persistence dir if provided."""
        if persistence_dir:
            self._persistence_dir = Path(persistence_dir)
            self._persistence_dir.mkdir(parents=True, exist_ok=True)
            await self._load_state()
            await self._restore_model_selections()
            self._auto_save_task = asyncio.create_task(self._periodic_auto_save())

    async def cleanup(self) -> None:
        """Shutdown auto-save and persist final state."""
        self._shutdown = True
        if self._auto_save_task:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
        if self._persistence_dir:
            await self._save_state()

    @property
    def state(self):
        return self._state

    async def update_app_state(self, app_state: Any) -> None:
        async with self._lock:
            self._state.app_state = app_state
            self._memory_tracker.track_state_change("app_state", None, app_state)
            if self._persistence_dir:
                await self._save_state()
            await self._notify_state_change("app_state", app_state)

    async def get_state_copy(self):
        async with self._lock:
            from backend.core_models import IRISState
            return self._state.model_copy() if hasattr(self._state, 'model_copy') else self._state

    async def set_category(self, category: str) -> None:
        async with self._lock:
            old_category = self._state.current_category
            self._navigation_history.append(old_category)
            self._state.current_category = category
            self._state.current_section = None
            self._memory_tracker.track_state_change("category", old_category, category)

    async def set_section(self, section_id: str) -> None:
        async with self._lock:
            old_section = self._state.current_section
            self._navigation_history.append(self._state.current_category)
            self._state.current_section = section_id
            self._memory_tracker.track_state_change("section", old_section, section_id)
            if self._persistence_dir:
                await self._save_state()

    async def update_field(self, section_id: str, field_id: str, value: Any) -> None:
        async with self._lock:
            timestamp = datetime.now()
            stored_value = value
            field_key = f"{section_id}.{field_id}"

            # Check if this is an API key field
            try:
                from backend.utils.encryption import encrypt_api_key
                if "api_key" in field_id.lower() or "token" in field_id.lower():
                    stored_value = encrypt_api_key(str(value)) if value else value
            except Exception:
                pass

            if not hasattr(self._state, 'field_values') or self._state.field_values is None:
                self._state.field_values = {}
            if section_id not in self._state.field_values:
                self._state.field_values[section_id] = {}
            self._state.field_values[section_id][field_id] = stored_value

            # Update model selections if this is a model selection field
            if section_id == "model_selection":
                if field_id == "reasoning_model":
                    self._state.selected_reasoning_model = str(value) if value else None
                elif field_id == "tool_execution_model":
                    self._state.selected_tool_execution_model = str(value) if value else None

            if self._persistence_dir:
                await self._save_state()

    async def confirm_section(self, category: str, section_id: str, values: Dict[str, Any]) -> None:
        async with self._lock:
            if not hasattr(self._state, 'field_values') or self._state.field_values is None:
                self._state.field_values = {}
            if section_id not in self._state.field_values:
                self._state.field_values[section_id] = {}
            for field_id, value in values.items():
                self._state.field_values[section_id][field_id] = value
            if self._persistence_dir:
                await self._save_state()

    async def update_theme(self, glow_color: str = None, font_color: str = None,
                            state_colors: Dict = None, **kwargs) -> None:
        async with self._lock:
            old_theme = self._state.active_theme
            if glow_color and hasattr(self._state.active_theme, 'glow'):
                self._state.active_theme.glow = glow_color
            if font_color and hasattr(self._state.active_theme, 'font'):
                self._state.active_theme.font = font_color
            self._memory_tracker.track_theme_change(old_theme, self._state.active_theme)
            if self._persistence_dir:
                await self._save_theme()

    async def go_back(self) -> None:
        async with self._lock:
            if self._navigation_history:
                previous = self._navigation_history.pop()
                self._state.current_category = previous
                self._state.current_section = None
            if self._persistence_dir:
                await self._save_state()

    async def collapse_to_idle(self) -> None:
        async with self._lock:
            self._state.current_category = None
            self._state.current_section = None
            self._navigation_history.clear()
            if self._persistence_dir:
                await self._save_state()

    def get_field_value(self, section_id: str, field_id: str, default: Any = None) -> Any:
        fv = getattr(self._state, 'field_values', None) or {}
        return fv.get(section_id, {}).get(field_id, default)

    def get_section_field_values(self, section_id: str) -> Dict[str, Any]:
        fv = getattr(self._state, 'field_values', None) or {}
        return dict(fv.get(section_id, {}))

    def get_category_field_values(self, category: str) -> Dict[str, Any]:
        fv = getattr(self._state, 'field_values', None) or {}
        result = {}
        for section_id, values in fv.items():
            if self._get_category_for_section(section_id) == category:
                result.update(dict(values))
        return result

    def get_decrypted_field_value(self, section_id: str, field_id: str, default: Any = None) -> Any:
        value = self.get_field_value(section_id, field_id, default)
        try:
            from backend.utils.encryption import decrypt_api_key
            return decrypt_api_key(value) if value else value
        except Exception:
            return value

    def get_masked_field_value(self, section_id: str, field_id: str, default: Any = None) -> Any:
        value = self.get_decrypted_field_value(section_id, field_id, default)
        try:
            from backend.utils.encryption import mask_api_key
            return mask_api_key(value) if value else value
        except Exception:
            return value

    def register_state_change_callback(self, callback: Callable) -> None:
        self._state_change_callbacks.append(weakref.ref(callback) if False else callback)

    async def _notify_state_change(self, key: str, value: Any) -> None:
        for callback in list(self._state_change_callbacks):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(key, value)
                else:
                    callback(key, value)
            except Exception as e:
                logger.debug(f"[StateIsolation:{self.session_id}] Callback error: {e}")
                try:
                    self._state_change_callbacks.remove(callback)
                except Exception:
                    pass

    def _get_category_for_section(self, section_id: str) -> Optional[str]:
        category_map = {
            "model_selection": "agent",
            "agent_settings": "agent",
            "voice_settings": "voice",
            "appearance": "appearance",
            "api_keys": "api",
            "system": "system",
        }
        return category_map.get(section_id)

    async def _save_state(self) -> None:
        if not self._persistence_dir:
            return
        try:
            state_file = self._persistence_dir / "state.json"
            backup_file = state_file.with_suffix(".bak")
            if state_file.exists():
                try:
                    shutil.copy2(state_file, backup_file)
                except Exception:
                    pass
            data = {}
            if hasattr(self._state, 'model_dump'):
                data = self._state.model_dump()
            else:
                data = {"field_values": getattr(self._state, 'field_values', {})}
            async with _aiofiles_open(state_file, 'w') as f:
                await f.write(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.debug(f"[StateIsolation:{self.session_id}] Save failed: {e}")

    async def _load_state(self) -> None:
        if not self._persistence_dir:
            return
        for path, label in [
            (self._persistence_dir / "state.json", "primary"),
            (self._persistence_dir / "state.bak", "backup"),
        ]:
            if path.exists():
                try:
                    async with _aiofiles_open(path, 'r') as f:
                        raw = await f.read()
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        fv = data.get("field_values", {})
                        if isinstance(fv, dict):
                            self._state.field_values = fv
                    return
                except Exception as e:
                    logger.debug(f"[StateIsolation:{self.session_id}] Load {label} failed: {e}")

    async def _restore_model_selections(self) -> None:
        try:
            from backend.agent.agent_kernel import get_agent_kernel
            agent_kernel = get_agent_kernel()
            fv = getattr(self._state, 'field_values', {}) or {}
            ms_fv = fv.get("model_selection", {})
            reasoning = ms_fv.get("reasoning_model")
            tool_exec = ms_fv.get("tool_execution_model")
            provider = ms_fv.get("provider")
            if reasoning or tool_exec:
                try:
                    success = agent_kernel.set_model_selection(
                        reasoning_model=reasoning,
                        tool_exec_model=tool_exec,
                        provider=provider,
                        session_id=self.session_id,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    async def _save_category(self, category: str) -> None:
        if not self._persistence_dir:
            return
        try:
            fv = getattr(self._state, 'field_values', {}) or {}
            category_fields = {
                sid: vals for sid, vals in fv.items()
                if self._get_category_for_section(sid) == category
            }
            data = {
                "category": category,
                "fields": category_fields,
                "saved_at": datetime.now().isoformat(),
            }
            await self._save_json(f"{category}.json", data)
        except Exception as e:
            logger.debug(f"[StateIsolation:{self.session_id}] Save category '{category}' failed: {e}")

    async def _save_theme(self) -> None:
        if not self._persistence_dir:
            return
        try:
            theme = getattr(self._state, 'active_theme', None)
            data = {
                "theme": theme.model_dump() if hasattr(theme, 'model_dump') else {},
                "saved_at": datetime.now().isoformat(),
            }
            await self._save_json("theme.json", data)
        except Exception as e:
            logger.debug(f"[StateIsolation:{self.session_id}] Save theme failed: {e}")

    async def _save_all_categories(self) -> None:
        for category in ["agent", "voice", "appearance", "api", "system"]:
            await self._save_category(category)

    async def _periodic_auto_save(self) -> None:
        while not self._shutdown:
            try:
                await asyncio.sleep(30)
                if self._persistence_dir:
                    await self._save_all_categories()
                    await self._save_theme()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[StateIsolation:{self.session_id}] Auto-save error: {e}")

    async def _load_json(self, filename: str) -> Optional[Dict]:
        if not self._persistence_dir:
            return None
        filepath = self._persistence_dir / filename
        if not filepath.exists():
            return None
        try:
            async with _aiofiles_open(filepath, 'r') as f:
                content = await f.read()
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.debug(f"[StateIsolation:{self.session_id}] JSON decode error in {filename}: {e}")
            return None
        except Exception as e:
            logger.debug(f"[StateIsolation:{self.session_id}] Load {filename} failed: {e}")
            return None

    async def _save_json(self, filename: str, data: Dict) -> None:
        if not self._persistence_dir:
            return
        filepath = self._persistence_dir / filename
        try:
            content = json.dumps(data, indent=2, default=str)
            async with _aiofiles_open(filepath, 'w') as f:
                await f.write(content)
        except Exception as e:
            logger.debug(f"[StateIsolation:{self.session_id}] Save {filename} failed: {e}")

    def get_memory_usage(self) -> int:
        try:
            return len(json.dumps(
                self._state.model_dump() if hasattr(self._state, 'model_dump') else {}
            ))
        except Exception:
            return 0


def _aiofiles_open(path, mode='r'):
    """Lazy aiofiles import to avoid startup cost."""
    import aiofiles
    return aiofiles.open(path, mode)
