# IRIS Desktop Widget

A frameless, transparent desktop widget featuring a hexagonal hub-and-spoke interface with orbital input fields. Built with Next.js + Framer Motion frontend and Python FastAPI backend.

## Features

- **Hexagonal Hub Interface**: 6 main categories (Voice, AI Model, Agent, System, Memory, Stats)
- **Subnode System**: Category-specific configuration panels
- **Mini-Node Carousel**: 180px double-size input cards with 3D stacking
- **Real-time Theme Sync**: Change colors and see updates instantly
- **Persistent State**: Settings saved to JSON and restored on restart
- **WebSocket Communication**: Low-latency bidirectional sync

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
│   └── hexagonal-control-center.tsx  # Main widget component
├── hooks/                  # Custom React hooks
│   └── useIRISWebSocket.ts # WebSocket connection hook
├── backend/                # Python FastAPI backend
│   ├── __init__.py
│   ├── main.py             # FastAPI app & WebSocket endpoint
│   ├── models.py           # Pydantic data models
│   ├── state_manager.py    # State persistence
│   ├── ws_manager.py       # WebSocket connections
│   └── settings/           # JSON persistence folder
├── requirements.txt        # Python dependencies
├── start-backend.py        # Backend startup script
└── package.json            # Node.js dependencies
```

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
