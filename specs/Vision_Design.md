Design Specification: LFM2.5-VL Vision Layer Integration
IRISVOICE Spec Mode: design.md
Version: 4.1.0
Date: March 2026
Status: Draft

1. Architecture Overview
1.1 Core Principle
Vision is a tool, not a voice pipeline component and not a model route.

The voice pipeline and gates system are completely sealed — they do not know vision exists. The IRIS Gateway passes messages to the Agent Kernel exactly as before. The Agent Kernel passes to Qwen exactly as before.

The only new addition: Qwen now has a vision.* tool available in its MCP toolbox, the same way it has filesystem.* or browser.*. When Qwen calls it, the Tool Bridge handles it. The voice pipeline never sees the difference.

1.2 Pre-Integration Architecture
┌─────────────────────────────────────────────────────────────┐
│                    Voice Pipeline (Frozen)                  │
│  ┌──────────┐   ┌─────────────┐   ┌────────────────┐       │
│  │Porcupine │ → │ RealtimeSTT │ → │  IRIS Gateway  │       │
│  │Wake Word │   │  (Whisper)  │   │   (Frozen)     │       │
│  └──────────┘   └─────────────┘   └───────┬────────┘       │
└───────────────────────────────────────────┼─────────────────┘
                                            │
┌───────────────────────────────────────────▼─────────────────┐
│                        Agent Kernel                         │
│   ┌─────────────────┐       ┌──────────────────┐           │
│   │  Model Router   │       │   Tool Bridge    │           │
│   │  ├─ Brain       │◄──────│   (MCP Client)   │           │
│   │  │  (LFM2-8B)   │       └────────┬─────────┘           │
│   │  └─ Executor    │                │                      │
│   │     (LFM2.5)    │                ▼                      │
│   └─────────────────┘       ┌──────────────────┐           │
│                             │   MCP Servers:   │           │
│                             │   • Browser      │           │
│                             │   • Filesystem   │           │
│                             │   • System       │           │
│                             │   • App Launch   │           │
│                             └──────────────────┘           │
└─────────────────────────────────────────────────────────────┘
1.3 Post-Integration Architecture
┌─────────────────────────────────────────────────────────────┐
│             Voice Pipeline (Frozen — Unchanged)             │
│  Porcupine → RealtimeSTT → IRIS Gateway → WebSocket Mgr     │
│              ↓                                              │
│         Session Manager                                     │
│              ↑                                              │
│         LuxTTS (TTS) ←──────────────────────────────────   │
└────────────────────────────────┬────────────────────────────┘
                                 │ (unchanged message format)
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                        Agent Kernel                         │
│   ┌─────────────────┐       ┌──────────────────┐           │
│   │  Model Router   │       │   Tool Bridge    │           │
│   │  ├─ Brain       │◄──────│   (MCP Client)   │           │
│   │  │  (LFM2-8B)   │       └────────┬─────────┘           │
│   │  └─ Executor    │                │                      │
│   │     (LFM2.5)    │    ┌───────────┴──────────┐          │
│   └─────────────────┘    │     MCP Servers:     │          │
│                          │     • Browser        │          │
│                          │     • Filesystem     │          │
│                          │     • System         │          │
│                          │     • App Launch     │          │
│                          │     • Vision (NEW) ⚠️│          │
│                          └───────────┬──────────┘          │
└──────────────────────────────────────┼─────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Vision Layer (NEW)                     │
│   ┌──────────────────┐       ┌──────────────────┐          │
│   │ VisionMCPServer  │───────│ lfm_vl_provider  │          │
│   │  (MCP Server)    │       │  (HTTP Client)   │          │
│   └──────────────────┘       └────────┬─────────┘          │
│                                       │                     │
│              ┌────────────────────────▼──────────────────┐  │
│              │         llama-server (Port 8081)          │  │
│              │     LFM2.5-VL-1.6B-GGUF + mmproj         │  │
│              │           (Separate Process)              │  │
│              └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
1.4 Frozen Components
The following are explicitly frozen and must not be modified:

backend/voice/ — entire directory frozen
backend/iris_gateway.py — frozen (except MCP registration if applicable)
backend/ws_manager.py — frozen
backend/core/ — entire directory frozen
backend/sessions/ — entire directory frozen
backend/state_manager.py — frozen
Any gates logic — frozen
WebSocket message format — frozen
2. Component Design
2.1 lfm_vl_provider.py
Location: backend/tools/lfm_vl_provider.py
Role: HTTP client wrapping the llama-server vision endpoint

Data Structures
python
@dataclass
class LFMVLConfig:
    """Configuration for LFM2.5-VL vision provider."""
    base_url: str = "http://localhost:8081/v1"
    temperature: float = 0.1
    min_p: float = 0.15
    repetition_penalty: float = 1.05
    image_max_tokens: int = 128  # Range: 64-256 depending on task
    timeout: float = 30.0
Provider Class
python
class LFMVLProvider:
    """
    Synchronous HTTP client for LFM2.5-VL vision model.
    Design principles:
    - No state held between calls
    - Every call is independent (screenshot, query, response)
    - Sync wrapper for httpx to support async-to-sync bridging
    """
    def __init__(self, config: Optional[LFMVLConfig] = None)
    def health_check(self) -> bool
    def analyze_screen(self, img_bytes: bytes, question: str = "") -> str
    def find_ui_element(self, img_bytes: bytes, description: str) -> dict
    def read_text(self, img_bytes: bytes, region: Optional[Tuple] = None) -> str
    def suggest_action(self, img_bytes: bytes, goal: str) -> dict
    def describe_live_frame(self, img_bytes: bytes) -> str
Fallback Implementation
python
class LFMVLTransformers:
    """
    Fallback implementation using transformers library directly.
    Used when llama-server is unavailable or for CPU-only environments.
    Same interface as LFMVLProvider.
    """
    def __init__(self, model_path: str)
Screenshot Utility
python
def screenshot_to_bytes(
    region: Optional[Tuple[int, int, int, int]] = None
) -> bytes:
    """
    Capture screen and return as PNG bytes.
    Uses mss (Multi-Screen Shot) for cross-platform support.
    Latency: <5ms for full screen capture on target hardware.
    """
Sampling Parameters (Liquid AI Official):

Parameter	Value	Reason
temperature	0.1	Low for deterministic outputs
min_p	0.15	Nucleus sampling threshold
repetition_penalty	1.05	Prevent repetition
image_max_tokens	64–256	Task-dependent (see tuning guide)
Tuning Guide:

Use Case	image_max_tokens	Method
Click specific button	64	find_ui_element
Live screen monitoring	64	describe_live_frame
Read form/dialog	128	read_text
Complex UI understanding	256	analyze_screen
Document OCR	256	ocr_region
2.2 vision_mcp_server.py
Location: backend/tools/vision_mcp_server.py
Role: MCP server exposing vision tools over stdio JSON-RPC
Pattern: Identical to existing BrowserMCPServer, FileMCPServer

Server Class
python
class VisionMCPServer:
    """
    MCP server for vision capabilities.
    Follows identical pattern to BrowserMCPServer and FileMCPServer.
    Communicates via stdin/stdout JSON-RPC.
    """
    def __init__(self)
    async def handle(self, request: dict) -> dict          # JSON-RPC dispatcher
    async def _call_tool(self, name: str, arguments: dict) -> dict
    async def serve_stdio(self)                            # Main stdin/stdout loop
    async def _handle_tools_list(self) -> dict             # Returns tool schemas
    async def _handle_tools_call(self, params: dict) -> dict
