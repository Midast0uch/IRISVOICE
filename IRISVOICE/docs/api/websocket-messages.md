# WebSocket Message Protocol

## Overview

The IRISVOICE backend uses WebSocket for real-time bidirectional communication between the frontend and backend. All messages follow a consistent JSON structure.

## Connection

### Endpoint
```
ws://localhost:8000/ws/{client_id}?session_id={optional_session_id}
```

### Parameters
- `client_id` (required): Unique identifier for the client connection
- `session_id` (optional): Session ID to restore previous session state

### Connection Flow
1. Client connects to WebSocket endpoint
2. Backend creates or restores session
3. Backend sends `initial_state` message with complete session state
4. Heartbeat ping/pong messages every 30 seconds

## Message Structure

All messages use this format:
```json
{
  "type": "message_type",
  "payload": {
    "key": "value"
  }
}
```

## Client → Server Messages

### Navigation Messages

#### select_category
Switch to a settings category.

**Payload:**
```json
{
  "category": "voice" | "agent" | "automate" | "system" | "customize" | "monitor"
}
```

**Example:**
```json
{
  "type": "select_category",
  "payload": {
    "category": "voice"
  }
}
```

#### select_subnode
Activate a subnode within a category.

**Payload:**
```json
{
  "subnode_id": "string"
}
```

**Example:**
```json
{
  "type": "select_subnode",
  "payload": {
    "subnode_id": "input"
  }
}
```

#### go_back
Navigate to previous view.

**Payload:**
```json
{}
```

### Settings Messages

#### update_field
Update a field value.

**Payload:**
```json
{
  "subnode_id": "string",
  "field_id": "string",
  "value": "any",
  "timestamp": "number (optional)"
}
```

**Example:**
```json
{
  "type": "update_field",
  "payload": {
    "subnode_id": "input",
    "field_id": "input_device",
    "value": "Microphone (Realtek)",
    "timestamp": 1707156789123
  }
}
```

**Special Fields:**

- **inference_mode**: Select AI inference method
  - Values: `"local"`, `"vps"`, `"openai"`
  - Triggers model loading/unloading based on selection
  
- **vps_url**: VPS Gateway URL (when inference_mode is "vps")
  - Format: `"https://your-vps-server.com/api"`
  
- **vps_api_key**: VPS API key (when inference_mode is "vps")
  - Stored securely with encryption
  
- **openai_api_key**: OpenAI API key (when inference_mode is "openai")
  - Format: `"sk-[alphanumeric]"`
  - Validated before storage
  - Stored securely with encryption
  
- **agent_internet_access**: Control agent web search capabilities
  - Values: `true` (allow web search), `false` (block web search)
  - Does NOT affect application connectivity to VPS/OpenAI
  
- **reasoning_model**: Model for reasoning tasks
  - Populated from available models in selected inference mode
  
- **tool_execution_model**: Model for tool execution tasks
  - Populated from available models in selected inference mode

#### update_theme
Update theme colors.

**Payload:**
```json
{
  "glow_color": "string (optional)",
  "font_color": "string (optional)",
  "state_colors": "object (optional)"
}
```

**Example:**
```json
{
  "type": "update_theme",
  "payload": {
    "glow_color": "#7000ff"
  }
}
```

#### confirm_mini_node
Confirm a mini-node configuration.

**Payload:**
```json
{
  "subnode_id": "string",
  "values": "Record<string, any>"
}
```

### Voice Messages

#### voice_command_start
Begin voice recording.

**Payload:**
```json
{}
```

**Example:**
```json
{
  "type": "voice_command_start",
  "payload": {}
}
```

#### voice_command_end
Stop voice recording and process.

**Payload:**
```json
{}
```

#### get_wake_words
Request list of discovered wake word files.

**Payload:**
```json
{}
```

**Example:**
```json
{
  "type": "get_wake_words",
  "payload": {}
}
```

#### select_wake_word
Select a wake word file to load.

**Payload:**
```json
{
  "filename": "string"
}
```

**Example:**
```json
{
  "type": "select_wake_word",
  "payload": {
    "filename": "hey-iris_en_windows_v4_0_0.ppn"
  }
}
```

### Text Messages

#### text_message
Send text message to agent.

**Payload:**
```json
{
  "text": "string"
}
```

**Example:**
```json
{
  "type": "text_message",
  "payload": {
    "text": "What's the weather today?"
  }
}
```

#### clear_chat
Clear conversation history.

**Payload:**
```json
{}
```

### Status Messages

#### get_agent_status
Request agent status.

**Payload:**
```json
{}
```

#### get_agent_tools
Request available tools.

**Payload:**
```json
{}
```

#### get_available_models
Request list of available models from all configured inference sources.

**Payload:**
```json
{}
```

**Example:**
```json
{
  "type": "get_available_models",
  "payload": {}
}
```

