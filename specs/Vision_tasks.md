# Vision Layer Implementation Tasks
# IRISVOICE v4 — LFM2.5-VL Integration
# Replaces: MiniCPM-o4.5 (Ollama) → LFM2.5-VL-1.6B (llama-server port 8081)

Status: ACTIVE
Branch: IRISVOICEv.4
Gate: 4 (Free Range)

---

## HOW TO USE THIS FILE

READ spec → READ existing file → BUILD → RUN spec test → PASS → RECORD landmark
                                                         → FAIL → fix code → retry

The test is the requirement. Never modify tests to make them pass. Fix the code.

---

## PREREQUISITES (manual — must be done before T-14)

[ ] Download LFM2.5-VL-1.6B-Q4_0.gguf (~696MB)
[ ] Download mmproj-LFM2.5-VL-1.6B-Q4_0.gguf (~300MB)  ← CRITICAL — without this, vision returns blank
[ ] pip install mss httpx
[ ] Port 8081 available (not used by LM Studio or other services)
[ ] llama-server binary installed (cmake build with LLAMA_AVX2=ON on Windows, or brew install llama.cpp)

Download script:
  python -c "
  from huggingface_hub import hf_hub_download
  import os
  base = os.path.expanduser('~/models/LFM2.5-VL-1.6B/')
  os.makedirs(base, exist_ok=True)
  hf_hub_download('LiquidAI/LFM2.5-VL-1.6B-GGUF', 'LFM2.5-VL-1.6B-Q4_0.gguf', local_dir=base)
  hf_hub_download('LiquidAI/LFM2.5-VL-1.6B-GGUF', 'mmproj-LFM2.5-VL-1.6B-Q4_0.gguf', local_dir=base)
  print('Done')
  "

---

## PHASE 0 — SPEC SYNC (no code, no tests)

### T-00a: Update Vision_Design.md
- What: Correct architecture mismatches from spec draft
- File: specs/Vision_Design.md
- Changes:
  - §3.3 MCP Registration: was main.py → actual: tool_bridge.py _mcp_servers dict
  - §3.2 Model Router: remove VisionRouter + model_router_vision_patch.py (model_router has no async startup)
  - §2.3 VisionRouter class: remove entire section
  - §7 File Locations: vision_system.py is DELETED not "EXISTING: Unchanged"
- Status: DONE

### T-00b: Update Vision_requirements.md
- What: Remove Ollama references, confirm llama_server provider
- File: specs/Vision_requirements.md
- Status: DONE

---

## PHASE 1 — DELETE MINICPM

### T-01: Delete MiniCPM core files
- What: Remove the deprecated MiniCPM implementation entirely
- Files to DELETE:
  - backend/vision/minicpm_client.py
  - backend/vision/vision_service.py
  - backend/agent/gui_toolkit.py
  - backend/tools/vision_system.py
- Verify: python -c "from backend.vision import MiniCPMClient" → should raise ImportError

### T-02: Stub backend/vision/__init__.py
- What: Remove MiniCPMClient exports, leave minimal module
- File: backend/vision/__init__.py
- Before: exports MiniCPMClient, get_minicpm_client
- After: empty or exports only ScreenCapture if that file exists
- Verify: python -c "import backend.vision" → no ImportError

### T-03: Clean automation/vision.py
- What: Remove MINICPM_OLLAMA provider + _minicpm_client code
- File: backend/automation/vision.py
- Keep: VisionModelClient stub with Anthropic provider only
- Remove: VisionProvider.MINICPM_OLLAMA enum, _minicpm_client attr, _detect_with_minicpm(), MiniCPMClient import
- Verify: python -c "from backend.automation import VisionModelClient" → no ImportError

### T-04: Clean automation/__init__.py
- What: Remove any MiniCPMClient re-exports
- File: backend/automation/__init__.py
- Verify: python -c "import backend.automation" → no ImportError

---

## PHASE 2 — CREATE LFM2.5-VL PROVIDER

