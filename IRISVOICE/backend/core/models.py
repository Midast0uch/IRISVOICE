"""
Pydantic Models for Type Safety

Provides strongly-typed models for critical data structures:
- Tool definitions and execution
- WebSocket messages
- Agent requests/responses
- Vision service status
- State updates

These models replace the widespread use of Dict[str, Any] with
explicit, validated, self-documenting types.
"""

from typing import Any, Dict, List, Optional, Literal, Union
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, validator


class ToolCategory(str, Enum):
    """Categories of available tools."""
    FILE_MANAGEMENT = "file_management"
    BROWSER = "browser"
    SYSTEM = "system"
    APP_LAUNCHER = "app_launcher"
    VISION = "vision"
    CUSTOM = "custom"


class ToolParameter(BaseModel):
    """Definition of a tool parameter."""
    name: str
    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    description: str
    required: bool = False
    default: Optional[Any] = None
    enum: Optional[List[Any]] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None


class ToolDefinition(BaseModel):
    """Definition of an available tool."""
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter]
    required_params: List[str] = Field(default_factory=list)
    
    class Config:
        use_enum_values = True


class ToolRequest(BaseModel):
    """Request to execute a tool."""
    tool_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = "default"
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ToolResponse(BaseModel):
    """Response from tool execution."""
    success: bool
    tool_name: str
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VisionStatus(BaseModel):
    """Vision service status."""
    status: Literal["disabled", "loading", "enabled", "error"]
    vram_usage_mb: Optional[float] = None
    load_progress_percent: Optional[float] = None
    error_message: Optional[str] = None
    last_used: Optional[datetime] = None
    model_name: str = "lfm2.5-vl"
    quantization_enabled: bool = True
    is_available: bool = False


