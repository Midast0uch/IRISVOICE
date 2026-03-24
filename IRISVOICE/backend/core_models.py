"""
IRIS Backend Core Data Models
Core Pydantic models for type validation and serialization
These models have no dependencies on other backend modules to avoid circular imports
"""
from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator
import re


class Category(str, Enum):
    """Main category types matching the frontend hexagonal nodes"""
    VOICE = "voice"
    AGENT = "agent"
    AUTOMATE = "automate"
    SYSTEM = "system"
    CUSTOMIZE = "customize"
    MONITOR = "monitor"


class AppState(str, Enum):
    """Overall state of the IRIS application"""
    STARTING = "starting"
    LOADING_MODELS = "loading_models"
    READY = "ready"
    AWAKE = "awake"
    ASLEEP = "asleep"
    ERROR = "error"


class FieldType(str, Enum):
    """Input field types supported in cards"""
    TEXT = "text"
    SLIDER = "slider"
    DROPDOWN = "dropdown"
    TOGGLE = "toggle"
    COLOR = "color"
    KEY_COMBO = "keyCombo"
    # Extended types for frontend compatibility (mapped to base types with modifiers)
    PASSWORD = "password"  # Maps to TEXT with sensitive=True
    BUTTON = "button"      # Maps to TEXT with action trigger
    CUSTOM = "custom"      # Maps to TEXT as placeholder


# Type mapping documentation for frontend-backend compatibility
FIELD_TYPE_MAPPINGS = {
    # Frontend type -> (Backend type, Additional properties)
    "password": ("TEXT", {"sensitive": True}),
    "button": ("TEXT", {"is_action": True}),
    "custom": ("TEXT", {"is_placeholder": True}),
    # Base types pass through unchanged
    "text": ("TEXT", {}),
    "slider": ("SLIDER", {}),
    "dropdown": ("DROPDOWN", {}),
    "toggle": ("TOGGLE", {}),
    "color": ("COLOR", {}),
    "keyCombo": ("KEY_COMBO", {}),
}


class InputField(BaseModel):
    """Configuration for a single input field in a card"""
    id: str
    type: FieldType
    label: str
    value: Optional[Union[str, int, float, bool]] = None
    placeholder: Optional[str] = None
    options: Optional[List[str]] = None
    min: Optional[Union[int, float]] = None
    max: Optional[Union[int, float]] = None
    step: Optional[Union[int, float]] = None
    unit: Optional[str] = None
    # Extended type compatibility fields
    sensitive: Optional[bool] = None  # True for password fields
    is_action: Optional[bool] = None  # True for button fields
    action: Optional[str] = None      # Action identifier for button fields
    is_placeholder: Optional[bool] = None  # True for custom placeholder fields
    
    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if isinstance(v, str):
            return FieldType(v)
        return v
    
    def to_frontend_type(self) -> dict:
        """Convert to frontend-compatible type representation"""
        result = self.model_dump()
        # Map extended types back to frontend representation
        if self.type == FieldType.PASSWORD or self.sensitive:
            result['type'] = 'password'
        elif self.type == FieldType.BUTTON or self.is_action:
            result['type'] = 'button'
        elif self.type == FieldType.CUSTOM or self.is_placeholder:
            result['type'] = 'custom'
        else:
            result['type'] = self.type.value
        return result


class Section(BaseModel):
    """A section containing multiple input fields"""
    id: str
    label: str
    icon: str  # Icon name as string (Lucide icon name)
    fields: List[InputField]


class ColorTheme(BaseModel):
    """IRIS color theme configuration"""
    primary: str = Field(default="#00ff88", pattern=r'^#[0-9A-Fa-f]{6}$')
    glow: str = Field(default="#00ff88", pattern=r'^#[0-9A-Fa-f]{6}$')
    font: str = Field(default="#ffffff", pattern=r'^#[0-9A-Fa-f]{6}$')
    # State colors for voice-active UI
    state_colors_enabled: bool = Field(default=False)
    idle_color: str = Field(default="#00ff88", pattern=r'^#[0-9A-Fa-f]{6}$')
    listening_color: str = Field(default="#00aaff", pattern=r'^#[0-9A-Fa-f]{6}$')
    processing_color: str = Field(default="#a855f7", pattern=r'^#[0-9A-Fa-f]{6}$')
    error_color: str = Field(default="#ff3355", pattern=r'^#[0-9A-Fa-f]{6}$')
    
    @field_validator('primary', 'glow', 'font', 'idle_color', 'listening_color', 'processing_color', 'error_color')
    @classmethod
    def validate_hex_color(cls, v):
        if not re.match(r'^#[0-9A-Fa-f]{6}$', v):
            raise ValueError(f'Invalid hex color: {v}')
        return v.lower()