### T-05: Create lfm_vl_provider.py
- File: backend/tools/lfm_vl_provider.py
- Must implement:
  - LFMVLConfig dataclass (base_url, temperature, min_p, repetition_penalty, image_max_tokens, timeout)
  - LFMVLProvider class:
    - health_check() -> bool  (GET /v1/models, returns False if unreachable)
    - analyze_screen(img_bytes, question="") -> str
    - find_ui_element(img_bytes, description) -> dict  ({found, location_hint})
    - read_text(img_bytes, region=None) -> str
    - suggest_action(img_bytes, goal) -> dict  ({action, target, reasoning})
    - describe_live_frame(img_bytes) -> str
  - screenshot_to_bytes(region=None) -> bytes  (mss, PNG, <5ms)
- All methods: return error string on any failure, never raise
- Sampling: temperature=0.1, min_p=0.15, repetition_penalty=1.05
- Verify: python -c "from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes; print('OK')"

### T-06: Create start_vl.bat
- File: start_vl.bat (project root — IRISVOICE/)
- Flags: --model, --mmproj, --port 8081, --host 127.0.0.1, --n-gpu-layers 1, --ctx-size 4096, --image-max-tokens 256
- Paths: %USERPROFILE%\models\LFM2.5-VL-1.6B\

### T-07: Create start_vl.sh
- File: start_vl.sh (project root — IRISVOICE/)
- Same flags, bash syntax, chmod +x

---

## PHASE 3 — CREATE VISION MCP SERVER

### T-08: Create vision_mcp_server.py
- File: backend/tools/vision_mcp_server.py
- Pattern: identical to backend/mcp/gui_automation_server.py (stdio JSON-RPC)
- Must implement:
  - VisionMCPServer class
  - handle(request: dict) -> dict  (JSON-RPC dispatcher)
  - _handle_tools_list() → 5 tool schemas with vision. prefix
  - _handle_tools_call(params) → capture screenshot → call provider → return MCP content
  - serve_stdio()  (main stdin/stdout loop)
- 5 tools: vision.analyze_screen, vision.find_ui_element, vision.read_text,
           vision.suggest_next_action, vision.describe_live_frame
- All tool handlers: wrapped in try/except, return {"content": [{"type":"text","text":"..."}]}
- Verify: python -c "from backend.tools.vision_mcp_server import VisionMCPServer; print('OK')"
- Test: python -m pytest backend/tests/test_vision_mcp.py -v

---

## PHASE 4 — WIRE TOOL_BRIDGE

### T-09: Edit backend/agent/tool_bridge.py
- File: backend/agent/tool_bridge.py
- Remove:
  - VisionSystem init block (~lines 94-102): from backend.tools.vision_system import get_vision_system
  - VisionModelClient init block (~lines 104-111): from backend.automation import VisionModelClient
  - self._vision_system and self._vision_client attrs from __init__
- Add to _mcp_servers dict in initialize():
    from backend.tools.vision_mcp_server import VisionMCPServer
    "vision": VisionMCPServer(),
- Update get_screen_context handler to route through _mcp_servers["vision"] instead of self._vision_system
- Update get_status() to remove vision_system_available key (or set based on "vision" in _mcp_servers)
- Verify: python -c "
  import asyncio
  from backend.agent.tool_bridge import AgentToolBridge
  async def t():
    b = AgentToolBridge()
    await b.initialize()
    assert 'vision' in b._mcp_servers
    print('[+] vision wired into tool bridge')
  asyncio.run(t())
  "

---

## PHASE 5 — UPDATE IRIS_GATEWAY VISION HANDLER

### T-10: Update vision enable/disable in iris_gateway.py
- File: backend/iris_gateway.py
- Find: handler for "enable_vision" WebSocket message (~line 1520 area)
- Replace: MiniCPM availability check with LFMVLProvider.health_check()
- Send vision_status WebSocket message:
  {
    "type": "vision_status",
    "status": "enabled" if available else "error",
    "model_name": "lfm2.5-vl",
    "is_available": available,
    "vram_usage_mb": null,
    "load_progress_percent": null,
    "error_message": null or "Vision server not running on port 8081"
  }
- Also update model validation list (~line 1522): replace "minicpm" with "lfm2.5-vl"
- Verify: backend starts without error after this change

---

## PHASE 6 — FRONTEND SYNC