#### get_cleanup_report
Request cleanup analysis report (dry-run).

**Payload:**
```json
{
  "dry_run": "boolean (default: true)"
}
```

**Example:**
```json
{
  "type": "get_cleanup_report",
  "payload": {
    "dry_run": true
  }
}
```

#### execute_cleanup
Execute cleanup of unused files and dependencies.

**Payload:**
```json
{
  "items": "string[]",
  "backup": "boolean (default: true)"
}
```

**Example:**
```json
{
  "type": "execute_cleanup",
  "payload": {
    "items": ["models/unused_model.bin", "wake_words/old_wake_word.ppn"],
    "backup": true
  }
}
```

## Server → Client Messages

### Connection Messages

#### initial_state
Full state sent on connection.

**Payload:**
```json
{
  "state": "IRISState"
}
```

**Example:**
```json
{
  "type": "initial_state",
  "payload": {
    "state": {
      "current_category": "voice",
      "current_subnode": "input",
      "field_values": {},
      "active_theme": {},
      "confirmed_nodes": [],
      "app_state": {}
    }
  }
}
```

#### backend_ready
Backend initialization complete.

**Payload:**
```json
{
  "timestamp": "string"
}
```

### Navigation Messages

#### category_changed
Category switch confirmed.

**Payload:**
```json
{
  "category": "string",
  "subnodes": "SubNode[]"
}
```

#### subnode_changed
Subnode switch confirmed.

**Payload:**
```json
{
  "subnode_id": "string"
}
```

### Settings Messages

#### field_updated
Field update confirmed.

**Payload:**
```json
{
  "subnode_id": "string",
  "field_id": "string",
  "value": "any",
  "valid": "boolean"
}
```

**Example:**
```json
{
  "type": "field_updated",
  "payload": {
    "subnode_id": "input",
    "field_id": "input_device",
    "value": "Microphone (Realtek)",
    "valid": true
  }
}
```

#### theme_updated
Theme update confirmed.

**Payload:**
```json
{
  "active_theme": "ColorTheme"
}
```

#### mini_node_confirmed
Mini-node confirmed with orbit position.

**Payload:**
```json
{
  "subnode_id": "string",
  "orbit_angle": "number"
}
```

### Voice Messages

#### listening_state
Voice state changed.

**Payload:**
```json
{
  "state": "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"
}
```

**Example:**
```json
{
  "type": "listening_state",
  "payload": {
    "state": "listening"
  }
}
```

#### wake_detected
Wake word detected.

**Payload:**
```json
{
  "phrase": "string",
  "confidence": "number"
}
```

#### audio_level
Audio level update (during listening).

**Payload:**
```json
{
  "level": "number (0.0 to 1.0)"
}
```

#### wake_words_list
List of discovered wake word files.

**Payload:**
```json
{
  "wake_words": "WakeWordInfo[]",
  "count": "number"
}
```

**WakeWordInfo Structure:**
```json
{
  "filename": "string",
  "display_name": "string",
  "platform": "string",
  "version": "string"
}
```

**Example:**
```json
{
  "type": "wake_words_list",
  "payload": {
    "wake_words": [
      {
        "filename": "hey-iris_en_windows_v4_0_0.ppn",
        "display_name": "Hey Iris",
        "platform": "windows",
        "version": "v4_0_0"
      }
    ],
    "count": 1
  }
}
```

#### wake_word_selected
Wake word selection confirmed.

**Payload:**
```json
{
  "filename": "string",
  "display_name": "string",
  "platform": "string",
  "version": "string"
}
```

**Example:**
```json
{
  "type": "wake_word_selected",
  "payload": {
    "filename": "hey-iris_en_windows_v4_0_0.ppn",
    "display_name": "Hey Iris",
    "platform": "windows",
    "version": "v4_0_0"
  }
}
```

### Agent Messages

#### text_response
Agent text response.

**Payload:**
```json
{
  "text": "string",
  "sender": "assistant"
}
```

**Example:**
```json
{
  "type": "text_response",
  "payload": {
    "text": "The weather today is sunny with a high of 75°F.",
    "sender": "assistant"
  }
}
```

#### agent_status
Agent status information.

**Payload:**
```json
{
  "ready": "boolean",
  "models_loaded": "number",
  "total_models": "number",
  "tool_bridge_available": "boolean",
  "model_status": "object",
  "inference_mode": "string",
  "reasoning_model": "string (optional)",
  "tool_execution_model": "string (optional)"
}
```

**Example:**
```json
{
  "type": "agent_status",
  "payload": {
    "ready": true,
    "models_loaded": 2,
    "total_models": 2,
    "tool_bridge_available": true,
    "model_status": {
      "lfm2-8b": "loaded",
      "lfm2.5-1.2b-instruct": "loaded"
    },
    "inference_mode": "local",
    "reasoning_model": "lfm2-8b",
    "tool_execution_model": "lfm2.5-1.2b-instruct"
  }
}
```

