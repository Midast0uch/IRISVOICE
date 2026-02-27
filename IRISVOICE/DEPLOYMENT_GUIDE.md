# IRISVOICE Deployment Guide

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Backend Setup](#backend-setup)
3. [Frontend Setup](#frontend-setup)
4. [Audio Configuration](#audio-configuration)
5. [MCP Server Setup](#mcp-server-setup)
6. [VPS Gateway Configuration (Optional)](#vps-gateway-configuration-optional)
7. [Running the Application](#running-the-application)
8. [Verification](#verification)
9. [Troubleshooting](#troubleshooting)

---

## System Requirements

### Hardware Requirements

**Minimum:**
- CPU: 4-core processor (Intel i5 or AMD Ryzen 5 equivalent)
- RAM: 16 GB
- Storage: 20 GB free space
- GPU: Optional (NVIDIA GPU with CUDA support recommended for faster inference)
- Audio: Microphone and speakers/headphones

**Recommended:**
- CPU: 8-core processor (Intel i7/i9 or AMD Ryzen 7/9)
- RAM: 32 GB or more
- Storage: 50 GB free space (SSD recommended)
- GPU: NVIDIA GPU with 8GB+ VRAM (RTX 3060 or better)
- Audio: High-quality USB microphone and speakers

### Software Requirements

- **Operating System**: Windows 10/11, macOS 10.15+, or Linux (Ubuntu 20.04+)
- **Python**: 3.10 or higher
- **Node.js**: 18.x or higher
- **npm**: 9.x or higher
- **Git**: For cloning the repository

### Optional Requirements

- **CUDA Toolkit**: 11.8 or 12.1 (for GPU acceleration)
- **VPS Server**: For offloading model inference (optional)

---

## Backend Setup

### 1. Install Python Dependencies

Navigate to the IRISVOICE directory and create a virtual environment:

```bash
cd IRISVOICE
python -m venv venv
```

Activate the virtual environment:

**Windows:**
```bash
venv\Scripts\activate
```

**macOS/Linux:**
```bash
source venv/bin/activate
```

### 2. Install Python Packages

Install the required Python packages:

```bash
pip install -r requirements.txt
```

### 3. Install PyTorch with CUDA Support (GPU Users)

If you have an NVIDIA GPU and want to use GPU acceleration:

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

For CPU-only users, the default PyTorch installation from `requirements.txt` is sufficient.

### 4. Download AI Models

The system requires two LLM models and the LFM 2.5 audio model:

**Download Text Models:**
```bash
python download_text_model.py
```

This will download:
- `LFM2-8B-A1B` (reasoning model, ~8GB)
- `LFM2.5-1.2B-Instruct` (execution model, ~1.2GB)

**Download Audio Model:**
```bash
python download_lfm_audio.py
```

This will download:
- `LFM 2.5 Audio Model` (end-to-end audio-to-audio model, ~2GB)

Models will be stored in the `models/` directory.

### 5. Configure Environment Variables

Create a `.env` file in the IRISVOICE directory:

```bash
# Backend Configuration
BACKEND_HOST=localhost
BACKEND_PORT=8000

# Model Configuration
MODEL_PATH=./models
DEVICE=cuda  # or 'cpu' for CPU-only

# Audio Configuration
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1

# Logging
LOG_LEVEL=INFO
LOG_FILE=backend/logs/iris.log

# Optional: VPS Gateway
VPS_ENABLED=false
VPS_ENDPOINT=
VPS_AUTH_TOKEN=
```

### 6. Verify Backend Dependencies

Run the dependency check script:

```bash
python check_phase1_dependencies.py
```

This will verify that all required packages are installed correctly.

---

## Frontend Setup

### 1. Install Node.js Dependencies

From the IRISVOICE directory:

```bash
npm install
```

This will install all frontend dependencies including:
- Next.js (React framework)
- Tailwind CSS (styling)
- Framer Motion (animations)
- Tauri (desktop application framework)

### 2. Configure Frontend Environment

The frontend uses the same `.env` file. Ensure the following variables are set:

```bash
# WebSocket Configuration
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

### 3. Build Frontend Assets (Optional)

For production deployment, build the frontend:

```bash
npm run build
```

For development, you can skip this step and use the dev server.

---

## Audio Configuration

### 1. Verify Audio Devices

Run the audio device check script:

```bash
python check_devices.py
```

This will list all available audio input and output devices on your system.

### 2. Configure Audio Devices

The LFM 2.5 audio model handles audio device management internally. You can configure devices through the IRISVOICE UI:

1. Launch the application
2. Navigate to **Voice** → **Input** in the settings dashboard
3. Select your preferred microphone from the dropdown
4. Navigate to **Voice** → **Output**
5. Select your preferred speakers/headphones

### 3. Audio Device Settings

Default audio settings are stored in `backend/settings/voice.json`:

```json
{
  "input": {
    "input_device": "default",
    "sample_rate": 16000,
    "channels": 1
  },
  "output": {
    "output_device": "default",
    "sample_rate": 16000,
    "channels": 1
  }
}
```

The LFM 2.5 audio model will automatically:
- Apply noise reduction
- Apply echo cancellation
- Apply voice enhancement
- Apply automatic gain control
- Handle device fallback if a device becomes unavailable

---

## MCP Server Setup

IRISVOICE uses Model Context Protocol (MCP) servers to provide tool capabilities to the agent. The system includes several MCP servers:

### 1. MCP Server Components

The following MCP servers are included:

- **BrowserServer**: Web browsing and automation
- **AppLauncherServer**: Application control
- **SystemServer**: System operations
- **FileManagerServer**: File operations
- **GUIAutomationServer**: UI automation

### 2. MCP Server Configuration

MCP servers are configured in `backend/mcp/server_config.json`:

```json
{
  "servers": {
    "browser": {
      "enabled": true,
      "command": "node",
      "args": ["backend/mcp/servers/browser_server.js"]
    },
    "app_launcher": {
      "enabled": true,
      "command": "node",
      "args": ["backend/mcp/servers/app_launcher_server.js"]
    },
    "system": {
      "enabled": true,
      "command": "node",
      "args": ["backend/mcp/servers/system_server.js"]
    },
    "file_manager": {
      "enabled": true,
      "command": "node",
      "args": ["backend/mcp/servers/file_manager_server.js"]
    },
    "gui_automation": {
      "enabled": true,
      "command": "node",
      "args": ["backend/mcp/servers/gui_automation_server.js"]
    }
  }
}
```

### 3. MCP Server Startup

MCP servers start automatically when the backend launches. The `ServerManager` class handles:

- Starting all configured MCP servers
- Monitoring server health
- Automatic restart on failure
- Graceful shutdown

### 4. Security Configuration

MCP tool execution is protected by security filters. Configure security settings in `backend/settings/automate.json`:

```json
{
  "tools": {
    "security_allowlist": true,
    "rate_limit": 10,
    "require_confirmation": true,
    "audit_logging": true
  }
}
```

**Security Features:**
- Allowlist-based parameter validation
- User confirmation for destructive operations
- Rate limiting (max 10 executions per minute)
- Audit logging of all tool executions
- Input sanitization

---

## VPS Gateway Configuration (Optional)

The VPS Gateway enables offloading heavy model inference to a remote VPS server. This is useful for users with limited local compute resources.

### 1. VPS Server Requirements

Your VPS server should have:
- Python 3.10+
- 16GB+ RAM
- GPU with 8GB+ VRAM (recommended)
- FastAPI installed
- Same model files as local setup

### 2. VPS Server Setup

On your VPS server:

1. Clone the IRISVOICE repository
2. Install Python dependencies
3. Download the AI models
4. Create a VPS endpoint script (`vps_endpoint.py`):

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from backend.agent.model_router import ModelRouter

app = FastAPI()
model_router = ModelRouter()

class InferenceRequest(BaseModel):
    model: str
    prompt: str
    context: dict
    parameters: dict
    session_id: str

class InferenceResponse(BaseModel):
    text: str
    model: str
    latency_ms: float
    metadata: dict

@app.post("/infer")
async def infer(request: InferenceRequest):
    try:
        result = await model_router.route_message(
            request.prompt,
            request.context
        )
        return InferenceResponse(
            text=result,
            model=request.model,
            latency_ms=0.0,
            metadata={}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

5. Run the VPS endpoint:

```bash
uvicorn vps_endpoint:app --host 0.0.0.0 --port 8000
```

### 3. Local VPS Gateway Configuration

On your local machine, configure the VPS Gateway in `backend/settings/agent.json`:

```json
{
  "vps": {
    "enabled": true,
    "endpoints": ["https://your-vps-server.com:8000"],
    "auth_token": "your-secure-token",
    "timeout": 30,
    "health_check_interval": 60,
    "fallback_to_local": true,
    "load_balancing": false,
    "protocol": "rest"
  }
}
```

Or configure through the UI:
1. Navigate to **Agent** → **VPS** in the settings dashboard
2. Enable VPS Gateway
3. Enter your VPS endpoint URL
4. Enter your authentication token
5. Configure timeout and health check settings

### 4. VPS Gateway Features

**Automatic Fallback:**
- If VPS is unavailable, the system automatically falls back to local execution
- No interruption to user experience

**Health Monitoring:**
- Background health checks every 60 seconds
- Automatic detection of VPS failures
- Automatic resume when VPS recovers

**Load Balancing (Optional):**
- Support for multiple VPS endpoints
- Round-robin or least-loaded routing
- Automatic removal of failed endpoints

### 5. What Gets Offloaded

**Offloaded to VPS:**
- Model loading (lfm2-8b, lfm2.5-1.2b-instruct)
- Model inference (text generation, reasoning)
- Optionally: Tool execution

**Remains Local:**
- WebSocket Manager (real-time communication)
- Session Manager (session lifecycle)
- State Manager (settings persistence)
- Voice Pipeline (audio capture, LFM 2.5 audio model)
- UI Components (IrisOrb, DarkGlassDashboard, ChatView)

---

## Running the Application

### Development Mode

**Option 1: Run Backend and Frontend Separately**

Terminal 1 (Backend):
```bash
python start-backend.py
```

Terminal 2 (Frontend):
```bash
npm run dev
```

**Option 2: Run with Concurrently**

```bash
npm run dev:backend & npm run dev:frontend
```

**Option 3: Run as Tauri Desktop App**

```bash
npm run dev:tauri
```

### Production Mode

**Build the Application:**

```bash
# Build frontend
npm run build

# Build Tauri desktop app
npm run tauri build
```

**Run the Production Build:**

```bash
# Start backend
python start-backend.py

# Start frontend
npm start
```

### Quick Start Scripts

**Windows:**
```bash
start-iris.bat
```

**macOS/Linux:**
```bash
./start-iris.sh
```

These scripts will:
1. Activate the Python virtual environment
2. Start the backend server
3. Start the frontend development server
4. Open the application in your browser

---

## Verification

### 1. Verify Backend is Running

Open your browser and navigate to:
```
http://localhost:8000/docs
```

You should see the FastAPI interactive documentation.

### 2. Verify WebSocket Connection

Open the browser console and check for WebSocket connection messages:
```
WebSocket connected to ws://localhost:8000/ws/{client_id}
```

### 3. Verify Models are Loaded

Check the backend logs:
```bash
tail -f backend/logs/iris.log
```

Look for messages indicating models are loaded:
```
INFO: Model lfm2-8b loaded successfully
INFO: Model lfm2.5-1.2b-instruct loaded successfully
INFO: LFM 2.5 audio model loaded successfully
```

### 4. Verify MCP Servers

Check the agent status in the UI:
1. Navigate to **Monitor** → **Diagnostics**
2. Check that all MCP servers show as "Running"

Or check via API:
```bash
curl http://localhost:8000/api/agent/status
```

### 5. Test Voice Interaction

1. Double-click the IrisOrb
2. Speak a command (e.g., "Hello IRIS")
3. Verify the orb shows "listening" state
4. Verify you receive a spoken response

### 6. Test Text Chat

1. Navigate to the ChatView
2. Type a message (e.g., "What can you do?")
3. Verify you receive a text response

### 7. Test Settings Persistence

1. Navigate to **Customize** → **Theme**
2. Change the brand color
3. Restart the application
4. Verify the brand color persists

---

## Troubleshooting

### Backend Issues

**Issue: Backend fails to start**

Check Python version:
```bash
python --version
```

Ensure Python 3.10+ is installed.

Check for missing dependencies:
```bash
pip install -r requirements.txt
```

Check port availability:
```bash
# Windows
netstat -ano | findstr :8000

# macOS/Linux
lsof -i :8000
```

**Issue: Models fail to load**

Check available disk space:
```bash
# Windows
dir models

# macOS/Linux
du -sh models/*
```

Check available RAM:
```bash
# Windows
systeminfo | findstr "Available Physical Memory"

# macOS/Linux
free -h
```

For GPU issues, verify CUDA installation:
```bash
nvidia-smi
```

**Issue: WebSocket connection fails**

Check CORS configuration in `backend/main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Check firewall settings to ensure port 8000 is open.

### Frontend Issues

**Issue: Frontend fails to start**

Check Node.js version:
```bash
node --version
```

Ensure Node.js 18+ is installed.

Clear npm cache and reinstall:
```bash
npm cache clean --force
rm -rf node_modules package-lock.json
npm install
```

**Issue: WebSocket connection refused**

Verify backend is running:
```bash
curl http://localhost:8000/health
```

Check WebSocket URL in `.env`:
```bash
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

### Audio Issues

**Issue: No audio devices detected**

Run the device check script:
```bash
python check_devices.py
```

Verify audio drivers are installed and devices are connected.

**Issue: Audio quality is poor**

The LFM 2.5 audio model applies automatic audio processing. If quality is still poor:

1. Check microphone quality and positioning
2. Reduce background noise
3. Adjust input volume in system settings
4. Try a different audio device

**Issue: Wake word not detected**

1. Navigate to **Agent** → **Wake** in settings
2. Verify wake phrase is configured correctly
3. Adjust detection sensitivity (0-100%)
4. Speak clearly and at normal volume
5. Ensure microphone is not muted

### MCP Server Issues

**Issue: MCP servers fail to start**

Check Node.js installation:
```bash
node --version
```

Check MCP server logs:
```bash
tail -f backend/logs/mcp_servers.log
```

Manually start a server for debugging:
```bash
node backend/mcp/servers/browser_server.js
```

**Issue: Tool execution fails**

Check security settings in `backend/settings/automate.json`:
```json
{
  "tools": {
    "security_allowlist": true
  }
}
```

Check audit logs:
```bash
tail -f backend/logs/tool_audit.log
```

### VPS Gateway Issues

**Issue: VPS connection fails**

Verify VPS endpoint is reachable:
```bash
curl https://your-vps-server.com:8000/health
```

Check authentication token:
```bash
curl -H "Authorization: Bearer your-token" https://your-vps-server.com:8000/health
```

Check VPS Gateway logs:
```bash
tail -f backend/logs/vps_gateway.log
```

**Issue: VPS fallback not working**

Verify fallback is enabled in settings:
```json
{
  "vps": {
    "fallback_to_local": true
  }
}
```

Check local models are available:
```bash
ls -la models/
```

### Performance Issues

**Issue: Slow response times**

Check system resources:
```bash
# Windows
taskmgr

# macOS
Activity Monitor

# Linux
htop
```

Consider:
- Enabling GPU acceleration
- Offloading to VPS
- Reducing conversation memory limit
- Closing other applications

**Issue: High memory usage**

Check model offloading:
```bash
ls -la offload/
```

Consider:
- Using VPS Gateway
- Reducing model size
- Increasing system RAM

### Log Files

All logs are stored in `backend/logs/`:

- `iris.log` - Main application log
- `websocket.log` - WebSocket connection log
- `agent.log` - Agent kernel log
- `voice.log` - Voice pipeline log
- `mcp_servers.log` - MCP server log
- `tool_audit.log` - Tool execution audit log
- `vps_gateway.log` - VPS Gateway log

Check logs for detailed error messages and stack traces.

---

## Additional Resources

- **API Documentation**: See `API_DOCUMENTATION.md`
- **System Architecture**: See `docs/SYSTEM_OVERVIEW.md`
- **Agent Architecture**: See `docs/AGENT_ARCHITECTURE.md`
- **UI Architecture**: See `docs/UI_ARCHITECTURE.md`
- **Troubleshooting Guide**: See `TROUBLESHOOTING_GUIDE.md` (Task 27.3)

---

## Support

For issues not covered in this guide:

1. Check the GitHub Issues page
2. Review the API documentation
3. Check the troubleshooting guide
4. Contact the development team

---

## License

IRISVOICE is licensed under the MIT License. See `LICENSE` file for details.