def _build_default_field_values() -> Dict[str, Dict[str, Any]]:
    """BUG-04 FIX: Build default field_values from SECTION_CONFIGS.

    Without this, IRISState starts with empty field_values={} and the
    frontend never receives any default values from the backend on initial_state.
    """
    defaults: Dict[str, Dict[str, Any]] = {}
    # SECTION_CONFIGS is defined later in this file but this function
    # is only called at runtime (as a default_factory), not at import time.
    for category_sections in SECTION_CONFIGS.values():
        for section in category_sections:
            section_defaults: Dict[str, Any] = {}
            for field in section.fields:
                if field.value is not None:
                    section_defaults[field.id] = field.value
            if section_defaults:
                defaults[section.id] = section_defaults
    return defaults


class IRISState(BaseModel):
    """Complete application state"""
    current_category: Optional[Category] = None
    current_section: Optional[str] = None
    field_values: Dict[str, Dict[str, Any]] = Field(default_factory=_build_default_field_values)
    
    class Config:
        populate_by_name = True
        extra = 'forbid'  # Reject any extra fields not defined in the model
    active_theme: ColorTheme = Field(default_factory=ColorTheme)
    app_state: AppState = Field(default=AppState.STARTING)
    
    # Model selection (user-configurable dual-LLM)
    selected_reasoning_model: Optional[str] = None
    selected_tool_execution_model: Optional[str] = None
    
    def get_category_values(self, category: str) -> Dict[str, Dict[str, Any]]:
        """Get all field values for a category (all sections)"""
        result = {}
        sections = get_sections_for_category(category)
        for section in sections:
            if section.id in self.field_values:
                result[section.id] = self.field_values[section.id]
        return result
    
    def set_field_value(self, section_id: str, field_id: str, value: Any):
        """Set a field value for a section"""
        if section_id not in self.field_values:
            self.field_values[section_id] = {}
        self.field_values[section_id][field_id] = value


# ============================================================================
# WebSocket Message Models
# ============================================================================

class ClientMessage(BaseModel):
    """Base model for messages from client to server"""
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class SelectCategoryMessage(BaseModel):
    """Client requests category switch"""
    type: str = "select_category"
    category: Category


class SelectSectionMessage(BaseModel):
    """Client activates a section"""
    type: str = "select_section"
    section_id: str


class FieldUpdateMessage(BaseModel):
    """Client updates a field value"""
    type: str = "field_update"
    section_id: str
    field_id: str
    value: Any


class ConfirmCardMessage(BaseModel):
    """Client confirms a card"""
    type: str = "confirm_card"
    section_id: str
    values: Dict[str, Any]


class UpdateThemeMessage(BaseModel):
    """Client updates theme colors"""
    type: str = "update_theme"
    glow_color: Optional[str] = None
    font_color: Optional[str] = None


class ServerMessage(BaseModel):
    """Base model for messages from server to client"""
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class InitialStateMessage(BaseModel):
    """Server sends full state on connection"""
    type: str = "initial_state"
    state: IRISState


class CategoryChangedMessage(BaseModel):
    """Server confirms category change"""
    type: str = "category_changed"
    category: Category
    sections: List[Section]


class FieldUpdatedMessage(BaseModel):
    """Server confirms field update"""
    type: str = "field_updated"
    section_id: str
    field_id: str
    value: Any
    valid: bool


class ValidationErrorMessage(BaseModel):
    """Server reports validation error"""
    type: str = "validation_error"
    field_id: str
    error: str


class CardConfirmedMessage(BaseModel):
    """Server confirms card and provides orbit position"""
    type: str = "card_confirmed"
    section_id: str
    orbit_angle: float


