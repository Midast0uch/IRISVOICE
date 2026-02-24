# IRIS Desktop Widget

A frameless, transparent desktop widget featuring a hexagonal hub-and-spoke interface with orbital input fields. Built with Next.js + Framer Motion frontend and Python FastAPI backend. Includes an autonomous AI agent powered by dual large language models.

## Features

- **Hexagonal Hub Interface**: 6 main categories (Voice, AI Model, Agent, System, Memory, Stats)
- **Subnode System**: Category-specific configuration panels
- **Mini-Node Carousel**: 180px double-size input cards with 3D stacking
- **Real-time Theme Sync**: Change colors and see updates instantly
- **Persistent State**: Settings saved to JSON and restored on restart
- **WebSocket Communication**: Low-latency bidirectional sync
- **Voice Command Integration**: Double-click the Iris Orb to activate voice commands
- **Window Dragging**: Click and drag the widget to reposition it on your desktop
- **Autonomous AI Agent**: Dual-LLM system (lfm2-8b brain + lfm2.5 executor) for autonomous task execution

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- pnpm or npm

### 1. Backend Setup

```powershell
# Create virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the backend
python start-backend.py
```

The backend will start on `http://localhost:8000`

WebSocket endpoint: `ws://localhost:8000/ws/iris`

### 2. Frontend Setup

```powershell
# Install dependencies
pnpm install

# Start the dev server
pnpm dev
```

The frontend will start on `http://localhost:3000`

### 3. Open in Browser

Navigate to `http://localhost:3000` to see the IRIS widget.

## Project Structure

```
IRISVOICE/
├── app/                    # Next.js app router
├── components/             # React components
│   ├── iris/              # Iris Orb and navigation components
│   │   ├── IrisOrb.tsx    # Unified Iris Orb component (navigation + voice + drag)
│   │   ├── navigation-controller.tsx # Handles navigation state
│   │   └── types.ts       # TypeScript interfaces
│   ├── fields/            # Field rendering components
│   │   └── [category]/    # Category-specific field components
│   ├── ui/                # UI components (transitions, animations)
│   └── hexagonal-control-center.tsx  # Main widget container (refactored)
├── contexts/              # React contexts
│   └── NavigationContext.tsx # Centralized navigation state
├── hooks/                 # Custom React hooks
│   └── useIRISWebSocket.ts # WebSocket connection hook
├── backend/               # Python FastAPI backend
│   ├── agent/             # AI Agent system
│   │   ├── agent_kernel.py       # Central orchestrator
│   │   ├── model_router.py       # Model capability routing
│   │   ├── model_wrapper.py      # Model abstraction
│   │   ├── inter_model_communication.py  # JSON protocol
│   │   ├── tool_executor.py      # Tool execution engine
│   │   ├── skill_registry.py     # Skill management
│   │   ├── exceptions.py          # Custom exceptions
│   │   └── agent_config.yaml     # Agent configuration
│   ├── __init__.py
│   ├── main.py            # FastAPI app & WebSocket endpoint
│   ├── models.py          # Pydantic data models
│   ├── state_manager.py   # State persistence
│   ├── ws_manager.py      # WebSocket connections
│   └── settings/          # JSON persistence folder
├── models/                # LLM model files
│   ├── LFM2-8B-A1B/      # Brain model
│   └── LFM2.5-1.2B-Instruct/  # Executor model
├── requirements.txt        # Python dependencies
├── start-backend.py        # Backend startup script
└── package.json            # Node.js dependencies
```

## Architecture Overview

### Navigation System

The IRIS widget uses a 4-level navigation system:

1. **Level 1**: Collapsed Iris Orb (home state)
2. **Level 2**: Expanded Iris Orb showing 6 main categories
3. **Level 3**: Subnodes for selected category (e.g., Voice inputs/outputs)
4. **Level 4**: Mini-nodes (individual configuration panels)

The Iris Orb serves as both the main navigation element and a back button for each level.

### Component Architecture

The widget has been refactored from a monolithic component into a modular architecture:

- **IrisOrb Component** (`components/iris/IrisOrb.tsx`): Central orb that handles:
  - Navigation clicks (single-click)
  - Voice command activation (double-click)
  - Window dragging
  - Visual feedback for all states

- **Navigation Controller** (`components/iris/navigation-controller.tsx`): Manages the navigation flow between levels

- **Fields System** (`components/fields/`): Renders backend data as interactive UI elements

- **UI Transitions** (`components/ui/`): Handles smooth animations between navigation levels

### State Management

- **Frontend**: Centralized in `NavigationContext.tsx` using React Context
- **Backend**: Managed by `state_manager.py` with JSON persistence
- **Synchronization**: Real-time bidirectional sync via WebSocket

## Backend Architecture

### Data Models

