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
  "value": "any"
}
```

**Example:**
```json
{
  "type": "update_field",
  "payload": {
    "subnode_id": "input",
    "field_id": "input_device",
    "value": "Microphone (Realtek)"
  }
}
```

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
  "model_status": "object"
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
    }
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
