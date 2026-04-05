# IRISVOICE - AI Voice Assistant Platform

A production-ready AI voice assistant platform featuring an intuitive hexagonal interface, end-to-end voice processing, and autonomous task execution. Built with Next.js + Framer Motion frontend and Python FastAPI backend, powered by dual large language models and advanced voice AI.

## 🌟 Key Features

### 🎤 Voice & Audio
- **Wake Word Detection**: Custom wake words using Picovoice Porcupine with automatic file discovery
- **Wake Word Discovery**: Automatically finds all wake word files in wake_words/ directory
- **End-to-End Audio Processing**: LFM 2.5 audio model handles complete audio pipeline
- **Voice Commands**: Natural language voice interaction with double-click activation
- **Text-to-Speech**: F5-TTS (zero-shot voice cloning from TOMV2.wav, CPU) or Piper (fast built-in)
- **Audio Processing**: Automatic noise reduction, echo cancellation, and voice enhancement

### 🤖 AI Agent System
- **Flexible Inference**: Any GGUF model via llama-server (ik_llama.cpp binary, preferred) or llama-cpp-python (port 8082) or OpenAI-compatible VPS — select in Settings
- **Tool Execution**: LFM2.5-1.2B-Instruct handles structured tool calls; main LLM handles reasoning and conversation
- **DER Loop**: Director → Explorer → Reviewer agent loop with trailing crystallizer
- **Model-Agnostic Design**: Works with Local GGUF, VPS, or OpenAI inference backends
- **Flexible Inference Modes**: Choose between Local Models (Models Browser), VPS Gateway, or OpenAI API
- **Lazy Loading**: Models load only when needed, not on startup
- **Autonomous Task Execution**: Agent can execute complex multi-step tasks
- **Tool Integration**: MCP-based tool system for browser, file, system, and app automation
- **Personality System**: Configurable assistant personality and behavior
- **Conversation Memory**: Context-aware conversations with memory management (persists across mode switches)
- **Internet Access Control**: Toggle agent web search capabilities independently of app connectivity

### 👁 Vision Layer (LFM2.5-VL)
- **LFM2.5-VL-1.6B**: Liquid AI's vision-language model running via `llama-server` on port 8081
- **VisionMCPServer**: 5 MCP tools — `vision.analyze_screen`, `vision.find_ui_element`, `vision.read_text`, `vision.suggest_next_action`, `vision.describe_live_frame`
- **UniversalGUIOperator**: Controls any Windows application — UIA accessibility first, VL coordinate prediction second, PIL diff verification third
- **Perception-Action-Verify Loop**: Every GUI action is preceded by VL perception and followed by result verification
- **smart_click()**: VL finds element by natural language description → UIA by name → known coordinates — no hardcoded pixel hunting
- **PIL Fallback**: Pixel diff verification when VL is offline; all pipelines degrade gracefully
- **MiniCPM Removed**: Fully replaced by LFM2.5-VL + llama-server (no Ollama dependency)

### 🖥 Desktop Automation
- **Any Windows App**: UniversalGUIOperator works with Paint, Notepad, Chrome, Office — no app-specific code
- **Drawing Pipeline**: Programmatic star + sine wave via mouse drag
- **Text Pipeline**: PIL generates Segoe Script 36pt text → clipboard DIB → Ctrl+V paste → drag to position
- **Telegram Integration**: Sends canvas screenshots with caption via bot API

### 🎨 User Interface
- **Hexagonal Hub Interface**: 6 main categories (Voice, Agent, Automate, System, Customize, Monitor)
- **Wheel View Navigation**: Intuitive 4-level navigation system
- **Dark Glass Dashboard**: Modern glassmorphic design with smooth animations
- **Real-time Theme Sync**: Instant color theme updates across all clients
- **Accessibility**: WCAG 2.1 AA compliant with screen reader support
- **Multi-Client Sync**: Real-time state synchronization across multiple windows