Tool Mapping
MCP Tool	Provider Method
vision.analyze_screen	provider.analyze_screen(img, question)
vision.find_ui_element	provider.find_ui_element(img, description)
vision.read_text	provider.ocr_region(img, hint)
vision.suggest_next_action	provider.suggest_action(img, goal)
vision.describe_live_frame	provider.describe_live_frame(img)
Tool Schema
json
{
  "tools": [
    {
      "name": "vision.analyze_screen",
      "description": "Analyze current screen content and answer questions about it",
      "parameters": {
        "type": "object",
        "properties": {
          "question": {"type": "string", "description": "What to look for"},
          "region": {"type": "array", "description": "[x, y, width, height]"}
        }
      }
    },
    {
      "name": "vision.find_ui_element",
      "description": "Locate a UI element on screen",
      "parameters": {
        "type": "object",
        "properties": {
          "element_description": {"type": "string", "description": "Description of element"}
        },
        "required": ["element_description"]
      }
    },
    {
      "name": "vision.read_text",
      "description": "Extract text from screen or region",
      "parameters": {
        "type": "object",
        "properties": {
          "region_hint": {"type": "string", "description": "Optional region description"}
        }
      }
    },
    {
      "name": "vision.suggest_next_action",
      "description": "Suggest next action to achieve goal",
      "parameters": {
        "type": "object",
        "properties": {
          "goal": {"type": "string", "description": "The goal to achieve"}
        },
        "required": ["goal"]
      }
    },
    {
      "name": "vision.describe_live_frame",
      "description": "Fast single-sentence description for streaming",
      "parameters": {"type": "object", "properties": {}}
    }
  ]
}
Execution Pattern
All tool handlers follow this exact pattern:

Capture screenshot (async, run_in_executor) — calls screenshot_to_bytes(), converts to base64
Call provider method (async, run_in_executor) — avoids blocking event loop, sync HTTP client wrapped in executor
Return MCP text result — formatted as MCP content object, returned as JSON-RPC response
2.3 Tool Bridge Integration (CORRECTED — replaces VisionRouter)
Location: backend/agent/tool_bridge.py
Role: AgentToolBridge._mcp_servers dict — vision is a peer MCP server alongside browser, file, system, etc.

NOTE: model_router.py does NOT integrate vision. model_router.py handles text model routing only
(brain/executor). It has no async startup method and no vision attribute. VisionRouter and
model_router_vision_patch.py were removed from the spec — they contradict the core principle
"Vision is a tool, not a model route."

Integration in tool_bridge.py:

python
# ADD import in initialize():
from backend.tools.vision_mcp_server import VisionMCPServer

# ADD to _mcp_servers dict in initialize():
self._mcp_servers = {
    "browser": BrowserServer(),
    "app_launcher": AppLauncherServer(),
    "system": SystemServer(),
    "file_manager": FileManagerServer(),
    "gui_automation": GUIAutomationServer(),
    "internal": InternalCapabilityServer(),
    "vision": VisionMCPServer(),   # <- ADD THIS LINE ONLY
}
2.4 Startup Scripts
start_vl.sh (macOS/Linux)
bash
#!/bin/bash
MODEL_DIR="$HOME/models/LFM2.5-VL-1.6B"
MODEL="$MODEL_DIR/LFM2.5-VL-1.6B-Q4_0.gguf"
MMPROJ="$MODEL_DIR/mmproj-LFM2.5-VL-1.6B-Q4_0.gguf"

llama-server \
  --model "$MODEL" \
  --mmproj "$MMPROJ" \
  --port 8081 \
  --host 127.0.0.1 \
  --n-gpu-layers 1 \
  --ctx-size 4096 \
  --image-max-tokens 256 \
  --verbose
start_vl.bat (Windows)
batch
@echo off
set MODEL=%USERPROFILE%\models\LFM2.5-VL-1.6B\LFM2.5-VL-1.6B-Q4_0.gguf
set MMPROJ=%USERPROFILE%\models\LFM2.5-VL-1.6B\mmproj-LFM2.5-VL-1.6B-Q4_0.gguf

llama-server.exe ^
  --model "%MODEL%" ^
  --mmproj "%MMPROJ%" ^
  --port 8081 ^
  --host 127.0.0.1 ^
  --n-gpu-layers 1 ^
  --ctx-size 4096 ^
  --image-max-tokens 256
⚠️ Critical Flags:

Flag	Value	Reason
--model	Path to Q4_0.gguf	Main model weights
--mmproj	Path to mmproj file	REQUIRED — Vision projector. Without this, server starts but returns blank on all images
--port	8081	Must match agent_config.yaml
--n-gpu-layers	≥1	Avoids CPU-only VL bug in llama.cpp
--image-max-tokens	256	Maximum image tokens to generate
2.5 Configuration: agent_config.yaml
yaml
models:
  # ... existing brain and executor entries — DO NOT MODIFY ...

  - id: "vision"
    provider: "llama_server"
    base_url: "http://localhost:8081/v1"
    capabilities: ["screen_analysis", "ocr", "ui_element_detection"]
    optional: true  # Critical for graceful degradation

mcp_servers:
  # ... existing entries ...
  - name: "vision"
    enabled: true

vision:
  image_max_tokens: 128       # 64 for speed, 256 for detail
  temperature: 0.1            # Liquid AI recommended
  min_p: 0.15                 # Liquid AI recommended
  repetition_penalty: 1.05    # Liquid AI recommended
  screenshot_delay_ms: 100    # Optional delay before capture
3. Integration Points
3.1 Files That Change
File	Change Type	Discovery Steps	Verification
backend/agent/tool_bridge.py	Edit	Find _mcp_servers dict in initialize()	python -c "import asyncio; from backend.agent.tool_bridge import AgentToolBridge; asyncio.run(AgentToolBridge().initialize())"
start-iris.bat	Edit	Find first backend start command	Run start-iris.bat, verify 8081 responding
backend/agent/agent_config.yaml	Edit	Add vision model and config blocks	YAML syntax valid
start_vl.sh	New	Create in project root	chmod +x start_vl.sh
start_vl.bat	New	Create in project root	Test execution
NOTE: model_router.py and main.py do NOT change for vision registration.
3.2 Model Router Integration
Discovery Required:

Read backend/agent/model_router.py fully
Identify __init__ method signature
Find where self.brain and self.executor are initialized
Find startup() or __aenter__ async initialization method
Changes:

python
# ADD at top of file:
from model_router_vision_patch import VisionRouter

# ADD in __init__ (after executor initialization):
self.vision = VisionRouter(config.get("vision", {}))

# ADD in startup/async init (after brain/executor startup):
await self.vision.startup()
3.3 MCP Server Registration
Discovery Required:

Read backend/main.py fully
Search for "MCPServer" or "tool_bridge"
Find where BrowserMCPServer or other MCP servers are registered
If registration is in iris_gateway.py, touch ONLY the server list
Changes:

python
# ADD import:
from backend.tools.vision_mcp_server import VisionMCPServer

# ADD to server list:
mcp_servers = [
    BrowserMCPServer(),
    FileMCPServer(),
    SystemMCPServer(),
    AppLaunchMCPServer(),
    VisionMCPServer(),  # ← ADD THIS LINE ONLY
]
⚠️ If MCP servers are registered in iris_gateway.py: Touch ONLY the server list. Do NOT modify routing logic, gate conditions, WebSocket handling, or message processing.

3.4 Startup Script Integration
Discovery Required: Read start-iris.bat fully, find first backend start command.

Changes (add BEFORE first start command):

batch
echo Starting vision server...
start "LFM-VL Vision" cmd /k "start_vl.bat"
timeout /t 5 /nobreak >nul
echo Vision server started, waiting for backend...
Note: The 5-second wait is critical — the model takes time to load into GPU/CPU memory.

4. Voice → Vision Data Flow
User says: "Click on the search bar"

Step  Component          Action                           Status      Notes
----  ---------          ------                           ------      -----
1     Porcupine          Detect wake word                 [FROZEN]    Unchanged
2     RealtimeSTT        Transcribe speech                [FROZEN]    Unchanged
3     IRIS Gateway       Route to Agent Kernel            [FROZEN]    Unchanged
4     Agent Kernel       Pass to Model Router             [FROZEN]    Unchanged
5     Qwen (Brain)       Decide to use vision             [FROZEN]    Unchanged

══════════════════ EVERYTHING ABOVE IS UNTOUCHED ═════════════════

