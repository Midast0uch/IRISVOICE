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
    AI_MODEL = "ai_model"
    AGENT = "agent"
    SYSTEM = "system"
    MEMORY = "memory"
    STATS = "analytics"  # Frontend uses "analytics" for STATS


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
    
    @field_validator('primary', 'glow', 'font')
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
    
    def get_category_values(self, category: str) -> Dict[str, Any]:
        """Get all field values for a category"""
        return self.field_values.get(category, {})
    
    def set_field_value(self, category: str, field_id: str, value: Any):
        """Set a field value for a category"""
        if category not in self.field_values:
            self.field_values[category] = {}
        self.field_values[category][field_id] = value
    
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
    category: str
    field_id: str
    value: Any


class ConfirmMiniNodeMessage(BaseModel):
    """Client confirms a mini-node"""
    type: str = "confirm_mini_node"
    category: str
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
    category: str
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


class ThemeUpdatedMessage(BaseModel):
    """Server broadcasts theme change"""
    type: str = "theme_updated"
    primary: str
    glow: str
    font: str


# ============================================================================
# Subnode Configurations (mirrors frontend SUB_NODES)
# ============================================================================

SUBNODE_CONFIGS: Dict[str, List[SubNode]] = {
    "voice": [
        SubNode(
            id="input_device",
            label="Input",
            icon="Mic",
            fields=[
                InputField(id="mic_select", type=FieldType.DROPDOWN, label="Microphone", options=["Default", "USB Mic", "Webcam", "Headset"], value="Default"),
                InputField(id="gain", type=FieldType.SLIDER, label="Gain", min=0, max=100, value=50, unit="%"),
                InputField(id="monitor", type=FieldType.TOGGLE, label="Monitor Input", value=False),
            ]
        ),
        SubNode(
            id="output_device",
            label="Output",
            icon="Volume2",
            fields=[
                InputField(id="speaker_select", type=FieldType.DROPDOWN, label="Speaker", options=["Default", "Headphones", "Speakers", "HDMI"], value="Default"),
                InputField(id="volume", type=FieldType.SLIDER, label="Volume", min=0, max=100, value=70, unit="%"),
            ]
        ),
        SubNode(
            id="test_audio",
            label="Test",
            icon="Headphones",
            fields=[
                InputField(id="test_mic", type=FieldType.TOGGLE, label="Test Mic", value=False),
                InputField(id="test_speaker", type=FieldType.TOGGLE, label="Test Speaker", value=False),
            ]
        ),
        SubNode(
            id="sensitivity",
            label="Gain",
            icon="AudioWaveform",
            fields=[
                InputField(id="threshold", type=FieldType.SLIDER, label="Threshold", min=-60, max=0, value=-30, unit="dB"),
                InputField(id="auto_gain", type=FieldType.TOGGLE, label="Auto Gain", value=True),
            ]
        ),
        SubNode(
            id="noise_cancellation",
            label="Filter",
            icon="Shield",
            fields=[
                InputField(id="noise_cancel", type=FieldType.TOGGLE, label="Noise Cancel", value=True),
                InputField(id="echo_cancel", type=FieldType.TOGGLE, label="Echo Cancel", value=True),
            ]
        ),
    ],
    "ai_model": [
        SubNode(
            id="lm_url",
            label="LM URL",
            icon="Link",
            fields=[
                InputField(id="endpoint", type=FieldType.TEXT, label="Endpoint", placeholder="http://localhost:1234", value="http://localhost:1234"),
            ]
        ),
        SubNode(
            id="temperature",
            label="Temp",
            icon="Thermometer",
            fields=[
                InputField(id="temp_value", type=FieldType.SLIDER, label="Temperature", min=0, max=2, step=0.1, value=0.7, unit=""),
            ]
        ),
        SubNode(
            id="max_tokens",
            label="Tokens",
            icon="FileText",
            fields=[
                InputField(id="max_tok", type=FieldType.SLIDER, label="Max Tokens", min=256, max=8192, step=256, value=2048, unit=""),
            ]
        ),
        SubNode(
            id="context_window",
            label="Context",
            icon="Layers",
            fields=[
                InputField(id="ctx_size", type=FieldType.SLIDER, label="Context Size", min=1024, max=32768, step=1024, value=8192, unit=""),
            ]
        ),
        SubNode(
            id="preset",
            label="Preset",
            icon="Cpu",
            fields=[
                InputField(id="model_preset", type=FieldType.DROPDOWN, label="Preset", options=["Creative", "Balanced", "Precise", "Custom"], value="Balanced"),
            ]
        ),
    ],
    "agent": [
        SubNode(
            id="wake_word",
            label="Wake",
            icon="Sparkles",
            fields=[
                InputField(id="wake_phrase", type=FieldType.TEXT, label="Wake Word", placeholder="Hey IRIS", value="Hey IRIS"),
                InputField(id="wake_enabled", type=FieldType.TOGGLE, label="Enabled", value=True),
            ]
        ),
        SubNode(
            id="voice_select",
            label="Voice",
            icon="MessageSquare",
            fields=[
                InputField(id="tts_voice", type=FieldType.DROPDOWN, label="Voice", options=["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"], value="Nova"),
            ]
        ),
        SubNode(
            id="speech_rate",
            label="Speed",
            icon="Gauge",
            fields=[
                InputField(id="rate", type=FieldType.SLIDER, label="Speed", min=0.5, max=2, step=0.1, value=1.0, unit="x"),
            ]
        ),
        SubNode(
            id="tools",
            label="Tools",
            icon="Wrench",
            fields=[
                InputField(id="web_search", type=FieldType.TOGGLE, label="Web Search", value=True),
                InputField(id="code_exec", type=FieldType.TOGGLE, label="Code Exec", value=False),
            ]
        ),
        SubNode(
            id="personality",
            label="Style",
            icon="Smile",
            fields=[
                InputField(id="persona", type=FieldType.DROPDOWN, label="Persona", options=["Professional", "Friendly", "Concise", "Creative"], value="Friendly"),
            ]
        ),
    ],
    "system": [
        SubNode(
            id="startup",
            label="Startup",
            icon="Power",
            fields=[
                InputField(id="auto_start", type=FieldType.TOGGLE, label="Start with OS", value=False),
                InputField(id="start_minimized", type=FieldType.TOGGLE, label="Start Minimized", value=False),
            ]
        ),
        SubNode(
            id="hotkey",
            label="Hotkey",
            icon="Keyboard",
            fields=[
                InputField(id="global_key", type=FieldType.TEXT, label="Global Hotkey", placeholder="Ctrl+Space", value="Ctrl+Space"),
            ]
        ),
        SubNode(
            id="theme",
            label="Theme",
            icon="Palette",
            fields=[
                InputField(id="glow_color", type=FieldType.COLOR, label="Glow Color", value="#00ff88"),
                InputField(id="dark_mode", type=FieldType.TOGGLE, label="Dark Mode", value=True),
            ]
        ),
        SubNode(
            id="tray",
            label="Tray",
            icon="Minimize2",
            fields=[
                InputField(id="minimize_tray", type=FieldType.TOGGLE, label="Minimize to Tray", value=True),
                InputField(id="show_notifications", type=FieldType.TOGGLE, label="Notifications", value=True),
            ]
        ),
        SubNode(
            id="updates",
            label="Update",
            icon="RefreshCw",
            fields=[
                InputField(id="auto_update", type=FieldType.TOGGLE, label="Auto Update", value=True),
                InputField(id="beta_channel", type=FieldType.TOGGLE, label="Beta Channel", value=False),
            ]
        ),
    ],
    "memory": [
        SubNode(
            id="history",
            label="History",
            icon="History",
            fields=[
                InputField(id="save_history", type=FieldType.TOGGLE, label="Save History", value=True),
                InputField(id="history_days", type=FieldType.SLIDER, label="Keep Days", min=1, max=90, value=30, unit=" days"),
            ]
        ),
        SubNode(
            id="context_length",
            label="Context",
            icon="FileStack",
            fields=[
                InputField(id="ctx_messages", type=FieldType.SLIDER, label="Messages", min=5, max=50, value=20, unit=""),
            ]
        ),
        SubNode(
            id="auto_summarize",
            label="Summary",
            icon="Zap",
            fields=[
                InputField(id="auto_sum", type=FieldType.TOGGLE, label="Auto Summarize", value=True),
                InputField(id="sum_threshold", type=FieldType.SLIDER, label="Threshold", min=1000, max=10000, step=500, value=5000, unit=" tokens"),
            ]
        ),
        SubNode(
            id="export",
            label="Export",
            icon="Download",
            fields=[
                InputField(id="export_format", type=FieldType.DROPDOWN, label="Format", options=["JSON", "Markdown", "Text", "CSV"], value="JSON"),
            ]
        ),
        SubNode(
            id="clear",
            label="Clear",
            icon="Trash2",
            fields=[
                InputField(id="clear_confirm", type=FieldType.TOGGLE, label="Clear All Data", value=False),
            ]
        ),
    ],
    "analytics": [
        SubNode(
            id="token_graph",
            label="Tokens",
            icon="BarChart3",
            fields=[
                InputField(id="show_tokens", type=FieldType.TOGGLE, label="Show Token Count", value=True),
            ]
        ),
        SubNode(
            id="latency",
            label="Latency",
            icon="Timer",
            fields=[
                InputField(id="show_latency", type=FieldType.TOGGLE, label="Show Latency", value=True),
            ]
        ),
        SubNode(
            id="session_time",
            label="Session",
            icon="Clock",
            fields=[
                InputField(id="show_session", type=FieldType.TOGGLE, label="Show Session Time", value=True),
            ]
        ),
        SubNode(
            id="cost",
            label="Cost",
            icon="DollarSign",
            fields=[
                InputField(id="show_cost", type=FieldType.TOGGLE, label="Track Cost", value=False),
                InputField(id="cost_limit", type=FieldType.SLIDER, label="Monthly Limit", min=0, max=100, value=20, unit="$"),
            ]
        ),
        SubNode(
            id="optimize",
            label="Optimize",
            icon="TrendingUp",
            fields=[
                InputField(id="suggestions", type=FieldType.TOGGLE, label="Show Suggestions", value=True),
            ]
        ),
    ],
}


def get_subnodes_for_category(category: str) -> List[SubNode]:
    """Get subnode configuration for a category"""
    return SUBNODE_CONFIGS.get(category, [])
