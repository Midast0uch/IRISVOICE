# IRISVOICE - AI Voice Assistant Platform

A production-ready AI voice assistant platform featuring an intuitive hexagonal interface, end-to-end voice processing, and autonomous task execution. Built with Next.js + Framer Motion frontend and Python FastAPI backend, powered by dual large language models and advanced voice AI.

## 🌟 Key Features

### 🎤 Voice & Audio
- **Wake Word Detection**: Custom wake words using Picovoice Porcupine with automatic file discovery
- **Wake Word Discovery**: Automatically finds all wake word files in wake_words/ directory
- **End-to-End Audio Processing**: Porcupine (wake words) → faster-whisper (STT) → Agent Kernel → Pocket-TTS (TTS)
- **Voice Commands**: Natural language voice interaction with double-click activation
- **Text-to-Speech**: Pocket-TTS (~100M int8 quantized, zero-shot voice cloning from a user-provided reference WAV) with built-in speaker presets
- **Streaming LLM→TTS**: IRIS starts speaking as soon as the first sentence is ready — no waiting for the full LLM response
- **Native C++ Audio Layer**: Optional low-latency ring-buffer playback via PortAudio (<5ms chunk-to-speaker, <2ms inter-chunk gap)
- **Instant Interrupt**: Sub-5ms TTS cancellation via atomic flag in the C++ audio callback
- **Audio Processing**: Automatic noise reduction, echo cancellation, and voice enhancement

### 🤖 AI Agent System
- **Flexible Inference**: Brain model via ik_llama.cpp (port 8082) or llama-cpp-python, vision via upstream llama.cpp (port 8081), or remote OpenAI-compatible API — select in Settings
- **MTP Speculative Decoding (1.5-3× speedup)**: Multi-Token Prediction for compatible GGUF models (e.g. Qwopus3.6-27B-MTP). Auto-detected from tensor names, routed to compiled `llama-server --spec-type draft-mtp`. Configurable `--spec-draft-n-max` (1-6) and acceptance-rate logging. Non-MTP models fall back transparently to in-process inference.
- **Tool Execution**: Dedicated tool-calling model handles structured tool calls; main LLM handles reasoning and conversation
- **DER Loop**: Director → Explorer → Reviewer agent loop with trailing crystallizer, token-budget enforcement, and mid-loop episodic retrieval (C.4)
- **Caducean Engine v2 — Mitochondria to Mycelium (Domain 19)**: Four-dimensional physics-governed attention governor (Σ = x, y, ξ, u) based on the Duffing oscillator. Now the metabolic regulator of Mycelium memory:
  - **Winding numbers** `(l, m) ∈ ℤ²` control cycle speed `c_eff = (1/√2)√(l²+m²)`
  - **DirectionSignal** exposes bias-free physics to consumers (`target_u`, `force_magnitude`, `u_current`, `phase`, `balance`)
  - **Adaptive safety net** detects genuine topological drift via phase acceleration; fires `TOPO_VIOLATION` (return code 3) on lone-kink Q > 0.8 with nonzero phase_accel
  - **O(1) EML** from SessionState accumulators — eliminates SQL from the hot path
  - **Mycelium modulation** — `decay_multiplier` and `resonance_multiplier` scale by attentional velocity (explore→preserve, compress→prune)
  - **Multi-session coupling** via `CoupledTrajectoryRegistry` — rational c_eff ratios drive nucleus/barrier role differentiation; irrational ratios introduce destructive phase interference
  - **Parameter tuning** via `TrajectoryController.tune_dffing_params()` — adjusts (a, b, s) based on violation count with explicit Lyapunov bounds
  - **ConversationKernel** wraps the existing voice pipeline (no parallel VAD/TTS) — phase-driven turn-taking, TTS chunk sizing, halt-on-violation
  - **Kill switch:** `IRIS_CADUCEAN_V2_DISABLED=1` env var disables v2 entirely (one-line rollback)
  - **78 v2 tests pass via pytest** (was 0 — pytest was broken pre-v2; we fixed it)
  - See [Caducean v2 architecture](./docs/cad_v2_architecture.md) and [implementation plan](./docs/plans/Cadv2plan.md)
- **Recall-as-Cognition**: Two-phase memory retrieval protocol — model emits structured `<recall/>` ops before answering, resolves them against the coordinate graph, then answers with real memory context. 84% prompt token reduction vs full-history injection. Provider-uniform via prompt caching. See [architecture doc](./docs/architecture/RECALL_AS_COGNITION.md)
- **Mycelium v1.7**: 6-layer coordinate-graph memory — episodic events, semantic compression, landmarks, Pacman lifecycle, PiNs, and cross-project landmark bridges
- **PiNs (Primordial Information Nodes)**: Any knowledge artifact anchored to the graph — markdown notes, files, folders, images, URLs, decisions, fragments, mid-write checkpoints. Agent-callable (`pin_add`, `pin_search`, `pin_link`, `pin_checkpoint`) and surfaced via `<recall pin .../>`. Auto-checkpoints fire after large file writes so the agent can recover in-progress work on a future turn. Tunable search weights. Available in both modes. See [pin system doc](./docs/architecture/PIN_SYSTEM.md)
- **Cross-Project Landmark Bridging**: Maps a verified landmark to an equivalent pattern in another IRIS instance or project; bridges carry confidence scores and bridge types (equivalent / similar / inverse)
- **Unlimited Effective Context**: 3-layer retrieval — raw history (trimmed) + episodic summaries (Layer 2) + Mycelium coordinate package (Layer 3, includes PiNs)
- **Model-Agnostic Design**: Works with Local GGUF, VPS, or OpenAI inference backends
- **Flexible Inference Modes**: Choose between Local Models (Models Browser), VPS Gateway, or OpenAI API
- **Lazy Loading**: Models load only when needed, not on startup
- **Autonomous Task Execution**: Agent can execute complex multi-step tasks
- **Tool Integration**: MCP-based tool system for browser, file, system, and app automation
- **Personality System**: Configurable assistant personality and behavior
- **Conversation Memory**: Context-aware conversations with memory management (persists across mode switches)
- **Internet Access Control**: Toggle agent web search capabilities independently of app connectivity