class WakeDetectedMessage(BaseModel):
    """Server notifies that wake word was detected"""
    type: str = "wake_detected"
    phrase: str
    confidence: float = 0.0


class ListeningStateMessage(BaseModel):
    """Server broadcasts current listening state"""
    type: str = "listening_state"
    state: str  # "idle", "listening", "processing", "speaking"


class BackendReadyMessage(BaseModel):
    """Server signals backend is ready"""
    type: str = "backend_ready"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ModelStatusMessage(BaseModel):
    """Server broadcasts the status of the LFM model."""
    type: str = "model_status"
    status: str  # e.g., "loading", "ready", "error"
    message: Optional[str] = None  # Optional message, e.g., for errors


def get_sections_for_category(category: str) -> List[Section]:
    """Get section configuration for a category"""
    return SECTION_CONFIGS.get(category, [])

SECTION_CONFIGS: Dict[str, List[Section]] = {
    "voice": [
        Section(
            id="input",
            label="INPUT",
            icon="Mic",
            fields=[
                InputField(id="input_device", type=FieldType.DROPDOWN, label="Input Device", options=["Default", "USB Microphone", "Headset", "Webcam"], value="Default"),
                InputField(id="input_sensitivity", type=FieldType.SLIDER, label="Input Sensitivity", min=0, max=100, value=50, unit="%"),
                InputField(id="noise_gate", type=FieldType.TOGGLE, label="Noise Gate", value=False),
                InputField(id="vad", type=FieldType.TOGGLE, label="VAD", value=True),
                InputField(id="auto_gain", type=FieldType.TOGGLE, label="Auto Gain", value=True),
            ]
        ),
        Section(
            id="output",
            label="OUTPUT",
            icon="Volume2",
            fields=[
                InputField(id="output_device", type=FieldType.DROPDOWN, label="Output Device", options=["Default", "Speakers", "Headphones"], value="Default"),
                InputField(id="master_volume", type=FieldType.SLIDER, label="Master Volume", min=0, max=100, value=80, unit="%"),
                InputField(id="enable_spatial", type=FieldType.TOGGLE, label="Enable Spatial", value=False),
                InputField(id="audio_ducking", type=FieldType.SLIDER, label="Audio Ducking", min=0, max=100, value=20, unit="%"),
                InputField(id="limiter", type=FieldType.TOGGLE, label="Limiter", value=True),
            ]
        ),
        Section(
            id="effects",
            label="EFFECTS",
            icon="Sparkles",
            fields=[
                InputField(id="reverb", type=FieldType.SLIDER, label="Reverb", min=0, max=100, value=10, unit="%"),
                InputField(id="equalizer", type=FieldType.DROPDOWN, label="Equalizer", options=["None", "Vocal Booster", "Clarity", "Bass Boost"], value="None"),
                InputField(id="compression", type=FieldType.SLIDER, label="Compression", min=0, max=100, value=30, unit="%"),
                InputField(id="stereo_width", type=FieldType.SLIDER, label="Stereo Width", min=0, max=100, value=50, unit="%"),
                InputField(id="pitch_shift", type=FieldType.SLIDER, label="Pitch Shift", min=-12, max=12, value=0, unit="st"),
            ]
        ),
    ],
    "agent": [
        Section(
            id="inference_mode",
            label="INFERENCE MODE",
            icon="Server",
            fields=[
                InputField(id="inference_mode", type=FieldType.DROPDOWN, label="Inference Mode", options=["Local Models", "VPS Gateway", "OpenAI API"], value="Local Models"),
                InputField(id="vps_url", type=FieldType.TEXT, label="VPS URL", placeholder="https://vps.example.com", value=""),
                InputField(id="vps_api_key", type=FieldType.TEXT, label="VPS API Key", placeholder="Enter API key", value=""),
                InputField(id="openai_api_key", type=FieldType.TEXT, label="OpenAI API Key", placeholder="sk-...", value=""),
            ]
        ),
        Section(
            id="model_selection",
            label="MODEL SELECTION",
            icon="BrainCircuit",
            fields=[
                InputField(id="reasoning_model", type=FieldType.DROPDOWN, label="Reasoning Model", options=[], value=""),
                InputField(id="tool_execution_model", type=FieldType.DROPDOWN, label="Tool Execution Model", options=[], value=""),
            ]
        ),
        Section(
            id="model",
            label="MODEL",
            icon="BrainCircuit",
            fields=[
                InputField(id="lfm_type", type=FieldType.DROPDOWN, label="LFM Type", options=["Local", "Cloud"], value="Local"),
                InputField(id="local_model_path", type=FieldType.TEXT, label="Local Model Path", placeholder="/path/to/model", value=""),
                InputField(id="cloud_api_key", type=FieldType.TEXT, label="Cloud API Key", placeholder="sk-...", value=""),
                InputField(id="temperature", type=FieldType.SLIDER, label="Temperature", min=0, max=2, value=0.8, step=0.1),
                InputField(id="max_tokens", type=FieldType.SLIDER, label="Max Tokens", min=64, max=4096, value=1024),
            ]
        ),
        Section(
            id="wake",
            label="WAKE",
            icon="Power",
            fields=[
                InputField(id="wake_word_enabled", type=FieldType.TOGGLE, label="Wake Word Enabled", value=True),
                InputField(id="wake_phrase", type=FieldType.DROPDOWN, label="Wake Phrase", options=["Jarvis", "Computer", "Bumblebee", "Porcupine"], value="Jarvis"),
                InputField(id="detection_sensitivity", type=FieldType.SLIDER, label="Detection Sensitivity", min=0, max=100, value=70, unit="%"),
                InputField(id="activation_sound", type=FieldType.TOGGLE, label="Activation Sound", value=True),
                InputField(id="sleep_timeout", type=FieldType.SLIDER, label="Sleep Timeout", min=5, max=300, value=60, unit="s"),
            ]
        ),
        Section(
            id="speech",
            label="SPEECH",
            icon="MessageSquare",
            fields=[
                InputField(id="auto_start_speak", type=FieldType.TOGGLE, label="Auto-start Speak", value=True),
                InputField(id="voice_style", type=FieldType.DROPDOWN, label="Voice Style", options=["Professional", "Friendly", "Expressive"], value="Friendly"),
                InputField(id="speaking_rate", type=FieldType.SLIDER, label="Speaking Rate", min=0.5, max=2, value=1, step=0.1),
                InputField(id="pitch", type=FieldType.SLIDER, label="Pitch", min=-10, max=10, value=0, step=1),
                InputField(id="intonation", type=FieldType.SLIDER, label="Intonation", min=0, max=100, value=50, unit="%"),
            ]
        ),
        # BUG-03 FIX: Add sections that frontend expects but backend was missing
        Section(
            id="identity",
            label="IDENTITY",
            icon="User",
            fields=[
                InputField(id="agent_name", type=FieldType.TEXT, label="Agent Name", placeholder="Enter agent name...", value="Iris"),
                InputField(id="persona", type=FieldType.DROPDOWN, label="Persona", options=["Professional", "Friendly", "Concise", "Creative", "Technical"], value="Friendly"),
                InputField(id="greeting_message", type=FieldType.TEXT, label="Greeting Message", placeholder="Hello! How can I help you?", value="Hello! How can I help you?"),
            ]
        ),
        Section(
            id="memory",
            label="MEMORY",
            icon="Database",
            fields=[
                InputField(id="memory_enabled", type=FieldType.TOGGLE, label="Memory Enabled", value=True),
                InputField(id="context_window", type=FieldType.SLIDER, label="Context Window", min=5, max=50, value=10),
                InputField(id="memory_persistence", type=FieldType.TOGGLE, label="Save Conversations", value=True),
            ]
        ),
    ],
    "automate": [
        Section(
            id="hotkeys",
            label="HOTKEYS",
            icon="Keyboard",
            fields=[
                InputField(id="push_to_talk", type=FieldType.KEY_COMBO, label="Push-to-Talk", value=""),
                InputField(id="toggle_mute", type=FieldType.KEY_COMBO, label="Toggle Mute", value=""),
                InputField(id="quick_command", type=FieldType.KEY_COMBO, label="Quick Command", value=""),
                InputField(id="replay_last", type=FieldType.KEY_COMBO, label="Replay Last", value=""),
                InputField(id="toggle_iris_panel", type=FieldType.KEY_COMBO, label="Toggle IRIS Panel", value=""),
            ]
        ),
        Section(
            id="macros",
            label="MACROS",
            icon="Bot",
            fields=[
                InputField(id="macro_1_trigger", type=FieldType.TEXT, label="Macro 1 Trigger", placeholder="e.g., 'run diagnostics'", value=""),
                InputField(id="macro_1_action", type=FieldType.TEXT, label="Macro 1 Action", placeholder="e.g., 'run health check'", value=""),
                InputField(id="macro_2_trigger", type=FieldType.TEXT, label="Macro 2 Trigger", placeholder="e.g., 'start stream'", value=""),
                InputField(id="macro_2_action", type=FieldType.TEXT, label="Macro 2 Action", placeholder="e.g., 'open obs and start stream'", value=""),
                InputField(id="macro_3_trigger", type=FieldType.TEXT, label="Macro 3 Trigger", placeholder="e.g., 'good night'", value=""),
            ]
        ),
        Section(
            id="integrations",
            label="INTEGRATIONS",
            icon="Puzzle",
            fields=[
                InputField(id="discord_token", type=FieldType.TEXT, label="Discord Token", placeholder="...", value=""),
                InputField(id="obs_websocket_url", type=FieldType.TEXT, label="OBS WebSocket URL", placeholder="ws://localhost:4444", value=""),
                InputField(id="philips_hue_bridge_ip", type=FieldType.TEXT, label="Philips Hue Bridge IP", placeholder="192.168.1.x", value=""),
                InputField(id="spotify_client_id", type=FieldType.TEXT, label="Spotify Client ID", placeholder="...", value=""),
                InputField(id="home_assistant_url", type=FieldType.TEXT, label="Home Assistant URL", placeholder="http://homeassistant.local:8123", value=""),
            ]
        ),
        # BUG-03 FIX: Add sections that frontend expects but backend was missing
        Section(
            id="tools",
            label="TOOLS",
            icon="Wrench",
            fields=[
                InputField(id="allowed_tools", type=FieldType.DROPDOWN, label="Allowed Tools", options=["All", "None", "Custom"], value="All"),
                InputField(id="tool_confirmations", type=FieldType.TOGGLE, label="Require Confirmations", value=True),
            ]
        ),
        Section(
            id="vision",
            label="VISION",
            icon="Eye",
            fields=[
                InputField(id="vision_enabled", type=FieldType.TOGGLE, label="Vision Enabled", value=False),
                InputField(id="vision_model", type=FieldType.DROPDOWN, label="Vision Model", options=["minicpm-o4.5", "llava", "bakllava"], value="minicpm-o4.5"),
            ]
        ),
        Section(
            id="desktop_control",
            label="DESKTOP CONTROL",
            icon="Monitor",
            fields=[
                InputField(id="desktop_control_enabled", type=FieldType.TOGGLE, label="Desktop Control Enabled", value=False),
                InputField(id="ui_tars_provider", type=FieldType.DROPDOWN, label="UI-TARS Provider", options=["cli_npx", "native_python", "api_cloud"], value="native_python"),
                InputField(id="vision_model_provider", type=FieldType.DROPDOWN, label="Vision Model", options=["minicpm_ollama", "anthropic", "volcengine", "local"], value="minicpm_ollama"),
                InputField(id="api_key", type=FieldType.TEXT, label="API Key", placeholder="sk-...", value=""),
                InputField(id="max_steps", type=FieldType.SLIDER, label="Max Automation Steps", min=5, max=50, value=25),
                InputField(id="require_confirmation", type=FieldType.TOGGLE, label="Require Confirmation", value=True),
                InputField(id="use_vision_guidance", type=FieldType.TOGGLE, label="Use Vision Guidance", value=True),
            ]
        ),
        Section(
            id="skills",
            label="SKILLS",
            icon="Sparkles",
            fields=[
                InputField(id="skill_creation_enabled", type=FieldType.TOGGLE, label="Allow Agent to Create Skills", value=True),
            ]
        ),
        Section(
            id="profile",
            label="PROFILE",
            icon="User",
            fields=[
                InputField(id="active_mode", type=FieldType.DROPDOWN, label="Active Mode", options=["default", "work", "personal", "focus"], value="default"),
            ]
        ),
    ],
    "system": [
        Section(
            id="performance",
            label="PERFORMANCE",
            icon="Gauge",
            fields=[
                InputField(id="enable_gpu", type=FieldType.TOGGLE, label="Enable GPU", value=True),
                InputField(id="cpu_cores", type=FieldType.SLIDER, label="CPU Cores", min=1, max=16, value=4, step=1),
                InputField(id="ram_allocation", type=FieldType.SLIDER, label="RAM Allocation", min=1, max=16, value=4, unit="GB"),
                InputField(id="model_offload", type=FieldType.SLIDER, label="Model Offload", min=0, max=100, value=50, unit="%"),
                InputField(id="low_power_mode", type=FieldType.TOGGLE, label="Low Power Mode", value=False),
            ]
        ),
        Section(
            id="storage",
            label="STORAGE",
            icon="Database",
            fields=[
                InputField(id="log_retention_days", type=FieldType.SLIDER, label="Log Retention (days)", min=1, max=30, value=7, step=1),
                InputField(id="max_log_size_mb", type=FieldType.SLIDER, label="Max Log Size (MB)", min=10, max=500, value=100, step=10),
                InputField(id="session_history_path", type=FieldType.TEXT, label="Session History Path", placeholder="/path/to/history", value=""),
                InputField(id="clear_cache", type=FieldType.TEXT, label="Clear Cache", placeholder="Clear", value=""),
                InputField(id="backup_settings", type=FieldType.TEXT, label="Backup Settings", placeholder="Backup", value=""),
            ]
        ),
        Section(
            id="security",
            label="SECURITY",
            icon="Shield",
            fields=[
                InputField(id="enable_sandboxing", type=FieldType.TOGGLE, label="Enable Sandboxing", value=True),
                InputField(id="data_encryption", type=FieldType.TOGGLE, label="Data Encryption", value=True),
                InputField(id="audit_log_level", type=FieldType.DROPDOWN, label="Audit Log Level", options=["None", "Basic", "Full"], value="Basic"),
                InputField(id="allow_external_requests", type=FieldType.TOGGLE, label="Allow External Requests", value=False),
                InputField(id="two_factor_auth", type=FieldType.TOGGLE, label="Two-Factor Auth", value=False),
            ]
        ),
        # BUG-03 FIX: Add sections that frontend expects but backend was missing
        Section(
            id="power",
            label="POWER",
            icon="Power",
            fields=[
                InputField(id="auto_start", type=FieldType.TOGGLE, label="Auto Start on Boot", value=False),
                InputField(id="minimize_to_tray", type=FieldType.TOGGLE, label="Minimize to Tray", value=True),
            ]
        ),
        Section(
            id="display",
            label="DISPLAY",
            icon="Monitor",
            fields=[
                InputField(id="window_opacity", type=FieldType.SLIDER, label="Window Opacity", min=20, max=100, value=95, unit="%"),
                InputField(id="always_on_top", type=FieldType.TOGGLE, label="Always on Top", value=False),
            ]
        ),
        Section(
            id="network",
            label="NETWORK",
            icon="Wifi",
            fields=[
                InputField(id="websocket_url", type=FieldType.TEXT, label="WebSocket URL", placeholder="ws://localhost:8000/ws", value="ws://localhost:8000/ws"),
                InputField(id="connection_timeout", type=FieldType.SLIDER, label="Timeout", min=5, max=60, value=30, unit="s"),
            ]
        ),
    ],
    "customize": [
        Section(
            id="theme",
            label="THEME",
            icon="Palette",
            fields=[
                InputField(id="primary_color", type=FieldType.COLOR, label="Primary Color", value="#00ff88"),
                InputField(id="glow_color", type=FieldType.COLOR, label="Glow Color", value="#00ff88"),
                InputField(id="font_color", type=FieldType.COLOR, label="Font Color", value="#ffffff"),
                InputField(id="layout_mode", type=FieldType.DROPDOWN, label="Layout Mode", options=["Compact", "Spacious", "Minimal"], value="Spacious"),
                InputField(id="font_size", type=FieldType.SLIDER, label="Font Size", min=8, max=24, value=14, unit="px"),
            ]
        ),
        Section(
            id="ui",
            label="UI",
            icon="PanelsTopLeft",
            fields=[
                InputField(id="show_tooltips", type=FieldType.TOGGLE, label="Show Tooltips", value=True),
                InputField(id="animation_speed", type=FieldType.SLIDER, label="Animation Speed", min=0, max=2, value=1, step=0.1),
                InputField(id="blur_intensity", type=FieldType.SLIDER, label="Blur Intensity", min=0, max=100, value=20, unit="%"),
                InputField(id="hide_on_startup", type=FieldType.TOGGLE, label="Hide on Startup", value=False),
                InputField(id="always_on_top", type=FieldType.TOGGLE, label="Always on Top", value=False),
            ]
        ),
        Section(
            id="notifications",
            label="NOTIFICATIONS",
            icon="Bell",
            fields=[
                InputField(id="enable_notifications", type=FieldType.TOGGLE, label="Enable Notifications", value=True),
                InputField(id="notification_sound", type=FieldType.DROPDOWN, label="Notification Sound", options=["Default", "Subtle", "Chime", "None"], value="Default"),
                InputField(id="show_wake_notification", type=FieldType.TOGGLE, label="Show Wake Notification", value=True),
                InputField(id="show_error_notification", type=FieldType.TOGGLE, label="Show Error Notification", value=True),
                InputField(id="auto_dismiss_delay", type=FieldType.SLIDER, label="Auto-Dismiss Delay", min=1, max=10, value=5, unit="s"),
            ]
        ),
        # BUG-03 FIX: Add sections that frontend expects but backend was missing
        Section(
            id="startup",
            label="STARTUP",
            icon="Rocket",
            fields=[
                InputField(id="startup_page", type=FieldType.DROPDOWN, label="Startup Page", options=["Dashboard", "Chat", "Settings"], value="Dashboard"),
                InputField(id="startup_behavior", type=FieldType.DROPDOWN, label="Startup Behavior", options=["Normal", "Minimized", "Fullscreen"], value="Normal"),
            ]
        ),
        Section(
            id="behavior",
            label="BEHAVIOR",
            icon="Sliders",
            fields=[
                InputField(id="confirm_exit", type=FieldType.TOGGLE, label="Confirm on Exit", value=True),
                InputField(id="auto_save", type=FieldType.TOGGLE, label="Auto Save", value=True),
            ]
        ),
    ],
    "monitor": [
        # BUG-03 FIX: Add analytics section that frontend expects
        Section(
            id="analytics",
            label="ANALYTICS",
            icon="BarChart3",
            fields=[
                InputField(id="view_analytics", type=FieldType.TEXT, label="View Analytics", placeholder="View", value=""),
                InputField(id="export_report", type=FieldType.TEXT, label="Export Report", placeholder="Export", value=""),
            ]
        ),
        Section(
            id="metrics",
            label="METRICS",
            icon="LineChart",
            fields=[
                InputField(id="token_usage", type=FieldType.TEXT, label="Token Usage", placeholder="Usage", value=""),
                InputField(id="response_latency", type=FieldType.TEXT, label="Response Latency", placeholder="Latency", value=""),
                InputField(id="session_duration", type=FieldType.TEXT, label="Session Duration", placeholder="Duration", value=""),
                InputField(id="command_history", type=FieldType.TEXT, label="Command History", placeholder="History", value=""),
                InputField(id="cost_estimate", type=FieldType.TEXT, label="Cost Estimate", placeholder="Cost", value=""),
            ]
        ),
        Section(
            id="logs",
            label="LOGS",
            icon="FileText",
            fields=[
                InputField(id="system_logs", type=FieldType.TEXT, label="System Logs", placeholder="System", value=""),
                InputField(id="voice_logs", type=FieldType.TEXT, label="Voice Logs", placeholder="Voice", value=""),
                InputField(id="mcp_logs", type=FieldType.TEXT, label="MCP Logs", placeholder="MCP", value=""),
                InputField(id="error_logs", type=FieldType.TEXT, label="Error Logs", placeholder="Errors", value=""),
                InputField(id="export_logs", type=FieldType.TEXT, label="Export Logs", placeholder="Export", value=""),
            ]
        ),
        Section(
            id="diagnostics",
            label="DIAGNOSTICS",
            icon="Stethoscope",
            fields=[
                InputField(id="health_check", type=FieldType.TEXT, label="Health Check", placeholder="Run", value=""),
                InputField(id="lfm_benchmark", type=FieldType.TEXT, label="LFM Benchmark", placeholder="Benchmark", value=""),
                InputField(id="mcp_test", type=FieldType.TEXT, label="MCP Test", placeholder="Test MCP", value=""),
                InputField(id="network_test", type=FieldType.TEXT, label="Network Test", placeholder="Test Network", value=""),
                InputField(id="report_issue", type=FieldType.TEXT, label="Report Issue", placeholder="Report", value=""),
            ]
        ),
        Section(
            id="updates",
            label="UPDATES",
            icon="RefreshCw",
            fields=[
                InputField(id="update_channel", type=FieldType.DROPDOWN, label="Update Channel", options=["Stable", "Beta", "Nightly"], value="Stable"),
                InputField(id="check_updates", type=FieldType.TEXT, label="Check Updates", placeholder="Check", value=""),
                InputField(id="current_version", type=FieldType.TEXT, label="Current Version", placeholder="v0.0.0", value=""),
                InputField(id="changelog", type=FieldType.TEXT, label="Changelog", placeholder="View", value=""),
                InputField(id="auto_update", type=FieldType.TOGGLE, label="Auto Update", value=True),
            ]
        ),
    ],
}


