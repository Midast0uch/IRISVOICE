"""
IRIS Backend Core Data Models
Core Pydantic models for type validation and serialization
These models have no dependencies on other backend modules to avoid circular imports
"""
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
    """Input field types supported in mini-nodes"""
    TEXT = "text"
    SLIDER = "slider"
    DROPDOWN = "dropdown"
    TOGGLE = "toggle"
    COLOR = "color"
    KEY_COMBO = "keyCombo"


class InputField(BaseModel):
    """Configuration for a single input field in a mini-node"""
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
    
    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if isinstance(v, str):
            return FieldType(v)
        return v


class SubNode(BaseModel):
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


class ConfirmedNode(BaseModel):
    """A confirmed mini-node orbiting the IRIS center"""
    id: str
    label: str
    icon: str
    orbit_angle: float
    values: Dict[str, Any]
    category: str


class IRISState(BaseModel):
    """Complete application state"""
    current_category: Optional[Category] = None
    current_subnode: Optional[str] = None
    field_values: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    active_theme: ColorTheme = Field(default_factory=ColorTheme)
    confirmed_nodes: List[ConfirmedNode] = Field(default_factory=list)
    app_state: AppState = Field(default=AppState.STARTING)
    
    def get_category_values(self, category: str) -> Dict[str, Dict[str, Any]]:
        """Get all field values for a category (all subnodes)"""
        result = {}
        subnodes = get_subnodes_for_category(category)
        for subnode in subnodes:
            if subnode.id in self.field_values:
                result[subnode.id] = self.field_values[subnode.id]
        return result
    
    def set_field_value(self, subnode_id: str, field_id: str, value: Any):
        """Set a field value for a subnode"""
        if subnode_id not in self.field_values:
            self.field_values[subnode_id] = {}
        self.field_values[subnode_id][field_id] = value
    
    def add_confirmed_node(self, node: ConfirmedNode):
        """Add a confirmed node to orbit"""
        # Remove existing if same id
        self.confirmed_nodes = [n for n in self.confirmed_nodes if n.id != node.id]
        self.confirmed_nodes.append(node)


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


class SelectSubnodeMessage(BaseModel):
    """Client activates a subnode"""
    type: str = "select_subnode"
    subnode_id: str


class FieldUpdateMessage(BaseModel):
    """Client updates a field value"""
    type: str = "field_update"
    subnode_id: str
    field_id: str
    value: Any


class ConfirmMiniNodeMessage(BaseModel):
    """Client confirms a mini-node"""
    type: str = "confirm_mini_node"
    subnode_id: str
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
    subnodes: List[SubNode]


class FieldUpdatedMessage(BaseModel):
    """Server confirms field update"""
    type: str = "field_updated"
    subnode_id: str
    field_id: str
    value: Any
    valid: bool


class ValidationErrorMessage(BaseModel):
    """Server reports validation error"""
    type: str = "validation_error"
    field_id: str
    error: str


class MiniNodeConfirmedMessage(BaseModel):
    """Server confirms mini-node and provides orbit position"""
    type: str = "mini_node_confirmed"
    subnode_id: str
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


def get_subnodes_for_category(category: str) -> List[SubNode]:
    """Get subnode configuration for a category"""
    return SUBNODE_CONFIGS.get(category, [])

SUBNODE_CONFIGS: Dict[str, List[SubNode]] = {
    "voice": [
        SubNode(
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
        SubNode(
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
        SubNode(
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
        SubNode(
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
        SubNode(
            id="wake",
            label="WAKE",
            icon="Power",
            fields=[
                InputField(id="wake_word_enabled", type=FieldType.TOGGLE, label="Wake Word Enabled", value=True),
                InputField(id="wake_phrase", type=FieldType.DROPDOWN, label="Wake Phrase", options=["Hey IRIS", "Computer"], value="Hey IRIS"),
                InputField(id="detection_sensitivity", type=FieldType.SLIDER, label="Detection Sensitivity", min=0, max=100, value=70, unit="%"),
                InputField(id="activation_sound", type=FieldType.TOGGLE, label="Activation Sound", value=True),
                InputField(id="sleep_timeout", type=FieldType.SLIDER, label="Sleep Timeout", min=5, max=300, value=60, unit="s"),
            ]
        ),
        SubNode(
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
    ],
    "automate": [
        SubNode(
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
        SubNode(
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
        SubNode(
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
    ],
    "system": [
        SubNode(
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
        SubNode(
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
        SubNode(
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
    ],
    "customize": [
        SubNode(
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
        SubNode(
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
        SubNode(
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
    ],
    "monitor": [
        SubNode(
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
        SubNode(
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
        SubNode(
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
        SubNode(
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
