# IRIS Backend Core Infrastructure

This directory contains the core infrastructure components for the IRIS backend system.

## Overview

The core infrastructure provides:
- **WebSocket Management**: Real-time bidirectional communication with frontend clients
- **Session Management**: Multi-client session support with state isolation
- **State Management**: Persistent application state per session
- **Structured Logging**: JSON-formatted logging with context injection

## Directory Structure

```
backend/
├── core/              # Core infrastructure (this directory)
│   ├── __init__.py    # Core module exports
│   ├── logging_config.py  # Logging configuration
│   └── README.md      # This file
├── agent/             # Agent system (dual-LLM, conversation, tools)
├── voice/             # Voice pipeline (audio, VAD, wake word)
├── tools/             # MCP tool integration
├── gateway/           # Message routing and gateway
├── sessions/          # Session management
├── monitoring/        # Structured logging and monitoring
└── main.py            # FastAPI application entry point
```

## Components

### WebSocket Manager

Manages WebSocket connections and message routing.

**Location**: `backend/ws_manager.py`

**Key Features**:
- Connection lifecycle management
- Client-to-session association
- Message broadcasting (all clients or session-specific)
- Ping/pong heartbeat (30s interval)

**Usage**:
```python
from backend.core import get_websocket_manager

ws_manager = get_websocket_manager()
await ws_manager.connect(websocket, client_id, session_id)
await ws_manager.send_to_client(client_id, {"type": "message", "data": "..."})
await ws_manager.broadcast_to_session(session_id, {"type": "update"})
```

### Session Manager

Manages user sessions with state isolation.

**Location**: `backend/sessions/session_manager.py`

**Key Features**:
- Session creation and restoration
- Multi-client session support
- Session archival (24 hours of inactivity)
- State isolation between sessions

**Usage**:
```python
from backend.core import get_session_manager

session_manager = get_session_manager()
session_id = await session_manager.create_session()
session = session_manager.get_session(session_id)
```

### State Manager

Manages application state per session.

**Location**: `backend/state_manager.py`

**Key Features**:
- Field value management with validation
- Theme configuration
- Navigation state (category, subnode)
- JSON persistence to `backend/settings/`

**Usage**:
```python
from backend.core import get_state_manager

state_manager = get_state_manager()
await state_manager.update_field(session_id, "voice.input", "input_device", "default")
current_state = await state_manager.get_state(session_id)
```

### Structured Logger

Provides JSON-formatted logging with context injection.

**Location**: `backend/monitoring/structured_logger.py`

**Key Features**:
- JSON-formatted log output
- Context injection (session_id, component, etc.)
- File rotation (10MB per file, 5 backups)
- Security event tracking
- Performance metrics

**Usage**:
```python
from backend.core.logging_config import get_component_logger

logger = get_component_logger("websocket")
logger.set_context(session_id="abc123")
logger.info("Connection established", client_id="client_1")
logger.security_event("unauthorized_access", {"resource": "/admin"})
```

## Configuration

### Environment Variables

- `IRIS_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO
- `IRIS_LOG_DIR`: Directory for log files. Default: `backend/logs/`
- `ALLOWED_ORIGINS`: Comma-separated list of allowed CORS origins. Default: `http://localhost:3000,http://localhost:3001,tauri://localhost,https://tauri.localhost`

### CORS Configuration

The backend is configured to accept connections from:
- Next.js development server: `http://localhost:3000`, `http://localhost:3001`
- Tauri application: `tauri://localhost`, `https://tauri.localhost`

To add additional origins, set the `ALLOWED_ORIGINS` environment variable:

```bash
export ALLOWED_ORIGINS="http://localhost:3000,https://myapp.com"
```

### Logging Configuration

Logging is configured in `backend/core/logging_config.py` and initialized in `backend/main.py`.

**Default Configuration**:
- Log level: INFO
- Log file: `backend/logs/irisvoice.log`
- File rotation: 10MB per file, 5 backups
- Format: JSON with timestamps, levels, and context

**Component Loggers**:
```python
from backend.core.logging_config import (
    get_websocket_logger,
    get_session_logger,
    get_state_logger,
    get_agent_logger,
    get_voice_logger,
    get_tool_logger,
    get_gateway_logger
)

# Each logger has the component name set in context
logger = get_websocket_logger()
logger.info("WebSocket message received")
```

## WebSocket Protocol

### Connection

Clients connect to: `ws://localhost:8000/ws/{client_id}?session_id={optional_session_id}`

**Parameters**:
- `client_id` (required): Unique identifier for the client
- `session_id` (optional): Session ID to restore (if reconnecting)

**On Connection**:
1. Backend creates or restores session
2. Backend sends `initial_state` message with complete IRISState
3. Backend registers state change callback for the client

### Message Format

All messages follow this structure:

```json
{
  "type": "message_type",
  "payload": {
    "key": "value"
  }
}
```

### Heartbeat

- Backend sends `ping` every 30 seconds
- Client must respond with `pong` within 5 seconds
- Connection is closed if pong not received

## State Persistence

Application state is persisted to JSON files in `backend/settings/`:

- `voice.json`: Voice settings (input/output devices, processing)
- `agent.json`: Agent settings (personality, wake word, TTS)
- `automate.json`: Automation settings (tools, vision, workflows)
- `system.json`: System settings (power, display, storage, network)
- `customize.json`: Customization settings (theme, startup, behavior)
- `monitor.json`: Monitoring settings (analytics, logs, diagnostics)
- `theme.json`: Theme configuration (colors, state colors)

**Persistence Strategy**:
- Auto-save on every field update
- Atomic writes with backup
- Validation against field schemas
- Corruption recovery with default values

## Error Handling

The core infrastructure implements comprehensive error handling:

### WebSocket Layer
- Connection failures: Exponential backoff retry (1s, 2s, 4s) up to 3 attempts
- Parse errors: Log and continue processing
- Invalid messages: Send error response to client

### Session Layer
- Session creation failures: Log and return error
- State corruption: Use default values and log warning

### State Layer
- Validation errors: Send `validation_error` message to client
- Persistence errors: Retry once, then send error to client
- File corruption: Use default values and log warning

## Testing

Core infrastructure tests are located in `tests/unit/`:

- `test_websocket_manager.py`: WebSocket connection and message routing
- `test_session_manager.py`: Session lifecycle and isolation
- `test_state_manager.py`: State management and persistence

Run tests:
```bash
cd IRISVOICE
pytest tests/unit/test_websocket_manager.py -v
pytest tests/unit/test_session_manager.py -v
pytest tests/unit/test_state_manager.py -v
```

## Requirements

The core infrastructure satisfies the following spec requirements:

- **Requirement 1.1**: WebSocket connection to `ws://localhost:8000/ws/{client_id}`
- **Requirement 1.2**: Initial state message on connection
- **Requirement 1.5**: Ping/pong heartbeat (30s interval)
- **Requirement 2.1**: Session creation/restoration
- **Requirement 2.2**: Field value persistence
- **Requirement 2.4**: Session state isolation
- **Requirement 19.7**: Structured error logging

## Next Steps

After setting up the core infrastructure, the next tasks are:

1. **Task 2**: Implement WebSocket connection and session management
2. **Task 3**: Implement state management and persistence
3. **Task 4**: Implement IRIS Gateway message routing
4. **Task 6**: Implement dual-LLM agent system
5. **Task 12**: Implement voice pipeline infrastructure

See `.kiro/specs/irisvoice-backend-integration/tasks.md` for the complete implementation plan.