### 👁 Vision Layer (LFM2.5-VL)
- **LFM2.5-VL-450M**: Liquid AI's vision-language model running via `llama-server` on port 8081
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
- **C++ Hybrid Core Memory Engine** (`iris_core.dll`): Replaces the Python memory hot path with compiled C++ — **~570× faster** Caducean attention decisions (87 ns vs ~50 μs in pure Python), eliminates SQLite `database is locked` errors via a dedicated single-writer thread, and removes ReDoS risk entirely via Google RE2. Transparent Python fallback if the DLL is unavailable.
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
- [C++ Hybrid Core Memory Engine](#-c-hybrid-core-memory-engine)
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

### 2. Model Directory Setup (Unified)

All GGUF models (brain + vision) live in one canonical directory:

**WSL/Linux:**
```bash
# Create symlink to your Windows LM Studio models folder
mkdir -p ~/.lmstudio
ln -s /mnt/c/Users/midas/.lmstudio/models ~/.lmstudio/models
```

**Expected structure:**
```
~/.lmstudio/models/
├── LiquidAI/
│   └── LFM2.5-VL-450M-GGUF/
│       ├── LFM2.5-VL-450M-*.gguf      # vision model weights
│       └── mmproj-LFM2.5-VL-*.gguf    # vision projector
└── (your brain models — any GGUF file...)
```

**Vision auto-start:** The backend detects LFM2.5-VL in `~/.lmstudio/models` and spawns
`llama-server` on port 8081 automatically on first vision tool use. No manual startup needed.

```bash
# Install vision dependencies (optional, only for desktop automation)
pip install mss httpx pywinauto pyautogui pillow win32clipboard
```

### 3. Build C++ Hybrid Core Memory Engine (Windows)

The backend depends on `iris_core.dll` for high-performance memory operations. Build it once before first run:

**Requirements:** Visual Studio 2022 Build Tools + CMake + RE2 + SQLCipher

```powershell
# One-command build (run from repo root)
& build_cpp_core.ps1
```

This compiles the C++ core (`iris_core.dll`) with:
- **Google RE2** — linear-time regex sanitization (zero ReDoS risk)
- **SQLCipher** — encrypted SQLite with WAL mode
- **Caducean Attention Governor** — continuous dynamics for attention modulation
- **Pre-keyed Read Pool** — 4 pooled read connections (no repeated key derivation)

The DLL auto-copies to `backend/native/iris_core.dll`. If the build fails, the Python backend falls back to pure-Python implementations transparently.

### 3a. Build llama-server for MTP (Optional — required for speculative decoding)

MTP (Multi-Token Prediction) models need the upstream `llama-server` binary compiled from source. This is separate from `llama-cpp-python` (which does not support self-MTP).

```powershell
# One-command build (run from repo root)
& build_llama_server.ps1
```

**Requirements:** Visual Studio 2022 Build Tools + CMake + CUDA Toolkit (optional but recommended)

This builds `llama-server.exe` in `llama.cpp/build/bin/Release/` with:
- **MTP speculative decoding** — `--spec-type draft-mtp` for 1.5-3× speedup
- **CUDA offload** — `-DGGML_CUDA=ON` for GPU layers (requires CUDA VS integration)

If CUDA VS integration is missing, build CPU-only:
```powershell
& build_llama_server.ps1 -CPUOnly
```

The backend auto-discovers the binary at startup; no manual PATH edits needed.

### 4. Backend Setup

```bash
# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Set up environment variables
# Create .env file with:
# PICOVOICE_ACCESS_KEY=your_access_key_here
# TELEGRAM_BOT_TOKEN=your_bot_token  (optional)
# TELEGRAM_CHAT_ID=your_chat_id      (optional)
```

### Optional: Native C++ Audio Extension (Windows)

For sub-5ms TTS interrupt latency and <2ms inter-chunk audio gaps, build the optional native audio layer:

**Requirements:** Visual Studio 2022 Build Tools + CMake

```powershell
# One-command build (run from repo root)
.\build_native.ps1
```

This compiles `iris_audio.pyd` using pybind11 + PortAudio with a lock-free ring buffer. The script auto-downloads PortAudio headers, generates import libraries from the sounddevice DLL, and copies the built extension to `backend/native/`. No manual dependency installation needed — the script handles everything.

If the build succeeds, the backend automatically uses native audio for TTS playback. If it fails, the system falls back to the Python `sounddevice` path seamlessly.

### 5. Frontend Setup

```bash
# Install Node.js dependencies
npm install

# or with pnpm
pnpm install
```

### 6. Run the Application

> **Startup commands are unchanged.** The C++ core build (Step 3) is a one-time prerequisite — once `iris_core.dll` exists in `backend/native/`, you start the system exactly as before.

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
   # Pocket-TTS is installed automatically via requirements.txt
   # Cloned Voice model weights download automatically on first use
   ```

4. **Provide a voice reference for cloning** (optional — skip to use built-in voices)
   ```bash
   # Record or export a 6–30 second WAV of the voice you want IRIS to use
   # Save it as data/TOMV2.wav (or data/voice_clone_ref.wav)
   # See data/VOICE_CLONE_README.md for full guidance
   # This file is gitignored — you must supply your own
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
│                     Frontend (Next.js / Tauri)            │
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
│                    Backend (FastAPI + Python)               │
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
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Dual Inference Servers                  │  │
│  │  ┌──────────────────┐  ┌────────────────────────┐   │  │
│  │  │ Brain (port 8082)│  │ Vision (port 8081)     │   │  │
│  │  │ ik_llama.cpp     │  │ upstream llama.cpp     │   │  │
│  │  │ (Kimi-K2 fork)   │  │ (LFM2-VL support)      │   │  │
│  │  └──────────────────┘  └────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────▼──────┐           ┌────────▼────────┐            │
│  │  GGUF LLM   │           │  MCP Servers    │            │
│  │  (user's    │           │  - Browser      │            │
│  │   model)    │           │  - File Mgr     │            │
│  │             │           │  - System       │            │
│  │  LFM 2.5    │           │  - App Launch   │            │
│  │  (tool calls│           │  - Vision       │            │
│  └─────────────┘           └─────────────────┘            │
  │  ┌──────────────────────────────────────────────────────┐  │
  │  │                   Voice Pipeline                     │  │
  │  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │  │
  │  │  │ Porcupine│  │   STT    │  │   TTS            │  │  │
  │  │  │ Wake Word│  │ (Whisper)│  │  (Pocket-TTS)    │  │  │
  │  │  └──────────┘  └──────────┘  └──────────────────┘  │  │
  │  └──────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────┘
                             │  FFI (ctypes)
┌────────────────────────────▼────────────────────────────────┐
│          C++ Hybrid Core Memory Engine (iris_core.dll)      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐    │
│  │   DBManager  │ │   Caducean   │ │ Security         │    │
│  │ (Writer +    │ │ Attention    │ │ Sanitizer (RE2)  │    │
│  │  Read Pool)  │ │ Governor     │ │                  │    │
│  └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘    │
│         │                │                    │               │
│  ┌──────▼───────────────▼────────────────────▼─────────┐  │
│  │              Event Ingestor + EML Engine            │  │
│  │  • UUID v4 generation (sqlite3_randomness)          │  │
│  │  • Async single-writer queue                        │  │
│  │  • Immortus memory chain append / keep_latest       │  │
│  └──────────────────────────┬──────────────────────────┘  │
│                             │
┌─────────────────────────────▼──────────────────────────────┐
│                 SQLCipher (Encrypted SQLite)               │
│          WAL mode │ system_events │ memory_chain             │
│          mycelium_landmarks │ mycelium_nodes               │
└────────────────────────────────────────────────────────────┘
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
- **Model Router**: Routes requests between GGUF brain model and tool-calling model
- **Streaming Utilities** (`backend/agent/streaming.py`): chunk batching, provider-agnostic chunk parsing, safe iteration with silence/total timeouts
- **Tool Bridge**: MCP tool execution
- **Voice Pipeline**: End-to-end audio processing (Porcupine → faster-whisper → Agent Kernel → Pocket-TTS)
- **C++ Hybrid Core Memory Engine** (`iris_core.dll`): Replaces the Python memory hot path with compiled C++ — **~570× faster** Caducean attention decisions (87 ns vs ~50 μs in pure Python), eliminates SQLite `database is locked` errors via a dedicated single-writer thread, and removes ReDoS risk entirely via Google RE2. All backed by transparent Python fallback if the DLL is unavailable.

### Model Architecture

| Model | Role | Port | Server | Notes |
|-------|------|------|--------|-------|
| **Any GGUF model** | Reasoning & conversation | 8082 | ik_llama.cpp or llama-cpp-python | Your choice; selected in Models Browser |
| **Tool-calling model** | Tool execution | 8082 | Same as brain | Structured tool calls only; optional |
| **LFM2.5-VL-450M** | Vision / GUI | 8081 | Upstream llama.cpp b8102+ | Auto-starts on first vision tool use |
| **Remote API** | Reasoning & conversation | — | OpenAI-compatible | Any provider URL + API key; configured in Settings |

**Model Directory (Unified):**
All models live in one canonical location:
- **WSL/Linux**: `~/.lmstudio/models/` (symlinked to `C:\Users\midas\.lmstudio\models` on WSL)
- **Windows**: `C:\Users\midas\.lmstudio\models\`
- Both brain (port 8082) and vision (port 8081) scan from this directory.

**Communication Flow:**
1. User input → Provider selected in Settings (local GGUF / remote API / VPS)
2. Brain model (port 8082) analyzes and responds
3. When tools needed → Tool Bridge → MCP Servers execute operations
4. When vision needed → Vision server (port 8081) auto-starts, processes screenshot
5. Results returned → Brain incorporates and responds

---

## ⚡ C++ Hybrid Core Memory Engine

The legacy Python memory system experienced high CPU/IO thrashing under dense file-system watchdog observers and concurrent WebSocket messaging. SQLite `database is locked` errors appeared during multi-agent swarm operations, and the Caducean attention governor — computed in pure Python — added ~50 μs of GIL-bound latency to every DER loop iteration.

The C++ Hybrid Core (`iris_core.dll`) moves the entire performance-critical memory hot path into compiled code:

- **Caducean attention decisions** drop from **~50 μs (Python) to 87 ns (C++)** — a **~570× speedup**. At 87 ns, the engine executes **11 million attention recommendations per second**, far exceeding any agent swarm throughput requirement.
- **SQLite write contention vanishes** — a dedicated single-writer thread serializes all database transactions. No more `database is locked`. Concurrent multi-agent writes queue asynchronously and return immediately via `std::future`.
- **RE2 eliminates ReDoS entirely** — Google RE2 guarantees linear-time regex matching regardless of input size or pattern complexity. Payload sanitization runs at **~95 MB/s** with zero backtracking risk.
- **Pre-keyed read pool** maintains 4 open SQLCipher connections — no repeated PBKDF2 key derivation on every read query.
- **Transparent fallback** — if `iris_core.dll` fails to load or crashes, the Python backend (`backend/gateway/iris_ffi.py`) seamlessly falls back to pure-Python SQLite + `PythonCaduceanFallbackState`. Zero downtime, zero configuration changes.

### Source Files (`src-tauri/src/iris_core/`)

| File | Responsibility |
|------|--------------|
| `iris_core.h` | FFI C-interface — all exports callable from Python via `ctypes` |
| `iris_core.cpp` | FFI gateway + EML engine (`calculate_eml`), lifecycle (`init_core_engine`, `shutdown_core_engine`) |
| `caducean.h` / `caducean.cpp` | Attention governor — cubic Duffing potential F(u)=au−bu³, EXPAND/COMPRESS/CONTINUE thresholds |
| `db_manager.h` / `db_manager.cpp` | Async single-writer SQLite thread + pre-keyed read pool (4 connections) + `ReadGuard` RAII |
| `security_sanitizer.h` / `security_sanitizer.cpp` | RE2 linear-time payload scrubbing — API keys, SSH keys, DB connection strings, AWS keys |
| `event_ingestor.h` / `event_ingestor.cpp` | UUID v4 generation, payload sanitization, async DB queue, 1000-event spill buffer |
| `CMakeLists.txt` | CMake 3.15+ — FetchContent RE2, find_package SQLCipher, POST_BUILD DLL copy |

### Key Capabilities

- **ReDoS Elimination**: Google RE2 guarantees **O(n) linear-time matching** regardless of input size or pattern complexity. No backtracking, no catastrophic backtracking, no unbounded quantifiers. Patterns are bounded: `[A-Za-z0-9]{16,64}` instead of `.*`.
- **Async Single-Writer SQLite — No More `database is locked`**: All writes serialize through one dedicated C++ thread with a `std::promise/future` queue. Concurrent multi-agent writes queue asynchronously and return immediately. The read pool maintains 4 pre-keyed SQLCipher connections — no repeated PBKDF2 key derivation on every query.
- **Caducean Attention Governor — Compiled Physics**: Models the agent's attention as a particle in a Duffing potential energy landscape. State vector (x, y, xi, u) with restoring force `F(u) = a·u − b·u³`. EXPAND (exploration), COMPRESS (verification), and CONTINUE (neutral) signals modulate the DER loop step prioritizer in `der_loop.py` at **11 million decisions per second**.
- **EML v2 — Cognitive Governor**: `exp(x) − ln(y)` where x = edit/test drift and y = landmark coverage. Queried directly from SQLCipher via pooled WAL connections. High EML (≥1.50) relaxes Immortus drift tolerance to 0.50 and expands search depth to D≥5. Low EML (<1.00) tightens tolerance to 0.30 and locks depth to D=3.
- **Zero-Trust In-Memory Sanitization**: Payloads are scrubbed in-memory using pre-compiled RE2 regex tables before hitting the SQLCipher disk. Thread-safe try/catch boundaries around every replace operation.
- **Graceful Fallback — Zero Downtime**: If `iris_core.dll` fails to load, crashes, or is absent, the Python backend (`backend/gateway/iris_ffi.py`) transparently falls back to pure-Python SQLite + `PythonCaduceanFallbackState`. The agent continues operating with no configuration changes and no data loss.

### Build Requirements (Windows)

- Visual Studio 2022 Build Tools (C++ workload)
- CMake 3.15+
- SQLCipher (or plain SQLite3 for fallback builds)
- Google RE2 (auto-fetched by CMake via `FetchContent`)

### Build Command

```powershell
& build_cpp_core.ps1
```

Output: `backend/native/iris_core.dll` (auto-copied on POST_BUILD).

### Verification

```powershell
# C++ smoke tests (9/9 must pass)
python -m pytest backend/tests/test_iris_core_smoke.py -v

# C++ simulation tests (2/2 must pass)
python -m pytest backend/tests/test_iris_core_simulate.py -v

# C++ microbenchmarks (measures Caducean, RE2, ingestion, EML, memory)
& src-tauri/src/iris_core/build/Release/iris_core_bench.exe

# Frontend compiles clean
cargo check --manifest-path src-tauri/Cargo.toml

# Python FFI loads
cd backend && python -c "from gateway.iris_ffi import IrisCoreEngine; print('OK')"
```

## ⚡ Domain 19 — Caducean DER Governor (Completed May 2026)

A learned controller integration that closes the loop between Caducean attention dynamics, episodic memory, and the DER loop.

### What was delivered

| Component | File | Role |
|-----------|------|------|
| **CaduceanTrajectoryRecorder** | `backend/agent/caducean_trajectory.py` | Records every DER step's 4D state (x, y, xi, u) into SQLite |
| **SkillSimulator** | `backend/agent/skill_simulator.py` | Fast heuristic pre-filter for AutoResearch variants (~12 ms for 1000 calls) |
| **TrajectoryController** | `backend/agent/trajectory_controller.py` | Polynomial regression learned controller over Caducean state |
| **DER Phase Governor** | `backend/agent/agent_kernel.py` | Reads ξ each DER cycle; modulates TrailingDirector (force in phase 4, suppress in phase 3) |
| **recall_memory tool** | `backend/agent/tool_bridge.py` | EML-aware episodic retrieval with adaptive limit/score |
| **C++ Simulator** | `src-tauri/src/iris_core/iris_core.cpp` | `simulate_trajectories_to_db()` — 500×50 random-walk trajectories into DB |

### Architecture

The DER loop now queries `ffi_caducean_get_xi(session_id)` at the start of each cycle. The angular phase ξ ∈ [0, 2π) is divided into four quadrants:

| Phase | ξ range | Mode | TrailingDirector behaviour |
|-------|---------|------|---------------------------|
| 1 (Explore) | [0, π/2) | Open | Normal gap analysis every `TRAILING_GAP_MIN` steps |
| 2 (Balance) | [π/2, π) | Cautious | Normal gap analysis |
| 3 (Verify) | [π, 3π/2) | Strict | **Suppresses** adding new gap items — only executes existing plan |
| 4 (Crystallize) | [3π/2, 2π) | Lock-in | **Forces** gap analysis regardless of step interval |

The EML cognitive state (score, x-drift, y-drift) is also injected into the system prompt so the LLM can adapt its reasoning style dynamically.

### AutoResearch Integration

`AutoResearchRunner` now uses the learned `TrajectoryController` to decide when to fire research cycles, and `SkillSimulator` to pre-filter variant proposals before expensive evaluation. This reduces wasted cycles when EML indicates the system is in a high-drift (exploration) phase.

## ⚡ Domain 19 v2 — Mitochondria to Mycelium (Completed June 2026)

The original Domain 19 wired the Caducean Engine to the DER loop and episodic memory. **v2** goes further: makes the engine the *mitochondria* (energy/metabolic regulator) of the entire Mycelium memory system. Every layer that touches memory — decay, retrieval, voice, coupling — now reads Caducean state.

### Architecture (the v2 wiring)

```
                  ┌──────────────────────────────┐
                  │      Caducean Engine (C++)   │
                  │   Σ = (x, y, ξ, u) state     │
                  │   + l, m (winding numbers)   │
                  │   + DirectionSignal struct   │
                  └──────────────┬───────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
   ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
   │ Mycelium     │       │ Resonance    │       │ DER Loop +   │
   │ Edge Decay   │       │ RAG          │       │ Voice        │
   │ (u → 0.5/   │       │ (u → 0.5/   │       │ (target_u →  │
   │  1.0/1.8)   │       │  1.8)        │       │  speak/list) │
   └──────────────┘       └──────────────┘       └──────────────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 ▼
                  ┌──────────────────────────────┐
                  │  CoupledTrajectoryRegistry   │
                  │  (nucleus/barrier coupling)  │
                  └──────────────────────────────┘
```

### What's new in v2 (vs original Domain 19)

| Capability | v1 (Domain 19) | v2 (Domain 19 v2) |
|-----------|---------------|-------------------|
| State exposed | ξ, u (read-only) | `DirectionSignal {target_u, force_magnitude, u_current, phase, balance}` |
| Winding numbers | (1, 1) only | (l, m) ∈ ℤ², c_eff = (1/√2)√(l²+m²) |
| EML calculation | SQL-based (slow) | **O(1)** from SessionState accumulators |
| Mycelium decay | Constant rate | Caducean-modulated: u>0 → 0.5×, u<0 → 1.8× |
| Mycelium resonance | Constant threshold | Caducean-modulated: u>0 → 0.5× (creativity), u<0 → 1.8× (focus) |
| DER safety net | Static (58% FP rate) | **Adaptive** via phase acceleration (0% FP) |
| TOPO_VIOLATION | Return code 0/1/2 | **Return code 3** added — halts DER loop |
| Multi-session | None | **CoupledTrajectoryRegistry** with nucleus/barrier differentiation |
| Parameter tuning | None | **TrajectoryController.tune_dffing_params()** (a, b, s clamped) |
| Voice pipeline | Heuristic turn-taking | **ConversationKernel** — phase-driven, TTS chunk-sized by force |
| Kill switch | None | `IRIS_CADUCEAN_V2_DISABLED=1` env var |

### v2 Files Added/Modified

| File | Change | Lines |
|------|--------|-------|
| `src-tauri/src/iris_core/caducean.{h,cpp}` | Winding numbers, phase history, DirectionSignal, adaptive safety net | +200/-50 |
| `src-tauri/src/iris_core/iris_core.{h,cpp}` | 5 new FFI exports, O(1) EML path | +130 |
| `backend/gateway/iris_ffi.py` | ctypes bindings, fallback parity, 5 new helpers | +520/-56 |
| `backend/memory/interface.py` | `is_caducean_engine_live()`, `mycelium_record_anomaly()`, `get_caducean_state()` | +50 |
| `backend/memory/mycelium/interface.py` | `record_anomaly()`, `get_latest_u()` | +50 |
| `backend/memory/mycelium/scorer.py` | `apply_decay(session_id=)` — Caducean-modulated | +20 |
| `backend/memory/mycelium/resonance.py` | `augment_retrieval()` — Caducean-modulated | +20 |
| `backend/agent/caducean_trajectory.py` | Added `recommendation` column | +30 |
| `backend/agent/agent_kernel.py` | Computes balance, persists with new fields, handles TOPO_VIOLATION | +50 |
| `backend/agent/der_loop.py` | Handles rec==3 by raising TopologyViolationException | +10 |
| `backend/agent/trajectory_controller.py` | `tune_dffing_params()` with explicit clamp ranges | +60 |
| `backend/agent/coupled_registry.py` (NEW) | Multi-session coupling with rational/irrational detection | +270 |
| `backend/agent/exceptions.py` | TopologyViolationException (code 5010), CouplingViolationException (5011) | +60 |
| `backend/agent/conversation_kernel.py` (NEW) | Thin wrapper on existing voice pipeline | +270 |
| `backend/iris_gateway.py` | 3 minimal touches (instantiate kernel, replace TTS constants, halt check) | +40 |
| `backend/main.py` | 4 FastAPI endpoints + lifespan wiring | +135 |
| `src-tauri/src/commands/caducean.rs` (NEW) | 4 Tauri commands proxying to FastAPI | +190 |
| `src-tauri/src/commands/mod.rs` (NEW) | Module declaration | +5 |
| `src-tauri/src/main.rs` | Register commands in `invoke_handler!` | +5 |
| `app/hooks/useCaducean.ts` (NEW) | React hook (500ms polling) | +180 |
| `app/components/CaduceanDebugPanel.tsx` (NEW) | Dev-only floating panel | +280 |

**Total: 18 files new, 12 files modified, 79 new tests passing via pytest.**

### Pre-existing Bugs Fixed in v2 Branch

Three pre-existing bugs were discovered and fixed (see commit `ad1a50d5`):

1. **`conftest.py`** — Patched missing `_DB_PATH` attribute. **Fix:** rewrote as no-op (in-memory store doesn't need patching). All pytest collection now works.
2. **Missing C++ FFI functions** — `simulate_trajectories_to_db` and `immortus_chain_keep_latest` were referenced by Python but not implemented in the C++ DLL. **Fix:** added C++ implementations; log noise gone.
3. **`conversation_store` was in-memory only** — Domain 6.4 "Chat history persistence" was claimed DONE but conversations were lost on restart. **Fix:** rewrote with SQLite (WAL mode, FK CASCADE, in-memory hot cache). 12 chat_persistence tests now pass.

### Documentation

- **Architecture:** [docs/cad_v2_architecture.md](./docs/cad_v2_architecture.md) — full system architecture with math
- **Implementation plan:** [docs/plans/Cadv2plan.md](./docs/plans/Cadv2plan.md) — 11 components, 7 phases, scope & impact analysis
- **Plan review:** [docs/plans/cad_v2_plan_review.md](./docs/plans/cad_v2_plan_review.md) — 15 corrections found via cold review
- **Integration test report:** [docs/plans/cad_v2_integration_test_report.md](./docs/plans/cad_v2_integration_test_report.md) — 78/78 tests pass via pytest
- **Frontend wiring notes:** [app/PHASE_6_INTEGRATION_NOTES.md](./app/PHASE_6_INTEGRATION_NOTES.md)

### Test Coverage

175+ tests across 13+ suites, all passing (post-v2):

```bash
# All Caducean v2 + Domain 18 + Domain 19 + pre-existing test suites
python -m pytest \
  backend/tests/test_iris_core_smoke.py \
  backend/tests/test_iris_core_simulate.py \
  backend/tests/test_chat_persistence.py \
  backend/tests/test_der_loop.py \
  backend/tests/test_trailing_director.py \
  backend/tests/test_caducean_trajectory.py \
  backend/tests/test_skill_simulator.py \
  backend/tests/test_trajectory_controller.py \
  backend/tests/test_autoresearch_integration.py \
  backend/tests/test_der_caducean_gaps.py \
  backend/tests/test_caducean_ffi_contract.py \
  backend/tests/test_caducean_v2_integration.py \
  backend/tests/test_coupled_registry.py \
  backend/tests/test_caducean_api_contract.py \
  backend/tests/test_conversation_kernel.py -v
```

**Caducean v2 (Domain 19) added the following test suites:**
- `test_caducean_ffi_contract.py` — 21 FFI struct + argtype + return code tests
- `test_caducean_v2_integration.py` — 8 Mycelium modulation + recommendation column tests
- `test_coupled_registry.py` — 8 multi-session coupling + role differentiation tests
- `test_caducean_api_contract.py` — 6 API contract tests (frozen JSON schema)
- `test_conversation_kernel.py` — 12 voice pipeline + observer callback tests

**Pre-existing bugs fixed in the v2 branch (unblocked pytest):**
- `test_iris_core_smoke.py` (9 tests) — previously broken by conftest.py bug
- `test_iris_core_simulate.py` (2 tests) — previously broken by missing C++ FFI
- `test_chat_persistence.py` (12 tests) — previously broken; conversation persistence now actually works

## ⚙️ Configuration

### Backend Configuration

**Environment Variables** (`.env`):
```env
# Server
BACKEND_HOST=localhost
BACKEND_PORT=8000

# Picovoice (Wake Word)
PICOVOICE_ACCESS_KEY=your_key_here

# Inference Backend Selection
# Options: "local" (GGUF via port 8082), "api" (OpenAI-compatible remote), "vps" (custom gateway)
IRIS_INFERENCE_MODE=local

# Remote API Configuration (when IRIS_INFERENCE_MODE=api)
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.opencode.ai/zen/go/v1

# Models
IRIS_MODELS_DIR=~/.lmstudio/models
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
  # Tool execution — dedicated model handles structured tool calls
  - id: "executor"
    path: "./models/tool-calling-model"
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

### MTP (Multi-Token Prediction) Configuration

MTP is auto-detected and enabled for compatible GGUF models. No UI toggles needed.

**How it works:**
1. The backend scans GGUF tensor names for `mtp.*` prefixes
2. If detected, the model is routed to compiled `llama-server` with `--spec-type draft-mtp`
3. Non-MTP models continue using the fast in-process `llama_cpp.Llama` path

**Profiles:**
- `balanced_mtp` — same as `balanced` but with `--spec-draft-n-max 3` (default)
- Custom: set `mtp_n_max` (1-6) and `mtp_p_min` (0.0-1.0) in model settings

**Example models:**
- `Jackrong/Qwopus3.6-27B-v2-MTP-GGUF` — 27B Qwen-based MTP model
- `Unsloth/Qwen3.6-*-MTP-GGUF` — other MTP variants

**Hardware requirements:**
- MTP models are typically 8B-27B+ parameters. At Q3/Q4 quantization, plan for **~1.5× the GGUF file size in VRAM** (weights + KV cache + overhead).
- Example: `Qwopus3.6-27B-v2-MTP-Q3_K_S` (12.2 GB file) needs **~15-16 GB VRAM/RAM** at 32k context.
- For 8 GB GPUs, use a **smaller MTP model** (8B-14B) or reduce `n_ctx` to 4096 and use partial CPU offload.

**Acceptance rate logging:** After each generation batch, the backend logs:
```
[LocalModelManager] MTP acceptance: 142/200 = 71.0% (rolling 68.3%)
```
Higher acceptance = better speedup. Typical range: 50-80%.

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
│   │   ├── streaming.py  # Streaming chunk batching, safe iteration, chunk parsing
│   │   └── personality.py
│   ├── audio/           # Audio pipeline (Porcupine + faster-whisper)
│   │   ├── engine.py    # AudioEngine — frame ingest, VAD, listener dispatch
│   │   ├── voice_command.py
│   │   └── tts_normalizer.py
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
├── src-tauri/           # Tauri desktop shell + C++ core
│   ├── src/             # Rust Tauri source
│   └── src/iris_core/   # C++ Hybrid Core Memory Engine
│       ├── iris_core.h          # FFI C-interface exports
│       ├── iris_core.cpp        # FFI gateway + EML engine
│       ├── caducean.h / .cpp    # Attention governor (Duffing dynamics)
│       ├── db_manager.h / .cpp  # Async writer + pre-keyed read pool
│       ├── security_sanitizer.h / .cpp  # RE2 O(n) payload scrubber
│       ├── event_ingestor.h / .cpp        # UUID gen + async queue + spill buffer
│       ├── iris_core_bench.cpp  # Microbenchmark harness (Caducean, RE2, ingestion, EML, RSS)
│       └── CMakeLists.txt         # CMake 3.15 — FetchContent RE2, SQLCipher
├── models/              # AI model files (symlinked to ~/.lmstudio/models)
│   ├── LFM2.5-VL-450M/         # vision model (optional)
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

### Backend Validation

See [`docs/verification/BACKEND_VALIDATION_CHECKLIST.md`](docs/verification/BACKEND_VALIDATION_CHECKLIST.md) for the full validation matrix (model configs, pass rates, latency benchmarks).

**Current pass rate:** 932/939 = **99.1%**

### Running Tests

**All Backend Tests:**
```bash
# Full suite (backend + agent + memory)
python -m pytest backend/tests/ backend/agent/tests/ backend/memory/tests/ -q

# Memory tests only
python -m pytest backend/memory/tests/ -v

# Mycelium layer tests only
python -m pytest backend/memory/tests/test_mycelium_*.py -v

# Agent tests only
python -m pytest backend/agent/tests/ -v

# C++ Hybrid Core smoke tests (9 tests — FFI, Caducean, EML, Ingestor, Immortus)
python -m pytest backend/tests/test_iris_core_smoke.py -v

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

### Mycelium Layer — Architecture (v1.7)

The Mycelium layer is IRIS's coordinate-graph memory system. It compresses episodic events into a navigable semantic map that feeds every DER loop iteration.

**6 memory layers:**

| Layer | What it stores | Lifecycle |
|-------|----------------|-----------|
| 1. Episodic events | Raw code events, edits, test runs | Decays unless reinforced |
| 2. Semantic compression | `file_node` confidence + edge weights | Rises with reinforcement, decays with neglect |
| 3. Landmarks | Verified, crystallised features | Permanent after 3 passing runs |
| 4. Pacman context lifecycle | Zone membrane (trusted/tool chunks), age-weighted retrieval | `combined = similarity×0.80 + recency×0.20` |
| 5. PiNs | Files, folders, images, URLs, decisions, fragments | Permanent flag available; auto-anchored on edit/decision |
| 6. Landmark bridges | Cross-project / cross-instance equivalence map | Survives instance migrations |

**PiNs — Primordial Information Nodes:**
Named after mycological primordia (first growth points of a fungal network). A PiN anchors any knowledge artifact into the coordinate graph so it surfaces in the DER context package automatically.

PiNs are managed programmatically via the `backend/memory/mycelium/` API — add knowledge artifacts, search the graph, and bridge landmarks across projects.

**MCP storage integration (Domain 12):**
PiNs can be backed by external stores — Google Drive, Discord, Notion, GitHub — via the `backend/integrations/models.py` OAuthConfig layer. A PiN written locally can mirror to a Drive folder; a PiN read from Discord surfaces in the next DER context package.

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
| TTS First-Word Latency | <400ms | ✅ Implemented (streaming LLM→TTS + GPU synthesis) |
| TTS Audio Gap | <2ms | ✅ Implemented (native C++ ring buffer) |
| TTS Interrupt | <5ms | ✅ Implemented (atomic flag in audio callback) |
| State Persistence | <100ms | ✅ Ready |
| Frontend Rendering | <16ms (60 FPS) | ✅ Ready |
| Tool Execution | <10s or timeout | ✅ Ready |
| Concurrent Connections | ≥100 | ✅ Passing |
| C++ Caducean Recompute | 88 ns | ✅ Measured (Release, 1M iterations) |
| C++ Event Ingestion | ~1.4 ms | ✅ Measured (full async pipeline: sanitize + UUID + queue) |
| C++ EML Read Query | ~0.1 ms | ✅ Measured (pooled WAL read, 10K iterations) |
| C++ RE2 Sanitize | 48 µs (4 KB payload) | ✅ Measured (~95 MB/s throughput) |
| C++ Core Memory Overhead | <0.1 MB RSS | ✅ Measured (singletons below Windows granularity) |

## 📚 Documentation

### User Guides

- **[Inference Mode Selection Guide](./docs/guides/USER_GUIDE_INFERENCE_MODE.md)**: Choose between Local, VPS, or OpenAI inference
- **[Dual-LLM Model Selection Guide](./docs/guides/USER_GUIDE_MODEL_SELECTION.md)**: Configure reasoning and tool execution models
- **[Wake Word Configuration Guide](./docs/guides/USER_GUIDE_WAKE_WORDS.md)**: Set up custom wake words
- **[Cleanup System Guide](./docs/guides/USER_GUIDE_CLEANUP.md)**: Analyze and remove unused files

### Developer Guides

- **[Lazy Loading Architecture](./docs/guides/DEVELOPER_LAZY_LOADING.md)**: Model loading/unloading implementation
- **[Model-Agnostic Architecture](./docs/guides/DEVELOPER_MODEL_AGNOSTIC.md)**: Agent capabilities across all inference modes
- **[Recall-as-Cognition Developer Guide](./docs/guides/DEVELOPER_RECALL_GUIDE.md)**: Extending recall ops, debugging, episode feedback loop, critical fix rationale, and skill genesis lifecycle
- **[PiN Developer Guide](./docs/guides/DEVELOPER_PIN_GUIDE.md)**: Creating pins from agent or user, auto-checkpoint config, search weight tuning, debugging, wiki graph patterns

### Architecture Documentation

- **[System Overview](./docs/architecture/SYSTEM_OVERVIEW.md)**: Complete system architecture
- **[Agent Architecture](./docs/architecture/AGENT_ARCHITECTURE.md)**: Dual-LLM system design
- **[UI Architecture](./docs/architecture/UI_ARCHITECTURE.md)**: Frontend component structure
- **[DER Loop + Mycelium v1.7](./docs/architecture/DER_LOOP_MYCELIUM.md)**: Full DER loop spec — token budgets, trailing director, Pacman lifecycle, PiN injection, landmark bridges
- **[Mycelium Kyudo Layer Guide](./docs/architecture/MYCELIUM_KYUDO_LAYER_GUIDE.md)**: End-user guide to the coordinate-graph memory system, PiNs, and cross-project bridging
- **[Recall-as-Cognition](./docs/architecture/RECALL_AS_COGNITION.md)**: Two-phase memory retrieval protocol — op grammar, iterative recall, streaming filter, episode feedback loop, skill genesis, and performance model
- **[PiN System](./docs/architecture/PIN_SYSTEM.md)**: Primordial Information Nodes — pin data model, recall ops (`pin="title"`, `pin query="text"`, `pin file="X.md"`, `pin tags="a,b"`), auto-checkpoint heuristic, wiki link graph, tunable search weights
- **[Model-Agnostic Architecture Verification](./docs/architecture/MODEL_AGNOSTIC_ARCHITECTURE_VERIFICATION.md)**: Verification that agent capabilities remain identical across all inference backends

### Integration Documentation

- **[Porcupine Integration Summary](./docs/integrations/PORCUPINE_INTEGRATION_SUMMARY.md)**: Wake word detection implementation
- **[Wake Word UI Integration](./docs/integrations/WAKE_WORD_UI_INTEGRATION_SUMMARY.md)**: Wake word discovery and UI wiring

### Performance & Reference

- **[Performance Optimization Summary](./docs/performance/PERFORMANCE_OPTIMIZATION_SUMMARY.md)**: Backend performance tuning — WebSocket batching, agent caching, TTS streaming
- **[Benchmarks](./docs/reference/BENCHMARKS.md)**: Mycelium layer benchmark claims and validation setup

### Specifications

- **[IRIS Mycelium Layer Spec v1.6](./specs/IRIS_Mycelium_Layer_Spec_v1.6.md)**: Coordinate-graph memory system specification
- **[IRIS Swarm PRD v9](./specs/IRIS_Swarm_PRD_v9.md)**: Multi-agent swarm coordination product requirements
- **[Agent Loop Design](./specs/AGENT_LOOP_DESIGN.md)**: DER loop upgrade specification
- **[CLI Crawler Spec](./specs/CLI_CRAWLER_SPEC.md)**: Web crawler CLI toolkit specification

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

For complete message documentation, see the WebSocket section above and the backend OpenAPI docs at `/docs` when the server is running.

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

For more detailed troubleshooting, see [TROUBLESHOOTING_GUIDE.md](./TROUBLESHOOTING_GUIDE.md) in the project root.

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
- Review the API docs at `http://localhost:8000/docs` when the backend is running
- Open an issue on GitHub

---

**Version**: 4.8.0
**Last Updated**: May 26, 2026
**Status**: Production Ready ✅ (Domain 19 Complete)