- **Category**: `voice`, `ai_model`, `agent`, `system`, `memory`, `analytics`
- **FieldType**: `text`, `slider`, `dropdown`, `toggle`, `color`, `keyCombo`
- **IRISState**: Complete application state with theme, field values, confirmed nodes

### WebSocket Protocol

**Client → Server:**
- `select_category` - Switch main view
- `select_subnode` - Activate subnode
- `field_update` - Update field value
- `confirm_mini_node` - Save mini-node to orbit
- `update_theme` - Change colors
- `request_state` - Get full state
- `voice_command_start` - Start voice recording
- `voice_command_end` - Stop voice recording

**Server → Client:**
- `initial_state` - Full state on connect
- `category_changed` - Category switch confirmation
- `field_updated` - Field validation response
- `mini_node_confirmed` - Confirm success with orbit position
- `theme_updated` - Broadcast theme changes

### Persistence

Settings are saved to `backend/settings/` as JSON files:
- `{category}.json` - Field values per category
- `theme.json` - Color theme settings

Uses atomic file writes for data safety.

## Agent Architecture

### Dual-LLM Model System

IRIS uses a specialized dual-model architecture for autonomous task execution:

| Model | Role | Location | Capabilities |
| --- | --- | --- | --- |
| **Brain (lfm2-8b)** | Reasoning/Planning | `./models/LFM2-8B-A1B` | Reasoning, planning, conversation |
| **Executor (lfm2.5-1.2b)** | Tool Execution | `./models/LFM2.5-1.2B-Instruct` | Tool execution, instruction following |

### Inter-Model Communication Protocol

Communication between models uses a standardized JSON protocol:

**Request (Brain → Executor):**
```json
{
  "request_id": "req_a1b2c3",
  "timestamp": "2026-02-21T10:30:00Z",
  "tool_name": "read_file",
  "parameters": {"path": "/config.json"},
  "context": "User asked for configuration",
  "priority": "normal"
}
```

**Response (Executor → Brain):**
```json
{
  "request_id": "req_a1b2c3",
  "status": "success",
  "output_data": {"content": "..."},
  "error_message": null
}
```

### Available Tools

The agent can execute these tools autonomously:

| Tool | Category | Description |
| --- | --- | --- |
| `read_file` | File Management | Read file contents |
| `write_file` | File Management | Write to file |
| `list_directory` | File Management | List directory contents |
| `open_url` | Browser | Open URL in browser |
| `search` | Browser | Search via default engine |
| `launch_app` | App Launcher | Launch application |
| `get_system_info` | System | Get system information |
| `lock` | System | Lock the screen |

### Configuration

Edit `backend/agent/agent_config.yaml` to configure models and communication:

```yaml
communication:
  timeout: 30.0
  max_retries: 3

models:
  - id: "brain"
    path: "./models/LFM2-8B-A1B"
    capabilities: ["reasoning", "planning"]
    optional: false
```

### Health Checks

The agent system includes health checks to verify model availability:

```python
from backend.agent import get_agent_kernel

kernel = get_agent_kernel()
status = kernel.model_router.check_all_models_health()
```

## Configuration

### Environment Variables (Backend)

Create a `.env` file in the project root:

```env
IRIS_HOST=127.0.0.1
IRIS_PORT=8000
```

### WebSocket URL (Frontend)

Edit `hooks/useIRISWebSocket.ts` or pass custom URL:

```typescript
const { theme, updateField } = useIRISWebSocket("ws://localhost:8000/ws/iris")
```

## Development

### Running Tests

```powershell
# Backend tests
venv\Scripts\python -m pytest backend/

# Frontend tests
pnpm test
```

### API Documentation

With the backend running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Troubleshooting

### Backend won't start

1. Check Python version: `python --version` (need 3.10+)
2. Verify virtual environment: `venv\Scripts\python --version`
3. Reinstall dependencies: `pip install -r requirements.txt --force-reinstall`

### Frontend can't connect

1. Verify backend is running: `curl http://localhost:8000/`
2. Check WebSocket URL in browser console
3. Ensure no firewall blocking port 8000

### Settings not persisting

1. Check `backend/settings/` folder exists and is writable
2. Verify JSON files are being created
3. Check backend logs for file I/O errors

### Navigation issues (subnodes not appearing)

1. Check browser console for WebSocket errors
2. Verify `NavigationContext.tsx` state updates
3. Ensure `hexagonal-control-center.tsx` is properly subscribing to state changes
4. Check that `iris/IrisOrb.tsx` is triggering the correct navigation actions

## Tech Stack

**Frontend:**
- Next.js 14 (App Router)
- React 18
- TypeScript
- Tailwind CSS
- Framer Motion
- Lucide Icons

**Backend:**
- Python 3.10+
- FastAPI
- WebSockets
- Pydantic
- aiofiles

## License

MIT