# ---------------------------------------------------------------------------
# DER Loop execution models (Gate 1 Step 1.7)
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    """Status of a single plan step in the DER execution loop."""
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"
    BLOCKED   = "blocked"


@dataclass
class PlanStep:
    """
    One step in the Director's ExecutionPlan.
    Richer than QueueItem — carries execution state and results.
    """
    step_id: str
    step_number: int
    description: str
    status: StepStatus              = StepStatus.PENDING
    tool: Optional[str]             = None
    params: Dict[str, Any]          = dc_field(default_factory=dict)
    depends_on: List[str]           = dc_field(default_factory=list)
    critical: bool                  = True
    required_permission: Optional[str] = None
    result: Any                     = None
    failure_reason: Optional[str]   = None
    duration_ms: int                = 0
    expected_output: Optional[str]  = None


@dataclass
class ExecutionPlan:
    """
    The Director's complete execution plan.
    Initialized from _plan_task(), consumed by _execute_plan_der().
    """
    plan_id: str
    original_task: str
    strategy: str
    reasoning: str
    steps: List[PlanStep]           = dc_field(default_factory=list)
    outcome: str                    = "success"

    def has_failed(self) -> bool:
        return self.outcome == "failure"

    def to_context_string(self) -> str:
        """
        Serialize plan as HZA-formatted string for model context injection.
        Uses ASCII markers only — never Unicode (encoding errors on Windows).
        [+] = completed, [x] = failed, [~] = running, [ ] = pending/other
        """
        hza = self.plan_id[:8]
        lines = [
            f"[system://plan/{hza}]",
            f"Task: {self.original_task}",
            f"Strategy: {self.strategy}",
            f"Steps: {len(self.steps)}",
        ]
        for step in self.steps:
            if step.status == StepStatus.COMPLETED:
                marker = "[+]"
            elif step.status == StepStatus.FAILED:
                marker = "[x]"
            elif step.status == StepStatus.RUNNING:
                marker = "[~]"
            else:
                marker = "[ ]"
            lines.append(f"[system://plan/{hza}/step/{step.step_id}]")
            lines.append(f"  {marker} Step {step.step_number}: {step.description}")
            if step.result:
                lines.append(f"      Result: {str(step.result)[:100]}")
            if step.failure_reason:
                lines.append(f"      Failed: {step.failure_reason}")
        return "\n".join(lines)
