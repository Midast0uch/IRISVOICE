# Data Models

## Overview

This document describes the data structures used in the IRISVOICE backend.

## Core Models

### IRISState

Complete application state for a session.

```python
class IRISState(BaseModel):
    current_category: Optional[Category]
    current_subnode: Optional[str]
    field_values: Dict[str, Dict[str, Any]]  # subnode_id -> field_id -> value
    active_theme: ColorTheme
    confirmed_nodes: List[ConfirmedNode]
    app_state: AppState
    vps_config: VPSConfig
```

**Fields:**
- `current_category`: Currently selected settings category
- `current_subnode`: Currently selected subnode
- `field_values`: Nested dictionary of all field values
- `active_theme`: Current theme configuration
- `confirmed_nodes`: List of confirmed mini-nodes
- `app_state`: Application state information
- `vps_config`: VPS Gateway configuration

### ColorTheme

Theme color configuration.

```python
class ColorTheme(BaseModel):
    primary: str  # Hex color
    glow: str  # Hex color
    font: str  # Hex color
    state_colors_enabled: bool
    idle_color: str
    listening_color: str
    processing_color: str
    error_color: str
```

**Example:**
```json
{
  "primary": "#7000ff",
  "glow": "#7000ff",
  "font": "#ffffff",
  "state_colors_enabled": true,
  "idle_color": "#7000ff",
  "listening_color": "#00ff7f",
  "processing_color": "#7000ff",
  "error_color": "#ff0000"
}
```

### SubNode

Settings subnode configuration.

```python
class SubNode(BaseModel):
    id: str
    label: str
    icon: str  # Lucide icon name
    fields: List[InputField]
```

**Example:**
```json
{
  "id": "input",
  "label": "Input",
  "icon": "Mic",
  "fields": [...]
}
```

### InputField

Field configuration for settings.

```python
class InputField(BaseModel):
    id: str
    type: FieldType  # text, slider, dropdown, toggle, color, keyCombo
    label: str
    value: Optional[Union[str, int, float, bool]]
    placeholder: Optional[str]
    options: Optional[List[str]]  # For dropdown
    min: Optional[Union[int, float]]  # For slider
    max: Optional[Union[int, float]]  # For slider
    step: Optional[Union[int, float]]  # For slider
    unit: Optional[str]  # Display unit
```

**Field Types:**
- `text`: Text input
- `slider`: Numeric slider
- `dropdown`: Select from options
- `toggle`: Boolean switch
- `color`: Color picker
- `keyCombo`: Keyboard shortcut capture

**Example (Slider):**
```json
{
  "id": "speaking_rate",
  "type": "slider",
  "label": "Speaking Rate",
  "value": 1.0,
  "min": 0.5,
  "max": 2.0,
  "step": 0.1,
  "unit": "x"
}
```

**Example (Dropdown):**
```json
{
  "id": "tts_voice",
  "type": "dropdown",
  "label": "TTS Voice",
  "value": "Nova",
  "options": ["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"]
}
```

### ConfirmedNode

Confirmed mini-node orbiting the center.

```python
class ConfirmedNode(BaseModel):
    id: str
    label: str
    icon: str
    orbit_angle: float  # 0-360 degrees
    values: Dict[str, Any]
    category: str
```

**Example:**
```json
{
  "id": "wake-config",
  "label": "Wake Word",
  "icon": "Zap",
  "orbit_angle": 45.0,
  "values": {
    "wake_phrase": "jarvis",
    "detection_sensitivity": 50
  },
  "category": "agent"
}
```

### IRISession

Session data structure.

```python
class IRISession(BaseModel):
    session_id: str
    created_at: datetime
    last_active: datetime
    connected_clients: Set[str]
    state_manager: IsolatedStateManager
    conversation_history: List[Message]
```

**Fields:**
- `session_id`: Unique session identifier
- `created_at`: Session creation timestamp
- `last_active`: Last activity timestamp
- `connected_clients`: Set of connected client IDs
- `state_manager`: Isolated state manager for this session
- `conversation_history`: List of conversation messages

## VPS Models

### VPSConfig

VPS Gateway configuration.

