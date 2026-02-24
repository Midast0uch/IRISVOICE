# IRIS Vision Integration — MiniCPM-o 4.5

> **Local multimodal vision for IRIS** — see your screen, understand context, and assist proactively.

---

## 🌟 Key Features

| Feature | Description |
|---------|-------------|
| **"See & Talk"** | IRIS captures your screen during voice conversations and uses it as context. Ask _"What am I looking at?"_ or _"Help me with this error"_ — IRIS sees and responds. |
| **100% Local** | All vision inference runs through **Ollama** on your machine. No cloud API costs, no data leaving your PC. |
| **Proactive Monitoring** | An optional `ScreenMonitor` runs in the background, periodically analyzing your screen for errors, pop-ups, or context changes and proactively offering help. |
| **GUI Automation** | The `GUIAgent` uses MiniCPM-o to identify buttons, text fields, and other UI elements for automation tasks. |
| **UI Controls** | Toggle vision on/off, configure proactive mode, and change the vision model — all from the IRIS orbital interface. |

---

## 🛠️ Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | With `venv` activated |
| Node.js | 18+ | For the Next.js frontend |
| [Ollama](https://ollama.com/) | Latest | Vision model runtime |
| GPU (recommended) | 8 GB+ VRAM | MiniCPM-o 4.5 is ~8 GB; runs on CPU but slowly |

---

## 📥 Setup Instructions

### 1. Install Python Dependencies

```bash
# From the IRISVOICE root directory, with your venv activated:
pip install -r requirements.txt
```

Key packages added for vision:
- **`mss`** — cross-platform screen capture
- **`Pillow`** — image processing and encoding
- **`requests`** — HTTP client for Ollama API
- **`pyautogui`** — mouse/keyboard automation for GUIAgent

### 2. Install Ollama & Pull the Vision Model

```bash
# Install Ollama from https://ollama.com/ then:
ollama pull openbmb/minicpm-o4.5
```

> **Tip**: The model is ~8 GB. Ensure Ollama is running (`ollama serve`) before starting IRIS.

### 3. Verify the Installation

```bash
python tests/test_vision_integration.py
```

Expected output:
```
[1/4] MiniCPM-o Availability .............. ✅
[2/4] Screen Capture ...................... ✅
[3/4] Vision Inference .................... ✅ (or ⏭ skipped if model loading)
[4/4] Conversation Manager ................ ✅
```

### 4. Start IRIS

```bash
# Terminal 1 — Backend
python start-backend.py

# Terminal 2 — Frontend
npm run dev
```

Or use the unified startup script:
```bash
start-iris.bat
```

---

## 🖥️ Frontend UI Controls

Vision controls are integrated into the existing IRIS orbital navigation under **AUTOMATE → VISION**.

### Accessing Vision Settings

1. Click the IRIS orb to expand to **Level 2** (main nodes)
2. Click **AUTOMATE** (CPU icon) to expand to **Level 3** (subnodes)
3. Click the **VISION** (👁 Eye icon) subnode to expand to **Level 4** (mini-node cards)

### Vision Mini-Node Cards

| Card | Field | Type | Description |
|------|-------|------|-------------|
| **Vision** | `vision_enabled` | Toggle | Master switch — enables/disables all vision features |
| **Screen Context** | `screen_context` | Toggle | Include a screenshot with voice queries during conversation |
| **Proactive Mode** | `proactive_monitor` | Toggle | Enable/disable the background screen monitor |
| | `monitor_interval` | Slider (5–120 s) | How often the monitor captures & analyzes the screen |
| **Ollama Endpoint** | `ollama_endpoint` | Text | URL of your Ollama server (default: `http://localhost:11434`) |
| **Vision Model** | `vision_model` | Dropdown | Choose the vision model: `minicpm-o4.5`, `llava`, or `bakllava` |

### Dashboard View

The same controls are accessible in the **IRIS Menu Dashboard** (dark-glass panel) under the **AUTO** tab → **VISION** subnode.

### GUI Automation Updates

The **GUI AUTOMATION** subnode's **Vision Model** dropdown now includes `minicpm_ollama` as the default provider (replacing `anthropic`), enabling local vision-powered GUI automation without cloud API keys.

---

## 📦 Architecture

### Backend Modules

```
backend/
├── vision/
│   ├── __init__.py            # Package exports
│   ├── minicpm_client.py      # MiniCPMClient — Ollama HTTP API wrapper
│   ├── screen_capture.py      # ScreenCapture — mss-based capture with caching
│   └── screen_monitor.py      # ScreenMonitor — background proactive analysis
├── agent/
│   └── omni_conversation.py   # OmniConversationManager — text + vision prompts
├── automation/
│   ├── vision.py              # VisionModelClient + GUIAgent (updated for MiniCPM)
│   └── operator.py            # NativeGUIOperator (fixed base64 truncation)
└── main.py                    # Vision API endpoints + apply_vision_config()
```

### Frontend Modules

```
components/
├── hexagonal-control-center.tsx   # Orbital UI — added VISION subnode to automate
├── dark-glass-dashboard.tsx       # Dashboard — added VISION panel
├── mini-node-stack.tsx            # Renders vision mini-node cards
└── fields/                        # ToggleField, SliderField, DropdownField, etc.

data/
└── mini-nodes.ts                  # Vision mini-node card definitions

backend/
└── models.py                      # SUBNODE_CONFIGS — vision subnode schema
```

### Data Flow

```
┌──────────────────────┐
│   Frontend (React)   │
│  AUTOMATE → VISION   │
│  Toggle / Slider / …│
└──────────┬───────────┘
           │ WebSocket: field_update
           ▼
┌──────────────────────┐
│  Backend (FastAPI)   │
│  apply_vision_config │
└──────────┬───────────┘
           │
     ┌─────┴──────────┐
     ▼                ▼
┌─────────┐  ┌──────────────┐
│ Audio   │  │ Screen       │
│ Engine  │  │ Monitor      │
│ (config)│  │ (start/stop) │
└─────────┘  └──────────────┘
           │
           ▼
┌──────────────────────┐
│  MiniCPMClient       │
│  → Ollama HTTP API   │
│  → openbmb/minicpm   │
└──────────────────────┘
```

---

## 🚀 Usage

### In Conversation (Voice)

With `vision_enabled` ON, IRIS automatically includes a screenshot with your voice query:

> **You**: _"Does this code look correct?"_
> **IRIS**: _(Analyzes screen)_ _"Yes, but you're missing a colon on line 14."_

> **You**: _"What's on my screen right now?"_
> **IRIS**: _"I can see VS Code with a Python file open…"_

### Via REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/vision/status` | Check vision subsystem status |
| `POST` | `/api/vision/describe` | Get a text description of the current screen |
| `POST` | `/api/vision/detect?description=Save Button` | Find coordinates of a UI element |
| `POST` | `/api/vision/config` | Update vision configuration |
| `POST` | `/api/vision/monitor/start` | Start proactive screen monitoring |
| `POST` | `/api/vision/monitor/stop` | Stop proactive screen monitoring |

### Configuration via API

```bash
curl -X POST http://localhost:8000/api/vision/config \
  -H "Content-Type: application/json" \
  -d '{
    "vision_enabled": true,
    "screen_context_during_conversation": true,
    "ollama_endpoint": "http://localhost:11434",
    "vision_model": "minicpm-o4.5"
  }'
```

### Configuration via WebSocket

Vision settings are also applied in real-time through the existing WebSocket `field_update` message flow. When you toggle a switch in the VISION subnode UI, the frontend sends:

```json
{
  "type": "field_update",
  "payload": {
    "subnode_id": "vision",
    "field_id": "vision_enabled",
    "value": true
  }
}
```

The backend's `apply_vision_config()` function routes this to the appropriate subsystem (AudioEngine config, ScreenMonitor start/stop, etc.).

---

## 🔧 Dependencies

### Python (`requirements.txt`)

```
mss>=0.9.0              # Screen capture
Pillow>=10.0.0          # Image processing
requests>=2.31.0        # Ollama HTTP API
pyautogui>=0.9.54       # GUI automation mouse/keyboard
```

### Frontend (already included in `package.json`)

```
lucide-react            # Eye icon for the VISION subnode
framer-motion           # Animations for mini-node cards
```

No additional frontend packages are required — the vision UI uses existing field components (`ToggleField`, `SliderField`, `DropdownField`, `TextField`).

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| **"MiniCPM-o not available"** | Make sure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull openbmb/minicpm-o4.5`) |
| **Slow inference** | MiniCPM-o 4.5 requires ~8 GB VRAM. On CPU-only machines, expect 30-60 s per inference. Consider `llava` as a lighter alternative. |
| **Black screenshots** | Ensure `mss` has display access. On remote/headless setups, screen capture may not work. |
| **Vision toggle has no effect** | Check the backend console for `[VisionConfig]` log lines. Verify the WebSocket connection is active. |
| **VISION subnode not showing** | Hard-refresh the frontend (`Ctrl+Shift+R`). The subnode definition is in `hexagonal-control-center.tsx`. |
| **Model not found in dropdown** | The dropdown options are `minicpm-o4.5`, `llava`, `bakllava`. Ensure the model name matches exactly. |

---

## 📋 Files Changed

| File | Change |
|------|--------|
| `backend/vision/minicpm_client.py` | **NEW** — Core MiniCPM-o Ollama client |
| `backend/vision/screen_capture.py` | **NEW** — Screen capture utilities |
| `backend/vision/screen_monitor.py` | **NEW** — Proactive screen monitor |
| `backend/vision/__init__.py` | **UPDATED** — Exports ScreenMonitor |
| `backend/agent/omni_conversation.py` | **NEW** — Vision-aware conversation manager |
| `backend/automation/vision.py` | **UPDATED** — Added MiniCPM provider, updated defaults |
| `backend/automation/operator.py` | **FIXED** — base64 screenshot no longer truncated |
| `backend/models.py` | **UPDATED** — Added vision subnode to SUBNODE_CONFIGS |
| `backend/main.py` | **UPDATED** — Vision API endpoints + apply_vision_config() |
| `components/hexagonal-control-center.tsx` | **UPDATED** — VISION subnode + Eye icon |
| `components/dark-glass-dashboard.tsx` | **UPDATED** — VISION panel in dashboard |
| `data/mini-nodes.ts` | **UPDATED** — Vision mini-node card definitions |
| `requirements.txt` | **UPDATED** — Added mss, Pillow, requests, pyautogui |
| `tests/test_vision_integration.py` | **NEW** — Integration test script |