### T-11: Update data/cards.ts
- File: data/cards.ts
- Vision card vision_model dropdown:
  options: ['lfm2.5-vl', 'llava', 'bakllava']  (was: ['minicpm-o4.5', 'llava', 'bakllava'])
  defaultValue: 'lfm2.5-vl'  (was: 'minicpm-o4.5')
- Desktop control vision_model_provider dropdown:
  options: ['llama_server', 'anthropic', 'volcengine', 'local']  (was: ['minicpm_ollama', ...])
  defaultValue: 'llama_server'  (was: 'minicpm_ollama')

### T-12: Update hooks/useIRISWebSocket.ts
- File: hooks/useIRISWebSocket.ts
- Default VisionStatus model_name: "lfm2.5-vl"  (was: "minicpm-o4.5")
- Verify: no other MiniCPM string references remain

---

## PHASE 7 — REMAINING BACKEND FILE EDITS

### T-13a: Update backend/core_models.py
- vision_model dropdown options: 'lfm2.5-vl' default (was minicpm-o4.5)
- vision_model_provider: 'llama_server' default (was minicpm_ollama)

### T-13b: Update backend/models.py
- Same dropdown changes as core_models.py

### T-13c: Update backend/core/models.py
- model_name default: "lfm2.5-vl" (was "minicpm-o4.5")

### T-13d: Update backend/config/config_loader.py
- Update enable_vision_system comments (no logic change needed)

### T-13e: Update backend/agent/agent_config.yaml
- Replace vision model block:
  id: "vision"
  provider: "llama_server"
  base_url: "http://localhost:8081/v1"
  capabilities: ["screen_analysis", "ocr", "ui_element_detection"]
  optional: true
- Add vision config block:
  vision:
    image_max_tokens: 128
    temperature: 0.1
    min_p: 0.15
    repetition_penalty: 1.05

### T-13f: Update start-iris.bat
- Add vision server launch before backend start:
  echo Starting vision server...
  start "LFM-VL Vision" cmd /k "start_vl.bat"
  timeout /t 5 /nobreak >nul

---

## PHASE 8 — TESTS (run only when 95% confident integration is complete)

### T-14: Create backend/tests/test_vision_mcp.py
- Tests: MCP schema validation + agent tool bridge dispatch
- Does NOT require llama-server running
- Commands:
  python -m pytest backend/tests/test_vision_mcp.py -v
- On FAIL: fix code, not tests

### T-15: Create backend/tests/test_vision_integration.py
- Tests: Real LFM2.5-VL via llama-server
- REQUIRES: start_vl.bat running, model files downloaded
- Commands:
  python -m pytest backend/tests/test_vision_integration.py -v
- On FAIL: check mmproj loaded, check port 8081, fix provider code

---

## VERIFICATION SEQUENCE

After all phases complete:

1. MiniCPM gone:
   python -c "from backend.vision import MiniCPMClient" 2>&1
   # Expected: ImportError or ModuleNotFoundError

2. New files importable:
   python -c "from backend.tools.lfm_vl_provider import LFMVLProvider; print('[+] OK')"
   python -c "from backend.tools.vision_mcp_server import VisionMCPServer; print('[+] OK')"

3. Tool bridge wired:
   python -c "
   import asyncio
   from backend.agent.tool_bridge import AgentToolBridge
   async def t():
       b = AgentToolBridge()
       await b.initialize()
       assert 'vision' in b._mcp_servers
       print('[+] Vision wired')
   asyncio.run(t())"

4. MCP tests pass:
   python -m pytest backend/tests/test_vision_mcp.py -v

5. Integration tests pass (with server running):
   python -m pytest backend/tests/test_vision_integration.py -v

6. Full backend starts clean:
   python -c "
   import sys; sys.path.insert(0, '.')
   from backend.agent.tool_bridge import AgentToolBridge
   from backend.agent.model_router import ModelRouter
   print('[+] Backend imports clean')
   "

---

## LANDMARK RECORDING

After T-15 passes:
  python bootstrap/agent_context.py --complete VISION_IMPL claude_main success \
    --landmark "vision_layer:LFM2.5-VL MCP vision live, MiniCPM removed:backend/tools/vision_mcp_server.py:python -m pytest backend/tests/test_vision_mcp.py -v"