```python
class VPSConfig(BaseModel):
    enabled: bool = False
    endpoints: List[str] = []  # VPS endpoint URLs
    auth_token: Optional[str] = None
    timeout: int = 30  # seconds
    health_check_interval: int = 60  # seconds
    fallback_to_local: bool = True
    load_balancing: bool = False
    protocol: str = "rest"  # "rest" or "websocket"
    offload_tools: bool = False
```

**Example:**
```json
{
  "enabled": true,
  "endpoints": ["https://vps1.example.com:8000"],
  "auth_token": "your-secret-token",
  "timeout": 30,
  "health_check_interval": 60,
  "fallback_to_local": true,
  "load_balancing": false,
  "protocol": "rest",
  "offload_tools": false
}
```

### VPSHealthStatus

VPS endpoint health tracking.

```python
class VPSHealthStatus(BaseModel):
    endpoint: str
    available: bool
    last_check: datetime
    last_success: Optional[datetime]
    consecutive_failures: int
    latency_ms: Optional[float]
    error_message: Optional[str]
```

**Example:**
```json
{
  "endpoint": "https://vps1.example.com:8000",
  "available": true,
  "last_check": "2025-02-26T21:57:00Z",
  "last_success": "2025-02-26T21:57:00Z",
  "consecutive_failures": 0,
  "latency_ms": 45.2,
  "error_message": null
}
```

### VPSInferenceRequest

Request payload for VPS inference.

```python
class VPSInferenceRequest(BaseModel):
    model: str  # "lfm2-8b" or "lfm2.5-1.2b-instruct"
    prompt: str
    context: Dict[str, Any]  # Conversation history, personality, etc.
    parameters: Dict[str, Any]  # Temperature, max_tokens, etc.
    session_id: str
    tool_calls: Optional[List[Dict]]  # Tool execution requests
```

**Example:**
```json
{
  "model": "lfm2-8b",
  "prompt": "What's the weather today?",
  "context": {
    "conversation_history": [...],
    "personality": "friendly"
  },
  "parameters": {
    "temperature": 0.7,
    "max_tokens": 500
  },
  "session_id": "session-123",
  "tool_calls": null
}
```

### VPSInferenceResponse

Response payload from VPS inference.

```python
class VPSInferenceResponse(BaseModel):
    text: str  # Generated text
    model: str  # Model used for inference
    latency_ms: float  # Inference latency
    tool_calls: Optional[List[Dict]]  # Tool calls requested by model
    tool_results: Optional[List[Dict]]  # Tool execution results
    metadata: Dict[str, Any]  # Additional metadata
```

**Example:**
```json
{
  "text": "The weather today is sunny with a high of 75°F.",
  "model": "lfm2-8b",
  "latency_ms": 234.5,
  "tool_calls": null,
  "tool_results": null,
  "metadata": {
    "tokens": 45,
    "finish_reason": "stop"
  }
}
```

## Voice Models

### VoiceState

Voice interaction state.

```python
VoiceState = Literal[
    "idle",
    "listening",
    "processing_conversation",
    "processing_tool",
    "speaking",
    "error"
]
```

**States:**
- `idle`: No voice activity
- `listening`: Recording user speech
- `processing_conversation`: Processing user input
- `processing_tool`: Executing tools
- `speaking`: Playing audio response
- `error`: Error occurred

## Tool Models

### Tool

Tool definition.

```python
class Tool(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    server: str  # MCP server name
```

**Example:**
```json
{
  "name": "capture_screen",
  "description": "Capture the current screen",
  "parameters": {
    "region": {
      "type": "string",
      "description": "Screen region to capture",
      "enum": ["full", "window", "selection"]
    }
  },
  "server": "vision"
}
```

### ToolResult

Tool execution result.

```python
class ToolResult(BaseModel):
    tool_name: str
    success: bool
    result: Any
    error: Optional[str]
    execution_time_ms: float
```

**Example:**
```json
{
  "tool_name": "capture_screen",
  "success": true,
  "result": {
    "image_path": "/tmp/screen_capture.png",
    "width": 1920,
    "height": 1080
  },
  "error": null,
  "execution_time_ms": 125.3
}
```

## Enums

### Category

Settings categories.

```python
Category = Literal[
    "voice",
    "agent",
    "automate",
    "system",
    "customize",
    "monitor"
]
```

### FieldType

Field input types.

```python
FieldType = Literal[
    "text",
    "slider",
    "dropdown",
    "toggle",
    "color",
    "keyCombo"
]
```