#### agent_tools
Available tools list.

**Payload:**
```json
{
  "tools": "Tool[]"
}
```

#### tool_result
Tool execution result.

**Payload:**
```json
{
  "tool_name": "string",
  "result": "any",
  "error": "string (optional)"
}
```

#### available_models
List of available models from all configured inference sources.

**Payload:**
```json
{
  "models": "ModelInfo[]",
  "count": "number"
}
```

**ModelInfo Structure:**
```json
{
  "id": "string",
  "name": "string",
  "source": "local" | "vps" | "openai",
  "capabilities": "string[]"
}
```

**Example:**
```json
{
  "type": "available_models",
  "payload": {
    "models": [
      {
        "id": "lfm2-8b",
        "name": "LFM2 8B",
        "source": "local",
        "capabilities": ["reasoning", "conversation"]
      },
      {
        "id": "lfm2.5-1.2b-instruct",
        "name": "LFM2.5 1.2B Instruct",
        "source": "local",
        "capabilities": ["tool_execution", "structured_output"]
      },
      {
        "id": "gpt-4",
        "name": "GPT-4",
        "source": "openai",
        "capabilities": ["reasoning", "conversation", "tool_execution"]
      }
    ],
    "count": 3
  }
}
```

#### inference_mode_changed
Inference mode change confirmed.

**Payload:**
```json
{
  "mode": "local" | "vps" | "openai",
  "models_loaded": "boolean",
  "timestamp": "number"
}
```

**Example:**
```json
{
  "type": "inference_mode_changed",
  "payload": {
    "mode": "vps",
    "models_loaded": false,
    "timestamp": 1707156789123
  }
}
```

#### model_selection_updated
Model selection change confirmed.

**Payload:**
```json
{
  "reasoning_model": "string",
  "tool_execution_model": "string"
}
```

**Example:**
```json
{
  "type": "model_selection_updated",
  "payload": {
    "reasoning_model": "gpt-4",
    "tool_execution_model": "gpt-4"
  }
}
```

#### cleanup_report
Cleanup analysis report.

**Payload:**
```json
{
  "unused_files": "UnusedFile[]",
  "unused_dependencies": "UnusedDependency[]",
  "total_size_bytes": "number",
  "total_files": "number",
  "total_dependencies": "number",
  "warnings": "string[]"
}
```

**UnusedFile Structure:**
```json
{
  "path": "string",
  "size_bytes": "number",
  "last_accessed": "string (ISO datetime)",
  "reason": "string",
  "category": "model" | "wake_word" | "config" | "other"
}
```

**UnusedDependency Structure:**
```json
{
  "name": "string",
  "version": "string",
  "install_size_bytes": "number",
  "reason": "string"
}
```

**Example:**
```json
{
  "type": "cleanup_report",
  "payload": {
    "unused_files": [
      {
        "path": "models/old_model.bin",
        "size_bytes": 8589934592,
        "last_accessed": "2024-01-15T10:30:00Z",
        "reason": "Not referenced in active code",
        "category": "model"
      }
    ],
    "unused_dependencies": [
      {
        "name": "unused-package",
        "version": "1.0.0",
        "install_size_bytes": 1048576,
        "reason": "Not imported in any module"
      }
    ],
    "total_size_bytes": 8590983168,
    "total_files": 1,
    "total_dependencies": 1,
    "warnings": ["Large unused model file detected (8.0 GB)"]
  }
}
```

#### cleanup_result
Cleanup execution result.

**Payload:**
```json
{
  "removed_files": "string[]",
  "removed_dependencies": "string[]",
  "freed_bytes": "number",
  "backup_path": "string (optional)",
  "errors": "string[]"
}
```

**Example:**
```json
{
  "type": "cleanup_result",
  "payload": {
    "removed_files": ["models/old_model.bin"],
    "removed_dependencies": ["unused-package"],
    "freed_bytes": 8590983168,
    "backup_path": "backend/backups/cleanup_2024-02-05_19-30-00.zip",
    "errors": []
  }
}
```

### Error Messages

#### validation_error
Field validation failed.

**Payload:**
```json
{
  "field_id": "string",
  "error": "string"
}
```

**Example:**
```json
{
  "type": "validation_error",
  "payload": {
    "field_id": "speaking_rate",
    "error": "Value must be between 0.5 and 2.0"
  }
}
```

#### voice_command_error
Voice processing failed.

**Payload:**
```json
{
  "error": "string"
}
```

#### error
General error.

**Payload:**
```json
{
  "message": "string"
}
```

## Heartbeat

The backend sends ping messages every 30 seconds. Clients should respond with pong within 5 seconds to maintain the connection.