6     [NEW] Tool Bridge  Route vision.find_ui_element     NEW         MCP routing
7     [NEW] VisionMCPS   Capture screenshot → LFM-VL      NEW         Port 8081
8     [NEW] LFM-VL       Process image, return location   NEW         Vision model

══════════════════ EVERYTHING BELOW IS ALSO UNTOUCHED ════════════

9     Qwen (Brain)       Receive result, plan click       [FROZEN]    Unchanged
10    Qwen (Brain)       Emit: uitars.click               [FROZEN]    Unchanged
11    UI-TARS            Execute click                    [FROZEN]    Unchanged
12    Qwen (Brain)       Generate response                [FROZEN]    Unchanged
13    Agent Kernel       Return response                  [FROZEN]    Unchanged
14    IRIS Gateway       Route to TTS                     [FROZEN]    Unchanged
15    LuxTTS             Speak response                   [FROZEN]    Unchanged
Key Insight: Steps 6–8 are the only new steps. From the voice pipeline's perspective, step 5 and step 9 look identical — Qwen calls a tool and gets a result. The pipeline cannot distinguish between a vision tool call and a filesystem tool call.

5. Dependency Graph
Phase 1: Prerequisites (ALL must complete before Phase 2)
├── [T-01] Install llama-server binary
│         Windows: cmake build with LLAMA_AVX2=ON
│         macOS:   brew install llama.cpp
│         Verify:  llama-server --version
├── [T-02] Download LFM2.5-VL-1.6B-Q4_0.gguf (~696MB)
├── [T-03] Download mmproj-LFM2.5-VL-1.6B-Q4_0.gguf (~300MB) ⚠️ CRITICAL
└── [T-04] pip install mss

Phase 2: File Placement
├── [T-05] Place lfm_vl_provider.py           → backend/tools/
├── [T-06] Place vision_mcp_server.py         → backend/tools/
├── [T-07] Place model_router_vision_patch.py → backend/agent/
├── [T-08] Place start_vl.sh                  → project root (chmod +x)
└── [T-09] Place start_vl.bat                 → project root

Phase 3: Code Integration
├── [T-10] Edit model_router.py (import + init + startup)
├── [T-11] Register VisionMCPServer in main.py
├── [T-12] Update agent_config.yaml
└── [T-13] Update start-iris.bat

Phase 4: Validation
├── [T-14] Start server, verify port 8081
│         Run: start_vl.bat
│         Verify: curl http://localhost:8081/v1/models
├── [T-15] Run test_vision.py
│         Test: Provider health, screenshot, analysis
│         If blank result: Check T-03 (mmproj)
├── [T-16] Run test_vision_mcp.py
│         Test: tools/list, tools/call
├── [T-17] Full IRISVOICE integration test
│         Start: start-iris.bat
│         Test: "What app is open?"
│         Verify: Logs show vision tool call
└── [T-18] Test voice → vision → action loop
          Test: "Click on [element]"
          Verify: Pipeline logs unchanged except vision call
6. Testing Strategy
Phase 1: Prerequisites Validation
python
import subprocess
result = subprocess.run(["llama-server", "--version"], capture_output=True)
assert result.returncode == 0

from pathlib import Path
assert Path("~/models/LFM2.5-VL-1.6B/LFM2.5-VL-1.6B-Q4_0.gguf").expanduser().exists()
assert Path("~/models/LFM2.5-VL-1.6B/mmproj-LFM2.5-VL-1.6B-Q4_0.gguf").expanduser().exists()

import mss  # No ImportError
Phase 2: Component Tests (test_vision.py)
python
from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes

provider = LFMVLProvider()

# Test health check
assert provider.health_check() == True, "Server not reachable"

# Test screenshot
img = screenshot_to_bytes()
assert len(img) > 1000, "Screenshot empty"
assert img[:4] == b'\x89PNG', "Not PNG format"

# Test analysis — blank result = mmproj not loaded
result = provider.analyze_screen(img, "What app is open?")
assert isinstance(result, str)
assert len(result) > 10, "Vision returned blank — check mmproj loaded"
Phase 3: MCP Server Tests (test_vision_mcp.py)
python
import asyncio
from backend.tools.vision_mcp_server import VisionMCPServer

