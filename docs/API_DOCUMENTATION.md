# IRISVOICE Backend Integration API Documentation

## Overview

This document provides comprehensive API documentation for the IRISVOICE backend integration, covering:
- WebSocket message protocol
- Backend classes and methods
- Configuration options
- Data models

## Table of Contents

1. [WebSocket Protocol](#websocket-protocol)
2. [Backend Architecture](#backend-architecture)
3. [Configuration](#configuration)
4. [Data Models](#data-models)
5. [Error Handling](#error-handling)

## Quick Start

### Connection

Connect to the WebSocket endpoint:
```
ws://localhost:8000/ws/{client_id}?session_id={optional_session_id}
```

### Message Format

All messages follow this JSON structure:
```json
{
  "type": "message_type",
  "payload": {
    "key": "value"
  }
}
```

## Documentation Structure

- [WebSocket Messages](./docs/api/websocket-messages.md) - Complete WebSocket protocol reference
- [Backend Classes](./docs/api/backend-classes.md) - Backend component documentation
- [Configuration Guide](./docs/api/configuration.md) - Configuration options and settings
- [Data Models](./docs/api/data-models.md) - Data structure definitions

## Key Features

- **Real-time Communication**: WebSocket-based bidirectional messaging
- **Session Management**: Persistent sessions with state isolation
- **Dual-LLM Architecture**: lfm2-8b (reasoning) + lfm2.5-1.2b-instruct (execution)
- **VPS Gateway**: Optional remote model inference with automatic fallback
- **Voice Pipeline**: LFM 2.5 end-to-end audio processing
- **MCP Tool Integration**: Vision, web, file, system, and app automation tools
- **State Synchronization**: Multi-client real-time state updates

## Support

For issues and questions, refer to the design document at `.kiro/specs/irisvoice-backend-integration/design.md`
