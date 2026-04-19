# Configuration Guide

## Overview

IRISVOICE configuration is organized into categories, each stored in a separate JSON file in `backend/settings/`.

## Configuration Files

### voice.json

Voice and audio settings.

**Location:** `backend/settings/voice.json`

#### Structure
```json
{
  "input": {
    "input_device": "string",
    "sample_rate": "number",
    "channels": "number"
  },
  "output": {
    "output_device": "string",
    "volume": "number (0.0-1.0)"
  },
  "processing": {
    "noise_reduction": "boolean",
    "echo_cancellation": "boolean",
    "voice_enhancement": "boolean",
    "automatic_gain": "boolean"
  },
  "audio_model": {
    "model_path": "string",
    "device": "cpu | cuda"
  }
}
```

#### Fields

**input.input_device**
- Type: string
- Description: Audio input device name
- Example: "Microphone (Realtek)"

**input.sample_rate**
- Type: number
- Description: Audio sample rate in Hz
- Default: 16000
- Valid values: 8000, 16000, 22050, 44100, 48000

**input.channels**
- Type: number
- Description: Number of audio channels
- Default: 1
- Valid values: 1 (mono), 2 (stereo)

**output.output_device**
- Type: string
- Description: Audio output device name
- Example: "Speakers (Realtek)"

**output.volume**
- Type: number
- Description: Output volume level
- Default: 0.8
- Range: 0.0 to 1.0

**processing.noise_reduction**
- Type: boolean
- Description: Enable noise reduction (handled by LFM 2.5)
- Default: true

**processing.echo_cancellation**
- Type: boolean
- Description: Enable echo cancellation (handled by LFM 2.5)
- Default: true

**processing.voice_enhancement**
- Type: boolean
- Description: Enable voice enhancement (handled by LFM 2.5)
- Default: true

**processing.automatic_gain**
- Type: boolean
- Description: Enable automatic gain control (handled by LFM 2.5)
- Default: true

### agent.json

Agent and LLM settings.

**Location:** `backend/settings/agent.json`

#### Structure
```json
{
  "identity": {
    "assistant_name": "string",
    "personality": "string",
    "knowledge": "string"
  },
  "wake": {
    "wake_phrase": "string",
    "detection_sensitivity": "number (0-100)",
    "activation_sound": "boolean"
  },
  "speech": {
    "tts_voice": "string",
    "speaking_rate": "number (0.5-2.0)"
  },
  "memory": {
    "conversation_limit": "number",
    "context_window": "number"
  },
  "vps": {
    "enabled": "boolean",
    "endpoints": "string[]",
    "auth_token": "string",
    "timeout": "number",
    "health_check_interval": "number",
    "fallback_to_local": "boolean",
    "load_balancing": "boolean",
    "protocol": "rest | websocket",
    "offload_tools": "boolean"
  }
}
```

#### Fields

**identity.assistant_name**
- Type: string
- Description: Name of the assistant
- Default: "IRIS"

**identity.personality**
- Type: string
- Description: Personality style
- Valid values: "professional", "friendly", "casual", "technical"
- Default: "friendly"

**identity.knowledge**
- Type: string
- Description: Domain expertise
- Valid values: "general", "technical", "creative", "analytical"
- Default: "general"

**wake.wake_phrase**
- Type: string
- Description: Wake word phrase
- Valid values: "jarvis", "hey computer", "computer", "bumblebee", "porcupine"
- Default: "jarvis"

**wake.detection_sensitivity**
- Type: number
- Description: Wake word detection sensitivity
- Range: 0-100
- Default: 50

**speech.tts_voice**
- Type: string
- Description: TTS voice characteristics
- Valid values: "Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"
- Default: "Nova"

**speech.speaking_rate**
- Type: number
- Description: TTS speaking rate multiplier
- Range: 0.5 to 2.0
- Default: 1.0

**memory.conversation_limit**
- Type: number
- Description: Maximum messages to keep in memory
- Default: 10
- Range: 1 to 100

**vps.enabled**
- Type: boolean
- Description: Enable VPS gateway for remote model inference
- Default: false

**vps.endpoints**
- Type: string[]
- Description: List of VPS endpoint URLs
- Example: ["https://vps1.example.com:8000", "https://vps2.example.com:8000"]

**vps.auth_token**
- Type: string
- Description: Bearer token for VPS authentication
- Example: "your-secret-token"