### ⚡ Backend Infrastructure
- **WebSocket Communication**: Low-latency bidirectional messaging (<50ms p95)
- **Session Management**: Multi-client sessions with state isolation
- **State Persistence**: Atomic JSON persistence with corruption recovery
- **Structured Logging**: JSON-formatted logs with context injection
- **Performance Optimization**: Sub-50ms WebSocket latency, <5s agent responses
- **Security**: Tool execution security with allowlists and audit logging
- **Cleanup System**: Analyze and remove unused files and dependencies to free disk space

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [System Requirements](#-system-requirements)
- [Installation](#-installation)
- [Architecture](#-architecture)
- [Configuration](#-configuration)
- [Development](#-development)
- [Testing](#-testing)
- [Documentation](#-documentation)
- [Troubleshooting](#-troubleshooting)

## 🚀 Quick Start

### Prerequisites

- **Python**: 3.10 or higher
- **Node.js**: 18.x or higher
- **npm/pnpm**: Latest version
- **Git**: For cloning the repository

### 1. Clone the Repository

```bash
git clone <repository-url>
cd IRISVOICE
```

### 2. Vision Model Setup (LFM2.5-VL, optional)

```python
# Download LFM2.5-VL GGUF files (one-time, ~1GB total) — optional, only for vision features
from huggingface_hub import hf_hub_download
import os
base = os.path.expanduser("~/models/LFM2.5-VL-1.6B/")
os.makedirs(base, exist_ok=True)
hf_hub_download("LiquidAI/LFM2.5-VL-1.6B-GGUF", "LFM2.5-VL-1.6B-Q4_0.gguf", local_dir=base)
hf_hub_download("LiquidAI/LFM2.5-VL-1.6B-GGUF", "mmproj-LFM2.5-VL-1.6B-Q4_0.gguf", local_dir=base)
```

```bash
# Start vision server (Windows)
start_vl.bat

# Install vision dependencies
pip install mss httpx pywinauto pyautogui pillow win32clipboard
```

### 3. Backend Setup

```bash
# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Install F5-TTS for voice cloning (optional — uses Piper built-in if skipped)
pip install f5-tts

# Set up environment variables
# Create .env file with:
# PICOVOICE_ACCESS_KEY=your_access_key_here
# TELEGRAM_BOT_TOKEN=your_bot_token  (optional)
# TELEGRAM_CHAT_ID=your_chat_id      (optional)
```

### 3. Frontend Setup

```bash
# Install Node.js dependencies
npm install

# or with pnpm
pnpm install
```

### 4. Run the Application

**Option 1: Using the startup script (Windows)**
```bash
start-iris.bat
```

**Option 2: Manual startup**

Terminal 1 (Backend):
```bash
python start-backend.py
```

Terminal 2 (Frontend — production mode, ~1 GB lighter than dev):
```bash
npm run start:prod       # next build && next start (recommended)
```

Or for hot-reload during active frontend development:
```bash
npm run dev              # next dev (heavier, webpack watch mode)
```

**Option 3: Tauri Desktop App**
```bash
npm run dev:tauri
```

### 5. Access the Application

- **Web**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **WebSocket**: ws://localhost:8000/ws/{client_id}

## 💻 System Requirements

### Minimum Requirements
- **CPU**: 4-core processor (Intel i5 or AMD Ryzen 5)
- **RAM**: 16 GB
- **Storage**: 20 GB free space
- **GPU**: Optional (NVIDIA GPU with CUDA recommended)
- **Audio**: Microphone and speakers/headphones

### Recommended Requirements
- **CPU**: 8-core processor (Intel i7/i9 or AMD Ryzen 7/9)
- **RAM**: 32 GB or more
- **Storage**: 50 GB free space (SSD recommended)
- **GPU**: NVIDIA GPU with 8GB+ VRAM (RTX 3060 or better)
- **Audio**: High-quality USB microphone

### Software Requirements
- **OS**: Windows 10/11, macOS 10.15+, or Ubuntu 20.04+ (Linux fully supported — preferred for lower RAM baseline)
- **Python**: 3.10+
- **Node.js**: 18.x+
- **CUDA Toolkit**: 11.8 or 12.1 (optional, for GPU acceleration)

## 📦 Installation

### Detailed Installation Steps

1. **Install Python Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install PyTorch with CUDA (GPU users)**
   ```bash
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
   ```

3. **Install TTS** (one-time)
   ```bash
   # F5-TTS for zero-shot voice cloning (optional — falls back to Piper if skipped)
   pip install f5-tts
   # Place TOMV2.wav at IRISVOICE/data/TOMV2.wav for voice cloning
   # F5-TTS model weights (~800 MB) download automatically on first "Cloned Voice" use
   ```

4. **Configure Environment**
   
   Create `.env` file in the IRISVOICE directory:
   ```env
   # Backend Configuration
   BACKEND_HOST=localhost
   BACKEND_PORT=8000
   
   # Picovoice Access Key (for wake word detection)
   PICOVOICE_ACCESS_KEY=your_access_key_here
   
   # Model Configuration
   MODEL_PATH=./models
   DEVICE=cuda  # or 'cpu' for CPU-only
   
   # Logging
   LOG_LEVEL=INFO
   LOG_FILE=backend/logs/iris.log
   ```

5. **Install Frontend Dependencies**
   ```bash
   npm install
   ```

6. **Verify Installation**
   ```bash
   python check_phase1_dependencies.py
   python check_devices.py
   ```

## 🏗️ Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (Next.js)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Iris Orb    │  │  Wheel View  │  │  Chat View   │     │
│  │  Navigation  │  │  Dashboard   │  │  Interface   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                  │                  │             │
│         └──────────────────┴──────────────────┘             │
│                            │                                │
│                    WebSocket Connection                     │
└────────────────────────────┼────────────────────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────┐
│                    Backend (FastAPI)                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              IRIS Gateway (Message Router)           │  │
│  └──────────────────────────────────────────────────────┘  │
│         │                  │                  │             │
│  ┌──────▼──────┐  ┌────────▼────────┐  ┌────▼──────┐     │
│  │  WebSocket  │  │  State Manager  │  │  Session  │     │
│  │  Manager    │  │  (Persistence)  │  │  Manager  │     │
│  └─────────────┘  └─────────────────┘  └───────────┘     │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Agent Kernel (Orchestrator)             │  │
│  │  ┌────────────────┐      ┌────────────────┐         │  │
│  │  │  Model Router  │      │  Tool Bridge   │         │  │
│  │  │                │      │  (MCP Tools)   │         │  │
│  │  └────────────────┘      └────────────────┘         │  │
│  └──────────────────────────────────────────────────────┘  │
│         │                           │                       │
│  ┌──────▼──────┐           ┌────────▼────────┐            │
│  │  GGUF LLM   │           │  MCP Servers    │            │
│  │  (user's    │           │  - Browser      │            │
│  │   model,    │           │  - File Mgr     │            │
│  │   port 8082)│           │  - System       │            │
│  │             │           │  - App Launch   │            │
│  │  LFM 2.5    │           │  - Vision       │            │
│  │  (tool calls│           └─────────────────┘            │
│  └─────────────┘                                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                   Voice Pipeline                     │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │  │
│  │  │ Porcupine│  │   STT    │  │   TTS            │  │  │
│  │  │ Wake Word│  │ (Whisper)│  │(F5-TTS / Piper)  │  │  │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Component Overview

#### Frontend Components
- **IrisOrb**: Central navigation orb with voice activation
- **WheelView**: Hexagonal navigation interface
- **DarkGlassDashboard**: Main settings dashboard
- **ChatView**: Text-based conversation interface
- **NavigationContext**: Centralized state management

#### Backend Components
- **IRIS Gateway**: Message routing and coordination
- **WebSocket Manager**: Real-time bidirectional communication
- **State Manager**: Settings persistence and synchronization
- **Session Manager**: Multi-client session handling
- **Agent Kernel**: AI agent orchestration
- **Model Router**: Routes requests between GGUF LLM and LFM instruct (tool calls)
- **Tool Bridge**: MCP tool execution
- **Voice Pipeline**: End-to-end audio processing

### Model Architecture

| Model | Role | Size | Notes |
|-------|------|------|-------|
| **Any GGUF model** | Reasoning & conversation | User's choice | Served via llama-server (ik_llama.cpp, preferred) or llama-cpp-python on port 8082; selected in Models Browser |
| **lfm2.5-1.2b-instruct** | Tool execution | ~1.2 GB | Structured tool calls only; optional |
| **LFM2.5-VL-1.6B** | Vision / GUI | ~1 GB | Optional; served via llama-server on port 8081 |

**Communication Flow:**
1. User input → GGUF LLM (your chosen model) analyzes and responds
2. When tools needed → LFM2.5-1.2B-Instruct generates structured tool calls
3. Tool Bridge → MCP Servers: Execute operations
4. Results returned → LLM incorporates and responds

## ⚙️ Configuration

### Backend Configuration

**Environment Variables** (`.env`):
```env
# Server
BACKEND_HOST=localhost
BACKEND_PORT=8000

# Picovoice (Wake Word)
PICOVOICE_ACCESS_KEY=your_key_here

# Models
MODEL_PATH=./models
DEVICE=cuda  # or 'cpu'

# Audio
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1

# Logging
LOG_LEVEL=INFO
LOG_DIR=backend/logs
```

### Agent Configuration

**File**: `backend/agent/agent_config.yaml`

```yaml
models:
  # Tool execution — LFM2.5-1.2B-Instruct handles structured tool calls
  - id: "executor"
    path: "./models/LFM2.5-1.2B-Instruct"
    capabilities: ["tool_execution", "instruction_following"]
    constraints:
      device: "cpu"
      dtype: "float32"
    optional: true

  # GGUF local inference — user picks model in Settings → Models Browser
  # Served via llama-cpp-python on port 8082 (never auto-loaded)
  - id: "gguf_local"
    path: null
    capabilities: ["conversation", "tool_execution", "reasoning"]
    constraints:
      inference_server_url: "http://127.0.0.1:8082/v1"
      auto_load: false
    optional: true

  # Vision (optional) — LFM2.5-VL via llama-server on port 8081
  - id: "vision"
    path: null
    capabilities: ["vision", "gui_interaction"]
    constraints:
      vision_server_url: "http://localhost:8081/v1"
      auto_load: false
    optional: true

communication:
  timeout: 30.0
  max_retries: 3
```

### Voice Configuration

Wake word models are stored in `models/wake_words/`:
- `hey-iris_en_windows_v4_0_0.ppn` - Custom "hey iris" wake word

Supported wake phrases:
- "hey iris" (custom)
- "jarvis" (built-in)
- "computer" (built-in)
- "bumblebee" (built-in)
- "porcupine" (built-in)

### Frontend Configuration

**WebSocket URL**: Configured in `hooks/useIRISWebSocket.ts`

```typescript
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
```

## 🛠️ Development

### Project Structure

```
IRISVOICE/
├── app/                    # Next.js app router
│   ├── dashboard/         # Main dashboard page
│   └── menu-window/       # Menu window page
├── components/            # React components
│   ├── iris/             # Iris Orb and navigation
│   ├── wheel-view/       # Wheel navigation system
│   ├── fields/           # Field rendering components
│   ├── features/         # Feature components
│   └── ui/               # UI primitives
├── contexts/             # React contexts
│   ├── NavigationContext.tsx
│   ├── BrandColorContext.tsx
│   └── TransitionContext.tsx
├── hooks/                # Custom React hooks
│   ├── useIRISWebSocket.ts
│   ├── useAudioDevices.ts
│   └── useNavigationSettings.ts
├── lib/                  # Utility libraries
│   ├── performance/      # Performance optimizations
│   └── utils.ts          # Helper functions
├── backend/              # Python FastAPI backend
│   ├── agent/           # AI agent system
│   │   ├── agent_kernel.py
│   │   ├── model_router.py
│   │   ├── vps_gateway.py
│   │   └── personality.py
│   ├── voice/           # Voice pipeline
│   │   ├── audio_engine.py
│   │   ├── voice_pipeline.py
│   │   └── porcupine_detector.py
│   ├── tools/           # MCP tool integration
│   │   └── vision_system.py
│   ├── performance/     # Performance optimizers
│   ├── core/            # Core infrastructure
│   ├── sessions/        # Session management
│   ├── monitoring/      # Logging and monitoring
│   ├── memory/          # Memory subsystem
│   │   ├── mycelium/    # Coordinate-graph memory layer
│   │   │   ├── store.py      # CoordinateStore (node/edge CRUD, struct pack)
│   │   │   ├── navigator.py  # CoordinateNavigator (traversal, author_edge)
│   │   │   ├── extractor.py  # CoordinateExtractor (text→coords, toolpath)
│   │   │   ├── scorer.py     # EdgeScorer + MapManager (decay, condense)
│   │   │   ├── profile.py    # ProfileRenderer (prose sections)
│   │   │   ├── landmark.py   # LandmarkCondenser + LandmarkIndex
│   │   │   ├── resonance.py  # EpisodeIndexer + ResonanceScorer
│   │   │   ├── kyudo.py      # HyphaGateway (channel security, MCP trust)
│   │   │   └── spaces.py     # Canonical space definitions + constants
│   │   └── tests/       # 139-test requirement-anchored test suite
│   ├── main.py          # FastAPI application
│   ├── iris_gateway.py  # Message router
│   ├── state_manager.py # State persistence
│   └── ws_manager.py    # WebSocket manager
├── models/              # AI model files
│   ├── LFM2.5-1.2B-Instruct/   # tool execution (optional)
│   ├── LFM2.5-VL-1.6B/         # vision (optional)
│   └── wake_words/
├── tests/               # Test suites
│   ├── integration/     # Integration tests
│   ├── property/        # Property-based tests
│   └── performance/     # Performance tests
├── docs/                # Documentation
│   ├── api/            # API documentation
│   └── plans/          # Design documents
├── .env                 # Environment variables
├── package.json         # Node.js dependencies
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

### Running in Development Mode

**Backend with hot reload:**
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend with hot reload:**
```bash
npm run dev
```

**Concurrent development:**
```bash
npm run dev:backend & npm run dev:frontend
```

### Code Style

**Python:**
- Follow PEP 8 style guide
- Use type hints
- Document with docstrings

**TypeScript/React:**
- Follow ESLint configuration
- Use TypeScript strict mode
- Document complex components

## 🧪 Testing

### Running Tests

**Backend Tests:**
```bash
# All tests
python -m pytest backend/memory/tests/ -v

# Mycelium layer tests only
python -m pytest backend/memory/tests/test_mycelium_*.py -v

# With coverage
python -m pytest backend/memory/tests/ --cov=backend.memory --cov-report=html
```

**Frontend Tests:**
```bash
# All tests
npm test

# Specific test files
npm test -- tests/wheelview.test.js

# With coverage
npm test -- --coverage
```

### Mycelium Layer — Test Coverage

The Mycelium coordinate-graph memory layer (`backend/memory/mycelium/`) has a comprehensive, requirement-anchored test suite with **139 tests** across 12 test modules. All tests pass against `sqlite3` in-memory databases (no SQLCipher dependency required for testing).

| Module | Tests | Requirements covered |
|--------|-------|----------------------|
| `test_mycelium_requirements.py` | 21 | Req 1.1–1.11, 2.1–2.11, 4.12, 4.26, 7.3–7.6, 15.29–15.30 |
| `test_mycelium_store.py` | 9 | Req 3.1–3.8 (CoordinateStore dedup, nearest-node, edge clamping) |
| `test_mycelium_navigator.py` | 11 | Req 5.1–5.10, 6.1–6.7 (traversal, encoding formats, author_edge, record_path_outcome) |
| `test_mycelium_scorer.py` | 10 | Req 7.1–7.10 (hit/partial/miss deltas, highway bonus, decay formula, condense, space order) |
| `test_mycelium_extractor.py` | 12 | Req 4.1–4.24 (conduct/style/domain patterns, session confidence formula, circular mean, toolpath window) |
| `test_mycelium_profile.py` | 8 | Req 4.17, 10.1–10.12 (ProfileRenderer, context freshness threshold) |
| `test_mycelium_landmark.py` | 8 | Req 8.1–8.14 (LandmarkCondenser, nullify, promote-to-permanent, merge, absorbed flag) |
| `test_mycelium_resonance.py` | 9 | Req 11.1–11.12 (ResonanceScorer, formula, landmark bonus, suppression, space exclusion) |
| `test_mycelium_kyudo_security.py` | 11 | Req 15.1–15.30 (channel assignment, CellWall zones, trust cap, quorum sensor, MCP pin) |
| `test_mycelium_kyudo_precision.py` | 9 | Req 13.1–13.9 (task classifier, predictive loader, delta encoder, micro-abstract) |
| `test_mycelium_topology.py` | 7 | Req 9.1–9.8 (topology maintenance, chart positions, trajectory) |
| `test_mycelium_integration.py` | 4 | End-to-end interface contract |

**Key invariants verified by tests:**
- Coordinate byte order (big-endian) for cross-platform consistency
- `HyphaChannel` IntEnum values used correctly in security guards
- Stale context (freshness < 0.10) filtered from profile renders (Req 4.17)
- `author_edge` always uses initial score 0.4 — not configurable by agents (Req 5.8)
- `partial` outcome delta = +0.02, `hit` = +0.05, `miss` = -0.08 (Req 7.1)
- Highway bonus (+0.01) fires only on threshold crossing, not when already above (Req 7.4)
- Decay formula: `score -= rate * days_idle` (Req 7.2)
- Toolpath space excluded from RESONANCE_SPACES and profile renders (Req 11.5)
- All 13 schema tables present with required columns (`absorbed`, `source_channel`, `delta_compressed`)

### Test Coverage

- **Integration Tests**: End-to-end workflow testing
- **Property Tests**: Property-based testing with Hypothesis
- **Performance Tests**: Latency and throughput validation
- **Unit Tests**: Component-level testing

### Performance Benchmarks

| Metric | Target | Status |
|--------|--------|--------|
| WebSocket Latency | <50ms p95 | ✅ Passing |
| Agent Response | <5s p95 | ✅ Passing |
| Voice Processing | <3s p95 | ✅ Ready |
| State Persistence | <100ms | ✅ Ready |
| Frontend Rendering | <16ms (60 FPS) | ✅ Ready |
| Tool Execution | <10s or timeout | ✅ Ready |
| Concurrent Connections | ≥100 | ✅ Passing |

## 📚 Documentation

### User Guides

- **[Inference Mode Selection Guide](./docs/USER_GUIDE_INFERENCE_MODE.md)**: Choose between Local, VPS, or OpenAI inference
- **[Dual-LLM Model Selection Guide](./docs/USER_GUIDE_MODEL_SELECTION.md)**: Configure reasoning and tool execution models
- **[Wake Word Configuration Guide](./docs/USER_GUIDE_WAKE_WORDS.md)**: Set up custom wake words
- **[Cleanup System Guide](./docs/USER_GUIDE_CLEANUP.md)**: Analyze and remove unused files

### Developer Guides

- **[Lazy Loading Architecture](./docs/DEVELOPER_LAZY_LOADING.md)**: Model loading/unloading implementation
- **[Model-Agnostic Architecture](./docs/DEVELOPER_MODEL_AGNOSTIC.md)**: Agent capabilities across all inference modes
- **[Agent Architecture](./docs/AGENT_ARCHITECTURE.md)**: Dual-LLM system design
- **[System Overview](./docs/SYSTEM_OVERVIEW.md)**: Complete system architecture
- **[UI Architecture](./docs/UI_ARCHITECTURE.md)**: Frontend component structure

### API Documentation

- **[WebSocket Messages](./docs/api/websocket-messages.md)**: Complete WebSocket protocol reference
- **[Backend Classes](./docs/api/backend-classes.md)**: Backend component documentation
- **[Configuration Guide](./docs/api/configuration.md)**: Configuration options
- **[Data Models](./docs/api/data-models.md)**: Data structure definitions
- **[API Documentation](./API_DOCUMENTATION.md)**: Complete API reference

### Operations Guides

- **[Deployment Guide](./DEPLOYMENT_GUIDE.md)**: Production deployment instructions
- **[Troubleshooting Guide](./TROUBLESHOOTING_GUIDE.md)**: Common issues and solutions
- **[Performance Optimization](./PERFORMANCE_OPTIMIZATION_SUMMARY.md)**: Performance tuning guide
- **[Feature Summary](./docs/FEATURE_SUMMARY.md)**: Recent features and improvements

### Component Documentation

- **[Backend Core README](./backend/core/README.md)**: Core infrastructure documentation
- **[Agent Personality](./backend/agent/README_PERSONALITY.md)**: Personality system guide
- **[Model System](./backend/agent/README_MODEL_SYSTEM.md)**: Dual-LLM architecture
- **[Audio Engine](./backend/voice/README_AUDIO_ENGINE.md)**: Voice pipeline documentation
- **[Porcupine Setup](./backend/voice/README_PORCUPINE.md)**: Wake word configuration

### API Endpoints

**WebSocket:**
- `ws://localhost:8000/ws/{client_id}?session_id={optional_session_id}`

**REST API:**
- `GET /health` - Health check
- `GET /api/agent/status` - Agent status
- `GET /docs` - Swagger UI
- `GET /redoc` - ReDoc documentation

**WebSocket Message Types**

**Client → Server:**
- `select_category` - Navigate to category
- `select_subnode` - Select subnode
- `update_field` - Update field value (including inference_mode, model selection)
- `text_message` - Send text message to agent
- `voice_command_start` - Start voice recording
- `voice_command_end` - Stop voice recording
- `get_wake_words` - Request wake word list
- `select_wake_word` - Select wake word file
- `get_available_models` - Request available models
- `get_cleanup_report` - Request cleanup analysis
- `execute_cleanup` - Execute cleanup

**Server → Client:**
- `initial_state` - Complete state on connection
- `field_updated` - Field update confirmation
- `text_response` - Agent text response
- `agent_status` - Agent status update (includes inference mode, model selection)
- `audio_level` - Voice activity level
- `validation_error` - Field validation error
- `wake_words_list` - Available wake word files
- `wake_word_selected` - Wake word selection confirmed
- `available_models` - Available models from all inference sources
- `inference_mode_changed` - Inference mode change confirmed
- `model_selection_updated` - Model selection change confirmed
- `cleanup_report` - Cleanup analysis result
- `cleanup_result` - Cleanup execution result

For complete message documentation, see [WebSocket Messages](./docs/api/websocket-messages.md).

## 🔧 Troubleshooting

### Common Issues

**Backend won't start:**
```bash
# Check Python version
python --version  # Should be 3.10+

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Check port availability
netstat -an | findstr 8000  # Windows
lsof -i :8000  # macOS/Linux
```

**Models not loading:**
```bash
# Models are NOT loaded automatically on startup (lazy loading by design)
# Select inference mode in Agent settings first

# For Local Models mode:
# Open Settings → Models Browser → pick a GGUF model → click Load
# GPU RAM needed depends on your chosen model (e.g. 8B Q4_K_M ≈ 5 GB VRAM)
nvidia-smi

# For VPS/OpenAI modes:
# No local models needed — configure endpoint in Agent settings
```

**Wake word not detected:**
1. Check microphone permissions
2. Verify Picovoice access key in `.env`
3. Adjust detection sensitivity in settings
4. Test with `python check_devices.py`

**WebSocket connection fails:**
1. Verify backend is running
2. Check firewall settings
3. Ensure correct WebSocket URL
4. Check browser console for errors

For more detailed troubleshooting, see [TROUBLESHOOTING_GUIDE.md](./TROUBLESHOOTING_GUIDE.md).

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new features
5. Ensure all tests pass
6. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- **Picovoice** - Porcupine wake word detection
- **Liquid AI** - LFM models
- **FastAPI** - Backend framework
- **Next.js** - Frontend framework
- **Framer Motion** - Animation library

## 📞 Support

For issues and questions:
- Check the [Troubleshooting Guide](./TROUBLESHOOTING_GUIDE.md)
- Review the [API Documentation](./API_DOCUMENTATION.md)
- Open an issue on GitHub

---

**Version**: 4.5.0
**Last Updated**: April 2026
**Status**: Production Ready ✅
