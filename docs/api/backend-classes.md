# Backend Classes Documentation

## Overview

This document describes the main backend classes and their methods in the IRISVOICE system.

## Core Components

### WebSocketManager

Manages WebSocket connections and session association.

**Location:** `backend/ws_manager.py`

#### Methods

##### `connect(websocket: WebSocket, client_id: str, session_id: Optional[str]) -> Optional[str]`
Establish a WebSocket connection and associate with a session.

**Parameters:**
- `websocket`: WebSocket connection object
- `client_id`: Unique client identifier
- `session_id`: Optional session ID to restore

**Returns:** Session ID

**Example:**
```python
session_id = await ws_manager.connect(websocket, "client-123", "session-456")
```

##### `disconnect(client_id: str) -> None`
Disconnect a client and clean up resources.

**Parameters:**
- `client_id`: Client identifier to disconnect

##### `send_to_client(client_id: str, message: dict) -> bool`
Send a message to a specific client.

**Parameters:**
- `client_id`: Target client identifier
- `message`: Message dictionary

**Returns:** Success boolean

##### `broadcast(message: dict, exclude_clients: Optional[Set[str]]) -> None`
Broadcast message to all connected clients.

**Parameters:**
- `message`: Message to broadcast
- `exclude_clients`: Optional set of client IDs to exclude

##### `broadcast_to_session(session_id: str, message: dict, exclude_clients: Optional[Set[str]]) -> None`
Broadcast message to all clients in a session.

**Parameters:**
- `session_id`: Target session ID
- `message`: Message to broadcast
- `exclude_clients`: Optional set of client IDs to exclude

### SessionManager

Manages user sessions and state isolation.

**Location:** `backend/sessions/session_manager.py`

#### Methods

##### `create_session(session_id: Optional[str]) -> str`
Create a new session or restore existing one.

**Parameters:**
- `session_id`: Optional session ID to restore

**Returns:** Session ID

##### `get_session(session_id: str) -> Optional[IRISession]`
Retrieve a session by ID.

**Parameters:**
- `session_id`: Session identifier

**Returns:** Session object or None

##### `associate_client_with_session(client_id: str, session_id: str) -> None`
Associate a client with a session.

**Parameters:**
- `client_id`: Client identifier
- `session_id`: Session identifier

##### `dissociate_client(client_id: str) -> Optional[str]`
Remove client from session.

**Parameters:**
- `client_id`: Client identifier

**Returns:** Session ID the client was associated with

##### `archive_inactive_sessions() -> None`
Archive sessions inactive for 24+ hours.

### StateManager

Manages application state per session.

**Location:** `backend/state_manager.py`

#### Methods

##### `get_state(session_id: str) -> Optional[IRISState]`
Get complete state for a session.

**Parameters:**
- `session_id`: Session identifier

**Returns:** IRISState object

##### `set_category(session_id: str, category: Optional[Category]) -> None`
Set current category.

**Parameters:**
- `session_id`: Session identifier
- `category`: Category to set

##### `set_subnode(session_id: str, subnode_id: Optional[str]) -> None`
Set current subnode.

**Parameters:**
- `session_id`: Session identifier
- `subnode_id`: Subnode identifier

##### `update_field(session_id: str, subnode_id: str, field_id: str, value: Any) -> bool`
Update a field value with validation.

**Parameters:**
- `session_id`: Session identifier
- `subnode_id`: Subnode containing the field
- `field_id`: Field identifier
- `value`: New value

**Returns:** Success boolean

**Example:**
```python
success = await state_manager.update_field(
    "session-123",
    "input",
    "input_device",
    "Microphone (Realtek)"
)
```

##### `update_theme(session_id: str, glow_color: Optional[str], font_color: Optional[str], state_colors: Optional[dict]) -> None`
Update theme colors.

**Parameters:**
- `session_id`: Session identifier
- `glow_color`: Optional glow color hex
- `font_color`: Optional font color hex
- `state_colors`: Optional state colors dictionary

##### `get_field_value(session_id: str, subnode_id: str, field_id: str, default: Any) -> Any`
Get a field value with default fallback.

**Parameters:**
- `session_id`: Session identifier
- `subnode_id`: Subnode containing the field
- `field_id`: Field identifier
- `default`: Default value if not found

**Returns:** Field value or default

### IRISGateway

Routes incoming WebSocket messages to appropriate handlers.

**Location:** `backend/iris_gateway.py`

#### Methods

##### `handle_message(client_id: str, message: dict) -> None`
Main message dispatcher.

**Parameters:**
- `client_id`: Client identifier
- `message`: Message dictionary

**Routes to:**
- `_handle_navigation()` - Navigation messages
- `_handle_settings()` - Settings messages
- `_handle_voice()` - Voice messages
- `_handle_chat()` - Chat messages
- `_handle_status()` - Status queries

## Agent System

### AgentKernel

Orchestrates the dual-LLM system.

**Location:** `backend/agent/agent_kernel.py`

#### Methods

##### `process_text_message(text: str, session_id: str) -> str`
Process a text message through the dual-LLM system.

**Parameters:**
- `text`: User message text
- `session_id`: Session identifier

**Returns:** Agent response text

**Example:**
```python
response = await agent_kernel.process_text_message(
    "What's the weather?",
    "session-123"
)
```

##### `plan_task(task_description: str) -> Dict[str, Any]`
Use lfm2-8b to create an execution plan.

**Parameters:**
- `task_description`: Task to plan

**Returns:** Execution plan dictionary

##### `execute_plan(plan: Dict[str, Any]) -> List[Any]`
Use lfm2.5-1.2b-instruct to execute a plan.

**Parameters:**
- `plan`: Execution plan from plan_task()