**vps.timeout**
- Type: number
- Description: Request timeout in seconds
- Default: 30
- Range: 5 to 120

**vps.health_check_interval**
- Type: number
- Description: Health check interval in seconds
- Default: 60
- Range: 10 to 300

**vps.fallback_to_local**
- Type: boolean
- Description: Fall back to local execution when VPS unavailable
- Default: true

**vps.load_balancing**
- Type: boolean
- Description: Enable load balancing across multiple VPS endpoints
- Default: false

**vps.protocol**
- Type: string
- Description: Communication protocol
- Valid values: "rest", "websocket"
- Default: "rest"

**vps.offload_tools**
- Type: boolean
- Description: Offload tool execution to VPS
- Default: false

### automate.json

Automation and tool settings.

**Location:** `backend/settings/automate.json`

#### Structure
```json
{
  "tools": {
    "enabled": "boolean",
    "allowlist": "string[]"
  },
  "vision": {
    "vision_enabled": "boolean",
    "screen_context": "boolean",
    "proactive_monitor": "boolean",
    "ollama_endpoint": "string",
    "vision_model": "string",
    "monitor_interval": "number (5-120)"
  },
  "workflows": {
    "enabled": "boolean",
    "custom_workflows": "object[]"
  }
}
```

#### Fields

**tools.enabled**
- Type: boolean
- Description: Enable MCP tool access
- Default: true

**tools.allowlist**
- Type: string[]
- Description: List of allowed tool names
- Example: ["vision", "web", "file", "system"]

**vision.vision_enabled**
- Type: boolean
- Description: Enable vision capabilities
- Default: false

**vision.screen_context**
- Type: boolean
- Description: Include screen captures in chat context
- Default: false

**vision.proactive_monitor**
- Type: boolean
- Description: Enable proactive screen monitoring
- Default: false

**vision.ollama_endpoint**
- Type: string
- Description: Ollama endpoint URL for vision model
- Default: "http://localhost:11434"

**vision.vision_model**
- Type: string
- Description: Vision model to use
- Valid values: "minicpm-o4.5", "llava", "bakllava"
- Default: "minicpm-o4.5"

**vision.monitor_interval**
- Type: number
- Description: Screen monitoring interval in seconds
- Range: 5 to 120
- Default: 30

### theme.json

Theme and appearance settings.

**Location:** `backend/settings/theme.json`

#### Structure
```json
{
  "primary": "string (hex color)",
  "glow": "string (hex color)",
  "font": "string (hex color)",
  "state_colors_enabled": "boolean",
  "idle_color": "string (hex color)",
  "listening_color": "string (hex color)",
  "processing_color": "string (hex color)",
  "error_color": "string (hex color)"
}
```

#### Fields

**primary**
- Type: string
- Description: Primary UI color
- Format: Hex color (#RRGGBB)
- Default: "#7000ff"

**glow**
- Type: string
- Description: Orb glow color
- Format: Hex color (#RRGGBB)
- Default: "#7000ff"

**font**
- Type: string
- Description: Font color
- Format: Hex color (#RRGGBB)
- Default: "#ffffff"

**state_colors_enabled**
- Type: boolean
- Description: Use different colors for voice states
- Default: true

**idle_color**
- Type: string
- Description: Color for idle state
- Format: Hex color (#RRGGBB)
- Default: "#7000ff"

**listening_color**
- Type: string
- Description: Color for listening state
- Format: Hex color (#RRGGBB)
- Default: "#00ff7f"

**processing_color**
- Type: string
- Description: Color for processing state
- Format: Hex color (#RRGGBB)
- Default: "#7000ff"

**error_color**
- Type: string
- Description: Color for error state
- Format: Hex color (#RRGGBB)
- Default: "#ff0000"

## Configuration Management

### Loading Configuration

Configuration is loaded automatically on backend startup from JSON files in `backend/settings/`.

### Updating Configuration

Configuration can be updated via:
1. WebSocket `update_field` messages
2. Direct JSON file editing (requires backend restart)

### Validation

All configuration updates are validated against field schemas before being applied. Invalid values are rejected with a `validation_error` message.

### Persistence

Configuration changes are persisted immediately to JSON files using atomic writes with backup.

### Default Values

If a configuration file is missing or corrupted, default values are used and a warning is logged.