async def test():
    server = VisionMCPServer()

    # Test tools/list
    r = await server.handle({"method": "tools/list", "id": 1, "jsonrpc": "2.0"})
    names = [t["name"] for t in r["result"]["tools"]]
    assert "analyze_screen" in names
    assert "find_ui_element" in names
    assert "suggest_next_action" in names

    # Test tool call
    r2 = await server.handle({
        "method": "tools/call",
        "id": 2,
        "jsonrpc": "2.0",
        "params": {"name": "analyze_screen", "arguments": {}}
    })
    text = r2["result"]["content"][0]["text"]
    assert len(text) > 10, "Tool returned blank"

asyncio.run(test())
Phase 4: Integration Test (test_model_router.py)
python
import asyncio, yaml
from backend.agent.model_router import ModelRouter

async def test():
    with open('backend/agent/agent_config.yaml') as f:
        config = yaml.safe_load(f)

    router = ModelRouter(config)
    await router.startup()

    assert hasattr(router, 'vision'), "Vision not added to ModelRouter"

    result = await router.vision.analyze("What is on screen?")
    assert isinstance(result, str)
    assert len(result) > 5

asyncio.run(test())
Phase 4: End-to-End Validation
Start IRISVOICE normally (start-iris.bat)
Verify log: "Vision router ready (LFM2.5-VL-1.6B @ http://localhost:8081/v1)"
Text input: "What app is currently open?"
Expected: Accurate description of current screen
Verify logs: vision tool call appears in audit trail
Verify: Voice pipeline logs show unchanged flow
7. File Locations Summary
IRISVOICE/
├── start_vl.sh                          ← NEW: Vision server startup (macOS/Linux)
├── start_vl.bat                         ← NEW: Vision server startup (Windows)
├── start-iris.bat                       ← EDIT: Add vision startup before backend
├── backend/
│   ├── main.py                          ← EDIT: Register VisionMCPServer
│   ├── agent/
│   │   ├── agent_config.yaml            ← EDIT: Add vision model + config blocks
│   │   ├── model_router.py              ← EDIT: Import + init + startup VisionRouter
│   │   └── model_router_vision_patch.py ← NEW: VisionRouter class definition
│   └── tools/
│       ├── lfm_vl_provider.py           ← NEW: HTTP client for llama-server
│       ├── vision_mcp_server.py         ← NEW: MCP server exposing vision tools
│       └── vision_system.py            ← DELETED: Replaced by VisionMCPServer
└── models/
    └── LFM2.5-VL-1.6B/
        ├── LFM2.5-VL-1.6B-Q4_0.gguf   ← DOWNLOAD: Main model (~696MB)
        └── mmproj-LFM2.5-VL-1.6B-Q4_0.gguf ← DOWNLOAD: Vision projector (~300MB) CRITICAL
8. Rollback Conditions
Failure	Symptom	Action
llama-server won't start	Port binding error or model load error	Check --mmproj path, verify T-02 and T-03 files
health_check returns False	Connection refused	Verify port 8081 not in use, check server terminal
Vision returns blank	Model responds but describes black screen	mmproj not loaded — verify --mmproj flag
model_router.py import error	ImportError on startup	Check file is in backend/agent/, check Python path
MCP server not registering	Vision tools not in tools/list	Find where other MCPServers are registered, verify T-11
IRISVOICE crashes on startup	Exception in VisionRouter	Wrap startup in try/except, verify optional: true in config
Slow responses (>5s)	CPU-only inference	Set --n-gpu-layers 1 minimum — even integrated GPU works
9. Optional: System Prompt Tuning
To encourage Qwen to use vision proactively, add to personality.py or agent_config.yaml system prompt (brain model only):

Before clicking, typing, or interacting with any desktop element,
use vision.analyze_screen or vision.find_ui_element to confirm
the current screen state. Never assume element positions.
⚠️ Add only to brain model system prompt, not to gateway or pipeline config.

End of Design Specification

