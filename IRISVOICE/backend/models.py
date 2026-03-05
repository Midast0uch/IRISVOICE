"""
IRIS Backend Data Models
Pydantic models for type validation and serialization
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator
import re

from .core_models import AppState




class Category(str, Enum):
    """Main category types matching the frontend hexagonal nodes"""
    VOICE = "voice"
    AGENT = "agent"
    AUTOMATE = "automate"
    SYSTEM = "system"
    CUSTOMIZE = "customize"
    MONITOR = "monitor"


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
    """A sub-node containing multiple input fields"""
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


class IRISState(BaseModel):
    """Complete application state"""
    current_category: Optional[Category] = None
    current_section: Optional[str] = None
    field_values: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    
    class Config:
        populate_by_name = True
        extra = 'forbid'  # Reject any extra fields not defined in the model
    active_theme: ColorTheme = Field(default_factory=ColorTheme)
    app_state: AppState = Field(default=AppState.STARTING)
    
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


# ============================================================================
# Section Configurations (mirrors frontend sections)
# ============================================================================

SECTION_CONFIGS: Dict[str, List[Section]] = {
    "voice": [
        Section(
            id="input",
            label="INPUT",
            icon="Mic",
            fields=[
                InputField(id="input_device", type=FieldType.DROPDOWN, label="Input Device", options=["Default", "USB Microphone", "Headset", "Webcam"], value="Default"),
                InputField(id="input_volume", type=FieldType.SLIDER, label="Input Volume", min=0, max=100, value=50, unit="%"),
                InputField(id="noise_gate", type=FieldType.TOGGLE, label="Noise Gate", value=False),
                InputField(id="vad", type=FieldType.TOGGLE, label="VAD", value=True),
                InputField(id="input_test", type=FieldType.TEXT, label="Input Test", placeholder="Test microphone", value=""),
            ]
        ),
        Section(
            id="output",
            label="OUTPUT",
            icon="Volume2",
            fields=[
                InputField(id="output_device", type=FieldType.DROPDOWN, label="Output Device", options=["Default", "Headphones", "Speakers", "HDMI"], value="Default"),
                InputField(id="output_volume", type=FieldType.SLIDER, label="Output Volume", min=0, max=100, value=70, unit="%"),
                InputField(id="output_test", type=FieldType.TEXT, label="Output Test", placeholder="Test audio", value=""),
                InputField(id="latency_compensation", type=FieldType.SLIDER, label="Latency Compensation", min=0, max=500, value=0, unit="ms"),
            ]
        ),
    ],
    "agent": [
        Section(
            id="model_selection",
            label="MODEL SELECTION",
            icon="Brain",
            fields=[
                InputField(id="model_provider", type=FieldType.DROPDOWN, label="Provider", options=["local", "api", "vps"], value="local"),
                InputField(id="use_same_model", type=FieldType.TOGGLE, label="Use Same Model for Both", value=True),
                InputField(id="reasoning_model", type=FieldType.DROPDOWN, label="Reasoning Model", options=[], value=""),
                InputField(id="tool_model", type=FieldType.DROPDOWN, label="Tool Model", options=[], value=""),
                InputField(id="api_key", type=FieldType.TEXT, label="API Key", placeholder="sk-...", value=""),
                InputField(id="vps_endpoint", type=FieldType.TEXT, label="VPS Endpoint", placeholder="http://vps.example.com", value=""),
            ]
        ),
        Section(
            id="inference_mode",
            label="INFERENCE MODE",
            icon="Cpu",
            fields=[
                InputField(id="agent_thinking_style", type=FieldType.DROPDOWN, label="Agent Thinking Style", options=["concise", "balanced", "thorough"], value="balanced"),
                InputField(id="max_response_length", type=FieldType.DROPDOWN, label="Max Response Length", options=["short", "medium", "long"], value="medium"),
                InputField(id="reasoning_effort", type=FieldType.DROPDOWN, label="Reasoning Effort", options=["fast", "balanced", "accurate"], value="balanced"),
                InputField(id="tool_mode", type=FieldType.DROPDOWN, label="Tool Mode", options=["auto", "ask_first", "disabled"], value="auto"),
            ]
        ),
        Section(
            id="identity",
            label="IDENTITY",
            icon="Smile",
            fields=[
                InputField(id="agent_name", type=FieldType.TEXT, label="Agent Name", placeholder="IRIS", value="IRIS"),
                InputField(id="persona", type=FieldType.DROPDOWN, label="Persona", options=["Professional", "Friendly", "Concise", "Creative", "Technical"], value="Friendly"),
                InputField(id="knowledge", type=FieldType.DROPDOWN, label="Knowledge Focus", options=["General", "Coding", "Writing", "Research", "Conversation"], value="General"),
                InputField(id="response_length", type=FieldType.DROPDOWN, label="Response Length", options=["Brief", "Balanced", "Detailed", "Comprehensive"], value="Balanced"),
            ]
        ),
        Section(
            id="wake",
            label="WAKE",
            icon="Sparkles",
            fields=[
                InputField(id="wake_word_enabled", type=FieldType.TOGGLE, label="Wake Word Enabled", value=True),

# ... (rest of the file)

# In SECTION_CONFIGS["agent"][1] for the 'wake' section:
                InputField(
                    id="wake_phrase",
                    type=FieldType.DROPDOWN,
                    label="Wake Phrase",
                    # Options MUST be valid pvporcupine built-in keyword strings.
                    # These map directly to pre-trained .ppn files shipped inside the pvporcupine package.
                    # Custom phrases (e.g. "Hey IRIS") require a trained .ppn file from console.picovoice.ai
                    # and must be loaded via keyword_paths=[], not keywords=[].
                    # Run: python -c "import pvporcupine; print(pvporcupine.KEYWORDS)" to see all valid options.
                    options=["jarvis", "hey computer", "computer", "bumblebee", "porcupine"],
                    value="jarvis"  # Default — well-known, no trademark issues, reliable detection
                ),
                InputField(id="wake_word_sensitivity", type=FieldType.SLIDER, label="Wake Word Sensitivity", min=1, max=10, value=5),
                InputField(id="voice_profile", type=FieldType.DROPDOWN, label="Voice Profile", options=["Default", "Personal", "Professional"], value="Default"),
                InputField(id="activation_sound", type=FieldType.TOGGLE, label="Activation Sound", value=True),
                InputField(id="sleep_timeout", type=FieldType.SLIDER, label="Sleep Timeout", min=5, max=300, value=60, unit="s"),
            ]
        ),
        Section(
            id="speech",
            label="SPEECH",
            icon="MessageSquare",
            fields=[
                InputField(id="tts_enabled", type=FieldType.TOGGLE, label="TTS Enabled", value=True),
                InputField(id="tts_voice", type=FieldType.DROPDOWN, label="TTS Voice", options=["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"], value="Nova"),
                InputField(id="speaking_rate", type=FieldType.SLIDER, label="Speaking Rate", min=0.5, max=2, step=0.1, value=1.0, unit="x"),
                InputField(id="pitch_adjustment", type=FieldType.SLIDER, label="Pitch Adjustment", min=-20, max=20, value=0, unit="semitones"),
                InputField(id="pause_duration", type=FieldType.SLIDER, label="Pause Duration", min=0, max=2, step=0.1, value=0.2, unit="s"),
                InputField(id="voice_cloning", type=FieldType.TEXT, label="Voice Cloning", placeholder="Upload audio path", value=""),
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
            id="tools",
            label="TOOLS",
            icon="Wrench",
            fields=[
                InputField(id="active_servers", type=FieldType.TEXT, label="Active Servers", placeholder="Server status", value=""),
                InputField(id="tool_browser", type=FieldType.TEXT, label="Tool Browser", placeholder="Browse tools", value=""),
                InputField(id="quick_actions", type=FieldType.TEXT, label="Quick Actions", placeholder="Recent tools", value=""),
                InputField(id="tool_categories", type=FieldType.TEXT, label="Tool Categories", placeholder="Filter", value=""),
            ]
        ),
        Section(
            id="skills",
            label="SKILLS",
            icon="Sparkles",
            fields=[
                InputField(id="skill_creation_enabled", type=FieldType.TOGGLE, label="Allow Agent to Create Skills", value=True),
                InputField(id="skills_list", type=FieldType.TEXT, label="Learned Skills", placeholder="No skills learned yet", value=""),
            ]
        ),
        Section(
            id="profile",
            label="PROFILE",
            icon="User",
            fields=[
                InputField(id="user_profile_display", type=FieldType.TEXT, label="Your Profile", placeholder="Default Profile", value=""),
                InputField(id="active_mode", type=FieldType.DROPDOWN, label="Active Mode", options=["default", "work", "personal", "focus"], value="default"),
                InputField(id="modes_list", type=FieldType.TEXT, label="Your Modes", placeholder="No custom modes", value=""),
            ]
        ),
        Section(
            id="vision",
            label="VISION",
            icon="Eye",
            fields=[
                InputField(id="vision_enabled", type=FieldType.TOGGLE, label="Vision Enabled", value=False),
                InputField(id="screen_context", type=FieldType.TOGGLE, label="Screen Context in Chat", value=True),
                InputField(id="proactive_monitor", type=FieldType.TOGGLE, label="Proactive Monitor", value=False),
                InputField(id="monitor_interval", type=FieldType.SLIDER, label="Monitor Interval", min=5, max=120, value=30, unit="s"),
                InputField(id="ollama_endpoint", type=FieldType.TEXT, label="Ollama Endpoint", placeholder="http://localhost:11434", value="http://localhost:11434"),
                InputField(id="vision_model", type=FieldType.DROPDOWN, label="Vision Model", options=["minicpm-o4.5", "llava", "bakllava"], value="minicpm-o4.5"),
            ]
        ),
        Section(
            id="desktop_control",
            label="DESKTOP CONTROL",
            icon="Monitor",
            fields=[
                InputField(id="ui_tars_provider", type=FieldType.DROPDOWN, label="UI-TARS Provider", options=["cli_npx", "native_python", "api_cloud"], value="native_python"),
                InputField(id="model_provider", type=FieldType.DROPDOWN, label="Vision Model", options=["minicpm_ollama", "anthropic", "volcengine", "local"], value="minicpm_ollama"),
                InputField(id="vision_settings", type=FieldType.TEXT, label="Vision Settings", placeholder="Configure vision", value=""),
                InputField(id="automation_rules", type=FieldType.TEXT, label="Automation Rules", placeholder="Rules", value=""),
            ]
        ),
        Section(
            id="extensions",
            label="EXTENSIONS",
            icon="Puzzle",
            fields=[
                InputField(id="mcp_servers", type=FieldType.TEXT, label="MCP Servers", placeholder="Configure servers", value=""),
                InputField(id="extension_browser", type=FieldType.TEXT, label="Extension Browser", placeholder="Browse extensions", value=""),
                InputField(id="installed_extensions", type=FieldType.TEXT, label="Installed", placeholder="Installed extensions", value=""),
            ]
        ),
    ],
    "system": [
        Section(
            id="power",
            label="POWER",
            icon="Power",
            fields=[
                InputField(id="startup_launch", type=FieldType.TOGGLE, label="Launch on Startup", value=True),
                InputField(id="background_mode", type=FieldType.TOGGLE, label="Background Mode", value=True),
                InputField(id="power_save", type=FieldType.TOGGLE, label="Power Save Mode", value=False),
            ]
        ),
        Section(
            id="display",
            label="DISPLAY",
            icon="Monitor",
            fields=[
                InputField(id="theme", type=FieldType.DROPDOWN, label="Theme", options=["dark", "light", "auto"], value="dark"),
                InputField(id="accent_color", type=FieldType.COLOR, label="Accent Color", value="#00ff88"),
                InputField(id="window_opacity", type=FieldType.SLIDER, label="Window Opacity", min=50, max=100, value=95, unit="%"),
                InputField(id="font_size", type=FieldType.DROPDOWN, label="Font Size", options=["small", "medium", "large"], value="medium"),
            ]
        ),
        Section(
            id="storage",
            label="STORAGE",
            icon="HardDrive",
            fields=[
                InputField(id="data_location", type=FieldType.TEXT, label="Data Location", placeholder="~/.iris", value="~/.iris"),
                InputField(id="auto_cleanup", type=FieldType.TOGGLE, label="Auto Cleanup", value=True),
                InputField(id="retention_days", type=FieldType.SLIDER, label="Retention (days)", min=7, max=365, value=30, unit="d"),
            ]
        ),
        Section(
            id="network",
            label="NETWORK",
            icon="Wifi",
            fields=[
                InputField(id="offline_mode", type=FieldType.TOGGLE, label="Offline Mode", value=False),
                InputField(id="proxy_settings", type=FieldType.TEXT, label="Proxy", placeholder="http://proxy:8080", value=""),
                InputField(id="bandwidth_limit", type=FieldType.SLIDER, label="Bandwidth Limit", min=0, max=100, value=0, unit="Mbps"),
            ]
        ),
    ],
    "customize": [
        Section(
            id="theme",
            label="THEME",
            icon="Palette",
            fields=[
                InputField(id="glow_color", type=FieldType.COLOR, label="Glow Color", value="#00ff88"),
                InputField(id="font_color", type=FieldType.COLOR, label="Font Color", value="#ffffff"),
                InputField(id="state_colors_enabled", type=FieldType.TOGGLE, label="Enable State Colors", value=False),
                InputField(id="idle_color", type=FieldType.COLOR, label="Idle Color", value="#00ff88"),
                InputField(id="listening_color", type=FieldType.COLOR, label="Listening Color", value="#00aaff"),
                InputField(id="processing_color", type=FieldType.COLOR, label="Processing Color", value="#a855f7"),
                InputField(id="error_color", type=FieldType.COLOR, label="Error Color", value="#ff3355"),
            ]
        ),
        Section(
            id="startup",
            label="STARTUP",
            icon="Rocket",
            fields=[
                InputField(id="welcome_message", type=FieldType.TEXT, label="Welcome Message", placeholder="Welcome to IRIS", value="Welcome to IRIS"),
                InputField(id="startup_sound", type=FieldType.TOGGLE, label="Startup Sound", value=True),
                InputField(id="initial_mode", type=FieldType.DROPDOWN, label="Initial Mode", options=["voice", "chat", "idle"], value="voice"),
            ]
        ),
        Section(
            id="behavior",
            label="BEHAVIOR",
            icon="Sliders",
            fields=[
                InputField(id="auto_listen", type=FieldType.TOGGLE, label="Auto Listen", value=False),
                InputField(id="conversation_mode", type=FieldType.TOGGLE, label="Conversation Mode", value=True),
                InputField(id="interruptible", type=FieldType.TOGGLE, label="Allow Interrupt", value=True),
            ]
        ),
        Section(
            id="notifications",
            label="NOTIFICATIONS",
            icon="Bell",
            fields=[
                InputField(id="desktop_notifications", type=FieldType.TOGGLE, label="Desktop Notifications", value=True),
                InputField(id="sound_alerts", type=FieldType.TOGGLE, label="Sound Alerts", value=True),
                InputField(id="do_not_disturb", type=FieldType.TOGGLE, label="Do Not Disturb", value=False),
            ]
        ),
    ],
    "monitor": [
        Section(
            id="analytics",
            label="ANALYTICS",
            icon="BarChart3",
            fields=[
                InputField(id="usage_stats", type=FieldType.TEXT, label="Usage Stats", placeholder="View stats", value=""),
                InputField(id="performance_metrics", type=FieldType.TEXT, label="Performance", placeholder="View metrics", value=""),
                InputField(id="export_data", type=FieldType.TEXT, label="Export", placeholder="Export data", value=""),
            ]
        ),
        Section(
            id="logs",
            label="LOGS",
            icon="FileText",
            fields=[
                InputField(id="system_logs", type=FieldType.TEXT, label="System Logs", placeholder="View logs", value=""),
                InputField(id="error_logs", type=FieldType.TEXT, label="Error Logs", placeholder="View errors", value=""),
                InputField(id="log_level", type=FieldType.DROPDOWN, label="Log Level", options=["debug", "info", "warn", "error"], value="info"),
            ]
        ),
        Section(
            id="diagnostics",
            label="DIAGNOSTICS",
            icon="Stethoscope",
            fields=[
                InputField(id="system_health", type=FieldType.TEXT, label="System Health", placeholder="Check health", value=""),
                InputField(id="troubleshoot", type=FieldType.TEXT, label="Troubleshoot", placeholder="Run diagnostics", value=""),
                InputField(id="debug_info", type=FieldType.TEXT, label="Debug Info", placeholder="View debug info", value=""),
            ]
        ),
        Section(
            id="updates",
            label="UPDATES",
            icon="RefreshCw",
            fields=[
                InputField(id="check_updates", type=FieldType.TEXT, label="Check Updates", placeholder="Check for updates", value=""),
                InputField(id="auto_update", type=FieldType.TOGGLE, label="Auto Update", value=True),
                InputField(id="release_channel", type=FieldType.DROPDOWN, label="Channel", options=["stable", "beta", "dev"], value="stable"),
            ]
        ),
    ],
}


def get_sections_for_category(category: str) -> List[Section]:
    """Get section configuration for a category"""
    return SECTION_CONFIGS.get(category, [])