**Returns:** List of execution results

##### `get_status() -> Dict[str, Any]`
Get agent status information.

**Returns:** Status dictionary with:
- `ready`: Boolean
- `models_loaded`: Number
- `total_models`: Number
- `tool_bridge_available`: Boolean
- `model_status`: Dictionary

### VPSGateway

Routes model inference to remote VPS or local execution.

**Location:** `backend/agent/vps_gateway.py`

#### Methods

##### `initialize() -> None`
Initialize VPS gateway and health monitoring.

##### `shutdown() -> None`
Shutdown VPS gateway and cleanup resources.

##### `infer(model: str, prompt: str, context: Dict, params: Dict) -> str`
Route inference to VPS or local based on availability.

**Parameters:**
- `model`: Model name ("lfm2-8b" or "lfm2.5-1.2b-instruct")
- `prompt`: Input prompt
- `context`: Context dictionary
- `params`: Inference parameters

**Returns:** Generated text

##### `check_vps_health(endpoint: str) -> bool`
Check VPS endpoint health.

**Parameters:**
- `endpoint`: VPS endpoint URL

**Returns:** Health status boolean

##### `is_vps_available() -> bool`
Check if any VPS endpoint is available.

**Returns:** Availability boolean

### ModelRouter

Routes messages to appropriate LLM model.

**Location:** `backend/agent/model_router.py`

#### Methods

##### `route_message(message: str, context: Dict) -> str`
Determine which model should handle the message.

**Parameters:**
- `message`: User message
- `context`: Message context

**Returns:** Model name ("lfm2-8b" or "lfm2.5-1.2b-instruct")

##### `is_tool_execution(message: str) -> bool`
Determine if message requires tool execution.

**Parameters:**
- `message`: User message

**Returns:** Boolean

### ConversationMemory

Manages conversation history.

**Location:** `backend/agent/memory.py`

#### Methods

##### `add_message(role: str, content: str) -> None`
Add message to conversation history.

**Parameters:**
- `role`: Message role ("user" or "assistant")
- `content`: Message content

##### `get_context() -> List[Dict]`
Get conversation context for LLM.

**Returns:** List of message dictionaries

##### `clear() -> None`
Clear conversation history.

##### `get_message_count() -> int`
Get number of messages in history.

**Returns:** Message count

## Voice System

### VoicePipeline

Orchestrates the LFM 2.5 audio model for end-to-end audio processing.

**Location:** `backend/voice/voice_pipeline.py`

#### Methods

##### `start_listening(session_id: str) -> None`
Start voice recording and activate LFM 2.5 audio model.

**Parameters:**
- `session_id`: Session identifier

##### `stop_listening(session_id: str) -> None`
Stop voice recording and process audio.

**Parameters:**
- `session_id`: Session identifier

##### `get_audio_level() -> float`
Get current audio level (0.0 to 1.0).

**Returns:** Audio level

### AudioEngine

Thin wrapper around LFM 2.5 audio model.

**Location:** `backend/voice/audio_engine.py`

#### Methods

##### `initialize() -> None`
Initialize LFM 2.5 audio model.

##### `start_audio_interaction() -> None`
Start audio capture and processing.

##### `stop_audio_interaction() -> None`
Stop audio capture and processing.

##### `process_audio(audio_data: bytes) -> str`
Pass audio to LFM 2.5 model for processing.

**Parameters:**
- `audio_data`: Raw audio bytes

**Returns:** Transcribed text

## Tool System

### AgentToolBridge

Provides access to MCP tools.

**Location:** `backend/agent/tool_bridge.py`

#### Methods

##### `initialize() -> None`
Initialize all MCP servers.

##### `get_available_tools() -> List[Dict[str, Any]]`
Get list of all available tools.

**Returns:** List of tool dictionaries

##### `execute_tool(tool_name: str, params: Dict) -> Dict`
Execute a tool with parameters.

**Parameters:**
- `tool_name`: Tool identifier
- `params`: Tool parameters

**Returns:** Execution result dictionary

##### `execute_mcp_tool(server_name: str, tool_name: str, params: Dict) -> Dict`
Execute a tool on a specific MCP server.

**Parameters:**
- `server_name`: MCP server name
- `tool_name`: Tool identifier
- `params`: Tool parameters

**Returns:** Execution result dictionary

##### `get_status() -> Dict`
Get tool bridge status.

**Returns:** Status dictionary

### VisionSystem

Manages screen monitoring and vision capabilities.

**Location:** `backend/tools/vision_system.py`

#### Methods

##### `start_monitoring() -> None`
Start screen monitoring.

##### `stop_monitoring() -> None`
Stop screen monitoring.

##### `capture_screen() -> bytes`
Capture current screen.

**Returns:** Screen capture bytes

##### `analyze_screen(image_bytes: bytes) -> Dict`
Analyze screen capture using vision model.

**Parameters:**
- `image_bytes`: Screen capture bytes

**Returns:** Analysis result dictionary

### SecurityFilter

Validates tool parameters and enforces security policies.

**Location:** `backend/gateway/security_filter.py`

#### Methods

##### `validate_parameters(tool_name: str, params: Dict) -> bool`
Validate tool parameters against allowlist.

**Parameters:**
- `tool_name`: Tool identifier
- `params`: Tool parameters

**Returns:** Validation result boolean

##### `is_destructive(tool_name: str, params: Dict) -> bool`
Check if operation is destructive.

**Parameters:**
- `tool_name`: Tool identifier
- `params`: Tool parameters

**Returns:** Boolean

##### `check_rate_limit(session_id: str) -> bool`
Check if session has exceeded rate limit.

**Parameters:**
- `session_id`: Session identifier

**Returns:** Boolean (True if within limit)
