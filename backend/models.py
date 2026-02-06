"""
IRIS Backend Data Models
Pydantic models for type validation and serialization
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
    
    def get_category_values(self, category: str) -> Dict[str, Dict[str, Any]]:
        """Get all field values for a category (all subnodes)"""
        from .models import get_subnodes_for_category
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


# ============================================================================
# Subnode Configurations (mirrors frontend SUB_NODES)
# ============================================================================

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
                InputField(id="input_test", type=FieldType.TEXT, label="Input Test", placeholder="Test microphone", value=""),
            ]
        ),
        SubNode(
            id="output",
            label="OUTPUT",
            icon="Volume2",
            fields=[
                InputField(id="output_device", type=FieldType.DROPDOWN, label="Output Device", options=["Default", "Headphones", "Speakers", "HDMI"], value="Default"),
                InputField(id="master_volume", type=FieldType.SLIDER, label="Master Volume", min=0, max=100, value=70, unit="%"),
                InputField(id="output_test", type=FieldType.TEXT, label="Output Test", placeholder="Test audio", value=""),
                InputField(id="latency_compensation", type=FieldType.SLIDER, label="Latency Compensation", min=0, max=500, value=0, unit="ms"),
            ]
        ),
        SubNode(
            id="processing",
            label="PROCESSING",
            icon="AudioWaveform",
            fields=[
                InputField(id="noise_reduction", type=FieldType.TOGGLE, label="Noise Reduction", value=True),
                InputField(id="echo_cancellation", type=FieldType.TOGGLE, label="Echo Cancellation", value=True),
                InputField(id="voice_enhancement", type=FieldType.TOGGLE, label="Voice Enhancement", value=False),
                InputField(id="automatic_gain", type=FieldType.TOGGLE, label="Automatic Gain", value=True),
            ]
        ),
        SubNode(
            id="model",
            label="MODEL",
            icon="Cpu",
            fields=[
                InputField(id="endpoint", type=FieldType.TEXT, label="LFM Endpoint", placeholder="http://localhost:1234", value="http://localhost:1234"),
                InputField(id="connection_test", type=FieldType.TEXT, label="Connection Test", placeholder="Test connection", value=""),
                InputField(id="temperature", type=FieldType.SLIDER, label="Temperature", min=0, max=2, step=0.1, value=0.7, unit=""),
                InputField(id="max_tokens", type=FieldType.SLIDER, label="Max Tokens", min=256, max=8192, step=256, value=2048, unit=""),
                InputField(id="context_window", type=FieldType.SLIDER, label="Context Window", min=1024, max=32768, step=1024, value=8192, unit=""),
            ]
        ),
    ],
    "agent": [
        SubNode(
            id="identity",
            label="IDENTITY",
            icon="Smile",
            fields=[
                InputField(id="assistant_name", type=FieldType.TEXT, label="Assistant Name", placeholder="IRIS", value="IRIS"),
                InputField(id="personality", type=FieldType.DROPDOWN, label="Personality", options=["Professional", "Friendly", "Concise", "Creative", "Technical"], value="Friendly"),
                InputField(id="knowledge", type=FieldType.DROPDOWN, label="Knowledge Focus", options=["General", "Coding", "Writing", "Research", "Conversation"], value="General"),
                InputField(id="response_length", type=FieldType.DROPDOWN, label="Response Length", options=["Brief", "Balanced", "Detailed", "Comprehensive"], value="Balanced"),
            ]
        ),
        SubNode(
            id="wake",
            label="WAKE",
            icon="Sparkles",
            fields=[
                InputField(id="wake_phrase", type=FieldType.DROPDOWN, label="Wake Phrase", options=["Hey Computer", "Jarvis", "Alexa", "Hey Mycroft", "Hey Jarvis"], value="Hey Computer"),
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
                InputField(id="tts_voice", type=FieldType.DROPDOWN, label="TTS Voice", options=["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"], value="Nova"),
                InputField(id="speaking_rate", type=FieldType.SLIDER, label="Speaking Rate", min=0.5, max=2, step=0.1, value=1.0, unit="x"),
                InputField(id="pitch_adjustment", type=FieldType.SLIDER, label="Pitch Adjustment", min=-20, max=20, value=0, unit="semitones"),
                InputField(id="pause_duration", type=FieldType.SLIDER, label="Pause Duration", min=0, max=2, step=0.1, value=0.2, unit="s"),
                InputField(id="voice_cloning", type=FieldType.TEXT, label="Voice Cloning", placeholder="Upload audio path", value=""),
            ]
        ),
        SubNode(
            id="memory",
            label="MEMORY",
            icon="Database",
            fields=[
                InputField(id="context_visualization", type=FieldType.TEXT, label="Context Visualization", placeholder="View context", value=""),
                InputField(id="token_count", type=FieldType.TEXT, label="Token Count", placeholder="0 tokens", value="0"),
                InputField(id="conversation_history", type=FieldType.TEXT, label="Conversation History", placeholder="Browse history", value=""),
                InputField(id="clear_memory", type=FieldType.TEXT, label="Clear Memory", placeholder="Clear", value=""),
                InputField(id="export_memory", type=FieldType.TEXT, label="Export Memory", placeholder="Export", value=""),
            ]
        ),
    ],
    "automate": [
        SubNode(
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
        SubNode(
            id="workflows",
            label="WORKFLOWS",
            icon="Layers",
            fields=[
                InputField(id="workflow_list", type=FieldType.TEXT, label="Workflow List", placeholder="Saved workflows", value=""),
                InputField(id="create_workflow", type=FieldType.TEXT, label="Create Workflow", placeholder="Builder", value=""),
                InputField(id="schedule", type=FieldType.TEXT, label="Schedule", placeholder="Schedule", value=""),
                InputField(id="conditions", type=FieldType.TEXT, label="Conditions", placeholder="Conditions", value=""),
            ]
        ),
        SubNode(
            id="favorites",
            label="FAVORITES",
            icon="Star",
            fields=[
                InputField(id="favorite_commands", type=FieldType.TEXT, label="Favorite Commands", placeholder="Pinned actions", value=""),
                InputField(id="recent_actions", type=FieldType.TEXT, label="Recent Actions", placeholder="Recent", value=""),
                InputField(id="success_rate", type=FieldType.TEXT, label="Success Rate", placeholder="0%", value="0%"),
                InputField(id="edit_favorites", type=FieldType.TEXT, label="Edit Favorites", placeholder="Edit", value=""),
            ]
        ),
        SubNode(
            id="shortcuts",
            label="SHORTCUTS",
            icon="Keyboard",
            fields=[
                InputField(id="global_hotkey", type=FieldType.TEXT, label="Global Hotkey", placeholder="Ctrl+Space", value="Ctrl+Space"),
                InputField(id="voice_commands", type=FieldType.TEXT, label="Voice Commands", placeholder="Map commands", value=""),
                InputField(id="gesture_triggers", type=FieldType.TEXT, label="Gesture Triggers", placeholder="Gestures", value=""),
                InputField(id="key_combinations", type=FieldType.TEXT, label="Key Combinations", placeholder="Keys", value=""),
            ]
        ),
        SubNode(
            id="gui",
            label="GUI AUTOMATION",
            icon="Monitor",
            fields=[
                InputField(id="ui_tars_provider", type=FieldType.DROPDOWN, label="UI-TARS Provider", options=["cli_npx", "native_python", "api_cloud"], value="native_python"),
                InputField(id="model_provider", type=FieldType.DROPDOWN, label="Vision Model", options=["anthropic", "volcengine", "local"], value="anthropic"),
                InputField(id="api_key", type=FieldType.TEXT, label="API Key", placeholder="sk-...", value=""),
                InputField(id="max_steps", type=FieldType.SLIDER, label="Max Automation Steps", min=5, max=50, value=25),
                InputField(id="safety_confirmation", type=FieldType.TOGGLE, label="Require Confirmation", value=True),
                InputField(id="debug_mode", type=FieldType.TOGGLE, label="Debug Logging", value=True),
                InputField(id="test_automation", type=FieldType.TEXT, label="Test Automation", placeholder="Run test task", value=""),
            ]
        ),
    ],
    "system": [
        SubNode(
            id="power",
            label="POWER",
            icon="Power",
            fields=[
                InputField(id="shutdown", type=FieldType.TEXT, label="Shutdown", placeholder="Shutdown", value=""),
                InputField(id="restart", type=FieldType.TEXT, label="Restart", placeholder="Restart", value=""),
                InputField(id="sleep", type=FieldType.TEXT, label="Sleep", placeholder="Sleep", value=""),
                InputField(id="lock_screen", type=FieldType.TEXT, label="Lock Screen", placeholder="Lock", value=""),
                InputField(id="power_profile", type=FieldType.DROPDOWN, label="Power Profile", options=["Balanced", "Performance", "Battery"], value="Balanced"),
                InputField(id="battery_status", type=FieldType.TEXT, label="Battery Status", placeholder="Battery", value=""),
            ]
        ),
        SubNode(
            id="display",
            label="DISPLAY",
            icon="Monitor",
            fields=[
                InputField(id="brightness", type=FieldType.SLIDER, label="Brightness", min=0, max=100, value=50, unit="%"),
                InputField(id="resolution", type=FieldType.DROPDOWN, label="Resolution", options=["Auto", "1920x1080", "2560x1440", "3840x2160"], value="Auto"),
                InputField(id="night_mode", type=FieldType.TOGGLE, label="Night Mode", value=False),
                InputField(id="multi_monitor", type=FieldType.TEXT, label="Multi Monitor", placeholder="Arrange monitors", value=""),
                InputField(id="color_profile", type=FieldType.DROPDOWN, label="Color Profile", options=["sRGB", "DCI-P3", "Adobe RGB"], value="sRGB"),
            ]
        ),
        SubNode(
            id="storage",
            label="STORAGE",
            icon="HardDrive",
            fields=[
                InputField(id="disk_usage", type=FieldType.TEXT, label="Disk Usage", placeholder="Usage", value=""),
                InputField(id="quick_folders", type=FieldType.TEXT, label="Quick Folders", placeholder="Desktop/Downloads/Documents", value=""),
                InputField(id="cleanup", type=FieldType.TEXT, label="Cleanup", placeholder="Cleanup", value=""),
                InputField(id="external_drives", type=FieldType.TEXT, label="External Drives", placeholder="Drives", value=""),
            ]
        ),
        SubNode(
            id="network",
            label="NETWORK",
            icon="Wifi",
            fields=[
                InputField(id="wifi_toggle", type=FieldType.TOGGLE, label="WiFi", value=True),
                InputField(id="ethernet_status", type=FieldType.TEXT, label="Ethernet Status", placeholder="Connected", value=""),
                InputField(id="vpn_connection", type=FieldType.DROPDOWN, label="VPN Connection", options=["None", "Work", "Personal"], value="None"),
                InputField(id="bandwidth", type=FieldType.TEXT, label="Bandwidth", placeholder="0 Mbps", value=""),
                InputField(id="network_settings", type=FieldType.TEXT, label="Network Settings", placeholder="Advanced", value=""),
            ]
        ),
    ],
    "customize": [
        SubNode(
            id="theme",
            label="THEME",
            icon="Palette",
            fields=[
                InputField(id="theme_mode", type=FieldType.DROPDOWN, label="Theme Mode", options=["Dark", "Light", "Auto"], value="Dark"),
                InputField(id="glow_color", type=FieldType.COLOR, label="Glow Color", value="#00ff88"),
                InputField(id="state_colors", type=FieldType.TOGGLE, label="State Colors", value=False),
                InputField(id="idle_color", type=FieldType.COLOR, label="Idle Color", value="#00ff88"),
                InputField(id="listening_color", type=FieldType.COLOR, label="Listening Color", value="#00aaff"),
                InputField(id="processing_color", type=FieldType.COLOR, label="Processing Color", value="#a855f7"),
                InputField(id="error_color", type=FieldType.COLOR, label="Error Color", value="#ff3355"),
            ]
        ),
        SubNode(
            id="startup",
            label="STARTUP",
            icon="Power",
            fields=[
                InputField(id="launch_startup", type=FieldType.TOGGLE, label="Launch at Startup", value=False),
                InputField(id="startup_behavior", type=FieldType.DROPDOWN, label="Startup Behavior", options=["Show Widget", "Start Minimized", "Start Hidden"], value="Show Widget"),
                InputField(id="welcome_message", type=FieldType.TOGGLE, label="Welcome Message", value=True),
                InputField(id="default_state", type=FieldType.DROPDOWN, label="Default State", options=["Collapsed", "Expanded"], value="Collapsed"),
            ]
        ),
        SubNode(
            id="behavior",
            label="BEHAVIOR",
            icon="Sliders",
            fields=[
                InputField(id="confirm_destructive", type=FieldType.TOGGLE, label="Confirm Destructive", value=True),
                InputField(id="undo_history", type=FieldType.SLIDER, label="Undo History", min=0, max=50, value=10, unit="actions"),
                InputField(id="error_notifications", type=FieldType.DROPDOWN, label="Error Notifications", options=["Popup", "Banner", "Silent"], value="Popup"),
                InputField(id="auto_save", type=FieldType.TOGGLE, label="Auto Save", value=True),
            ]
        ),
        SubNode(
            id="notifications",
            label="NOTIFICATIONS",
            icon="Bell",
            fields=[
                InputField(id="dnd_toggle", type=FieldType.TOGGLE, label="Do Not Disturb", value=False),
                InputField(id="dnd_schedule", type=FieldType.TEXT, label="DND Schedule", placeholder="Quiet hours", value=""),
                InputField(id="notification_sound", type=FieldType.DROPDOWN, label="Notification Sound", options=["Default", "Chime", "Pulse", "Silent"], value="Default"),
                InputField(id="banner_style", type=FieldType.DROPDOWN, label="Banner Style", options=["Native", "Custom", "Minimal"], value="Native"),
                InputField(id="app_notifications", type=FieldType.TOGGLE, label="App Notifications", value=True),
            ]
        ),
    ],
    "monitor": [
        SubNode(
            id="analytics",
            label="ANALYTICS",
            icon="BarChart3",
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


def get_subnodes_for_category(category: str) -> List[SubNode]:
    """Get subnode configuration for a category"""
    return SUBNODE_CONFIGS.get(category, [])