class VoiceState(str, Enum):
    """Voice processing states."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


class VoiceStatus(BaseModel):
    """Voice pipeline status."""
    state: VoiceState
    audio_level: float = Field(ge=0.0, le=1.0, default=0.0)
    is_wake_word_active: bool = False
    current_wake_word: Optional[str] = None
    error_message: Optional[str] = None


class AgentStatus(BaseModel):
    """Agent kernel status."""
    initialized: bool = False
    active_skills: List[str] = Field(default_factory=list)
    available_tools: List[str] = Field(default_factory=list)
    conversation_length: int = 0
    last_activity: Optional[datetime] = None
    error_message: Optional[str] = None


class WebSocketMessage(BaseModel):
    """Generic WebSocket message."""
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[datetime] = None
    session_id: Optional[str] = None
    
    @validator('timestamp', pre=True, always=True)
    def set_timestamp(cls, v):
        return v or datetime.utcnow()


class StateSync(BaseModel):
    """State synchronization message."""
    category: Optional[str] = None
    section: Optional[str] = None
    field_values: Dict[str, Any] = Field(default_factory=dict)
    theme: Optional[Dict[str, str]] = None
    voice_state: Optional[VoiceState] = None


class ValidationError(BaseModel):
    """Structured validation error."""
    field: str
    error_type: Literal["required", "type", "format", "range", "pattern", "enum", "sanitization", "custom"]
    message: str
    value: Optional[str] = None


class ValidationResult(BaseModel):
    """Result of validation operation."""
    valid: bool
    errors: List[ValidationError] = Field(default_factory=list)
    sanitized_data: Optional[Dict[str, Any]] = None
    
    @property
    def is_valid(self) -> bool:
        return self.valid and len(self.errors) == 0


class TextMessage(BaseModel):
    """Text message for chat."""
    text: str
    sender: Literal["user", "assistant", "system"]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str = "default"
    message_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('text')
    def text_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Text cannot be empty')
        return v.strip()


class ThemeSettings(BaseModel):
    """UI theme settings."""
    primary: str = Field(default="#00ff88", pattern=r"^#[0-9a-fA-F]{6}$")
    glow: str = Field(default="#00ff88", pattern=r"^#[0-9a-fA-F]{6}$")
    font: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    idle_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    listening_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    processing_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    error_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class SessionState(BaseModel):
    """Complete session state."""
    session_id: str
    category: Optional[str] = None
    section: Optional[str] = None
    field_values: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    theme: ThemeSettings = Field(default_factory=ThemeSettings)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ScreenContext(BaseModel):
    """Screen analysis context."""
    active_app: str = "unknown"
    window_title: Optional[str] = None
    notable_items: List[str] = Field(default_factory=list)
    needs_help: bool = False
    suggestion: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    raw_analysis: Optional[str] = None


class AudioDevice(BaseModel):
    """Audio device information."""
    name: str
    index: int
    sample_rate: int
    channels: int = 2
    is_default: bool = False


class WakeWord(BaseModel):
    """Wake word configuration."""
    filename: str
    display_name: str
    platform: str
    version: str
    sensitivity: float = Field(ge=0.0, le=1.0, default=0.5)


class ErrorResponse(BaseModel):
    """Standard error response."""
    error_type: Literal["validation", "execution", "not_found", "timeout", "internal"]
    message: str
    field: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExecutionContext(BaseModel):
    """Context for tool execution."""
    session_id: str = "default"
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    source: Literal["voice", "chat", "automation", "system"] = "chat"
    permissions: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    """AI model information."""
    id: str
    name: str
    provider: str
    type: Literal["text", "vision", "audio", "multimodal"]
    capabilities: List[str] = Field(default_factory=list)
    max_tokens: Optional[int] = None
    context_window: Optional[int] = None


class ConversationContext(BaseModel):
    """Conversation context for agent."""
    messages: List[TextMessage] = Field(default_factory=list)
    system_prompt: Optional[str] = None
    max_context_length: int = 10
    session_id: str = "default"
    
    def add_message(self, text: str, sender: Literal["user", "assistant", "system"]):
        """Add a message to the conversation."""
        message = TextMessage(text=text, sender=sender)
        self.messages.append(message)
        # Trim to max length
        if len(self.messages) > self.max_context_length:
            self.messages = self.messages[-self.max_context_length:]


# Type aliases for commonly used types
ToolHandler = Union[
    callable,
    None
]

JsonDict = Dict[str, Any]
JsonList = List[Any]


# Utility functions for model conversion
def to_json_dict(model: BaseModel) -> Dict[str, Any]:
    """Convert Pydantic model to JSON dict."""
    return model.dict(by_alias=True, exclude_none=True)


def from_json_dict(data: Dict[str, Any], model_class: type) -> BaseModel:
    """Create Pydantic model from JSON dict."""
    return model_class.parse_obj(data)


def validate_tool_parameters(
    parameters: Dict[str, Any],
    tool_def: ToolDefinition
) -> ValidationResult:
    """
    Validate tool parameters against tool definition.
    
    Args:
        parameters: Parameters to validate
        tool_def: Tool definition with parameter specs
        
    Returns:
        ValidationResult with validation status
    """
    errors = []
    
    # Check required params
    for param_name in tool_def.required_params:
        if param_name not in parameters or parameters[param_name] is None:
            errors.append(ValidationError(
                field=param_name,
                error_type="required",
                message=f"Required parameter '{param_name}' is missing"
            ))
    
    # Validate each parameter
    for param in tool_def.parameters:
        if param.name not in parameters:
            continue
        
        value = parameters[param.name]
        
        # Type validation
        expected_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict
        }
        
        if param.type in expected_types:
            expected = expected_types[param.type]
            if not isinstance(value, expected):
                errors.append(ValidationError(
                    field=param.name,
                    error_type="type",
                    message=f"Expected {param.type}, got {type(value).__name__}",
                    value=str(value)
                ))
                continue
        
        # String validations
        if param.type == "string" and isinstance(value, str):
            if param.min_length and len(value) < param.min_length:
                errors.append(ValidationError(
                    field=param.name,
                    error_type="range",
                    message=f"Minimum length is {param.min_length}",
                    value=value
                ))
            
            if param.max_length and len(value) > param.max_length:
                errors.append(ValidationError(
                    field=param.name,
                    error_type="range",
                    message=f"Maximum length is {param.max_length}",
                    value=value
                ))
            
            if param.pattern and not __import__('re').match(param.pattern, value):
                errors.append(ValidationError(
                    field=param.name,
                    error_type="pattern",
                    message=f"Value does not match pattern {param.pattern}",
                    value=value
                ))
            
            if param.enum and value not in param.enum:
                errors.append(ValidationError(
                    field=param.name,
                    error_type="enum",
                    message=f"Value must be one of {param.enum}",
                    value=value
                ))
        
        # Number validations
        if param.type in ("integer", "number") and isinstance(value, (int, float)):
            if param.minimum is not None and value < param.minimum:
                errors.append(ValidationError(
                    field=param.name,
                    error_type="range",
                    message=f"Minimum value is {param.minimum}",
                    value=str(value)
                ))
            
            if param.maximum is not None and value > param.maximum:
                errors.append(ValidationError(
                    field=param.name,
                    error_type="range",
                    message=f"Maximum value is {param.maximum}",
                    value=str(value)
                ))
    
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors
    )


# Export commonly used models
__all__ = [
    "ToolCategory",
    "ToolParameter",
    "ToolDefinition",
    "ToolRequest",
    "ToolResponse",
    "VisionStatus",
    "VoiceState",
    "VoiceStatus",
    "AgentStatus",
    "WebSocketMessage",
    "StateSync",
    "ValidationError",
    "ValidationResult",
    "TextMessage",
    "ThemeSettings",
    "SessionState",
    "ScreenContext",
    "AudioDevice",
    "WakeWord",
    "ErrorResponse",
    "ExecutionContext",
    "ModelInfo",
    "ConversationContext",
    "to_json_dict",
    "from_json_dict",
    "validate_tool_parameters",
]
