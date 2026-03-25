PRD: LFM2.5-VL Vision Layer Integration
Product: IRISVOICE v4
Status: Draft
Date: March 2026
Branch: IRISVOICEv.4
Repository: https://github.com/Midast0uch/IRISVOICE/tree/IRISVOICEv.4
Target Release: v4.1.0

1. Executive Summary
1.1 Objective
Add desktop vision capabilities to IRISVOICE by integrating LFM2.5-VL-1.6B as a dedicated vision layer ("eyes") while maintaining the existing dual-LLM architecture and frozen voice pipeline.

1.2 Key Principle
Vision is a tool, not a voice pipeline component and not a model route.

The voice pipeline (Porcupine → RealtimeSTT → IRIS Gateway → Session Manager) remains completely sealed and unaware of vision's existence. Vision integrates exclusively at the MCP (Model Context Protocol) tool layer, below the Agent Kernel.

1.3 Integration Point
Vision exposes capabilities via MCP through the Tool Bridge, allowing the Brain (Qwen/LFM2-8B or any OpenAI-compatible replacement) to call vision tools the same way it calls filesystem or browser tools.

1.4 Success Criteria
Voice pipeline latency remains <50ms p95 (zero regression)
Vision tool calls complete in <2s for live frame description, <5s for full analysis
System operates normally if vision server is unavailable (graceful degradation)
No modifications to any files in backend/voice/ or gateway routing logic
2. Project Context
Component	Current Implementation
Brain	Any OpenAI-compatible model (currently Qwen 3.5 via LM Studio on port 1234)
Executor	LFM2.5-1.2B-Instruct (local, tool execution)
Voice	Porcupine wake word + RealtimeSTT (Whisper) + LuxTTS
Tools	MCP servers over stdio (browser, file, system, app_launch) — registered in AgentToolBridge._mcp_servers
Desktop Control	UI-TARS
Memory	Mycelium coordinate-graph memory layer
What this spec adds: LFM2.5-VL-1.6B as a dedicated vision layer — the "eyes" of the assistant.
What this spec removes: MiniCPM-o4.5 (Ollama-based) — all backend/vision/minicpm_client.py,
  backend/vision/vision_service.py, backend/agent/gui_toolkit.py, backend/tools/vision_system.py deleted.

3. Functional Requirements
FR-01: Vision Model Server
ID	Requirement	Priority
FR-01.1	System SHALL run LFM2.5-VL-1.6B via llama-server on localhost:8081	P0
FR-01.2	Server SHALL load both main GGUF and mmproj file on startup	P0
FR-01.3	Server SHALL remain running independently of main IRISVOICE backend	P0
FR-01.4	Server SHALL start before FastAPI backend initialization	P0
FR-01.5	Server SHALL expose OpenAI-compatible /v1/chat/completions endpoint	P0
⚠️ Critical: The mmproj file is mandatory. Without it, the server starts but silently ignores all images, returning blank descriptions.

FR-02: Screen Capture
ID	Requirement	Priority
FR-02.1	Capture full-screen PNG screenshots on-demand	P0
FR-02.2	Support optional region capture (x, y, width, height)	P1
FR-02.3	Capture latency <50ms	P0
FR-02.4	Use mss as primary capture backend	P0
FR-02.5	Cross-platform support (Windows, macOS, Linux)	P0
FR-03: Vision MCP Tools
The system SHALL expose the following tools via MCP over stdio:

Tool	Input	Output	Latency Target	Use Case
vision.analyze_screen	question (optional), region (optional)	Text description	<5s	General screen understanding
vision.find_ui_element	element_description (string)	{found: bool, location_hint: string}	<3s	Locate buttons, inputs, etc.
vision.read_text	region_hint (optional)	Extracted text string	<3s	OCR for forms, documents
vision.suggest_next_action	goal (string)	{action, target, reasoning}	<5s	Workflow guidance
vision.describe_live_frame	none	Single sentence description	<2s	Fast streaming/loop updates
FR-04: Model-Agnostic Integration
ID	Requirement	Priority
FR-04.1	Vision tools SHALL be exposed as standard MCP tools callable by any brain model	P0
FR-04.2	No vision-specific logic SHALL exist in model_router.py beyond VisionRouter initialization	P0
FR-04.3	Brain model (Qwen or any OpenAI-compatible replacement) SHALL call vision tools identically to other MCP tools	P0
FR-04.4	System SHALL NOT hardcode assumptions about which brain model is running	P0
FR-04.5	Vision tools SHALL appear in MCP tools list with the vision. prefix	P0
FR-05: Graceful Degradation
ID	Requirement	Priority
FR-05.1	If vision server is unreachable, IRISVOICE SHALL start and operate normally	P0
FR-05.2	Vision tool calls when server is down SHALL return clear error strings, not raise exceptions	P0
FR-05.3	Agent kernel SHALL log a warning but NOT throw an exception if vision is unavailable	P0
FR-05.4	Mark vision as optional: true in agent_config.yaml	P0
FR-05.5	Transformers-based fallback SHALL be available for CPU-only environments	P1
FR-05.6	Vision unavailability SHALL NOT block or delay other tool calls	P0
FR-06: Voice Pipeline Freeze — ABSOLUTE CONSTRAINTS
The following files MUST NOT be modified under any circumstances:

backend/voice/audio_engine.py
backend/voice/voice_pipeline.py
backend/voice/porcupine_detector.py
backend/iris_gateway.py (except MCP registration if applicable)
backend/ws_manager.py
backend/core/ — entire directory
backend/sessions/ — entire directory
backend/state_manager.py
Any gates logic
WebSocket message format
Vision integrates exclusively at the MCP tool layer. When Qwen calls a vision tool, it looks identical to calling a filesystem tool from the perspective of every layer above and below the Tool Bridge.

FR-07: Windows Compatibility
ID	Requirement	Priority
FR-07.1	All startup scripts SHALL be runnable on Windows 10/11	P0
FR-07.2	A start_vl.bat file SHALL exist alongside start_vl.sh	P0
FR-07.3	start-iris.bat SHALL be updated to launch vision server before backend	P0
FR-07.4	Vision server startup SHALL include a 5-second wait before backend initialization	P0
FR-08: Audit Trail
ID	Requirement	Priority
FR-08.1	Every vision tool call SHALL be logged with: timestamp, tool name, arguments, latency_ms	P0
FR-08.2	Vision logs SHALL follow the same format as existing tool audit logs	P0
FR-08.3	Logs SHALL write to the standard IRISVOICE log directory	P0
4. Non-Functional Requirements
NFR-01: Performance
Metric	Target	Critical
describe_live_frame latency	<2s on target hardware	Yes
analyze_screen latency	<5s	Yes
find_ui_element latency	<3s	Yes
Screen capture overhead	<50ms	Yes
Tool call serialization	<10ms	No
Total voice-to-vision latency	<3s added	Yes
Target Hardware: CPU with ≥1 GPU layer (Intel/AMD iGPU acceptable), 16GB RAM minimum

NFR-02: Resource Usage
Resource	Limit	Notes
Vision server RAM	≤4GB	Q4_0 quantization
Backend integration overhead	<50MB	HTTP client only
Process isolation	Required	Vision server separate from backend
Port usage	8081	Must not conflict with LM Studio (1234) or backend (8000)
NFR-03: Reliability
Requirement	Implementation
Health check polling	Every 30s via VisionRouter
Retry policy	1 retry before returning error
Crash isolation	Vision server crash SHALL NOT crash backend
Startup resilience	Backend starts successfully even if vision server is down
Connection recovery	Reconnect attempts every 30s when server available
NFR-04: Security
Requirement	Implementation
Local-only binding	llama-server SHALL bind to 127.0.0.1 only
No credential exposure	Vision server SHALL NOT require API keys
Screenshot privacy	Screenshots processed in-memory only, never persisted to disk
Tool execution safety	Vision suggestions validated by executor before UI-TARS execution
NFR-05: Compatibility
Platform	Status
Windows 10/11	Primary (AVX2 optimized)
macOS	Supported (brew install)
Linux	Supported
5. Out of Scope
The following are explicitly NOT included in this integration:

Fine-tuning or modifying the LFM2.5-VL model
Replacing or removing vision_system.py (both systems coexist)
Continuous background screen monitoring (future feature)
Multi-monitor support beyond primary monitor
Video stream processing (frame-by-frame only)
Any modifications to voice pipeline, gateway, WebSocket, or gates system
Database schema changes, API endpoint changes, authentication changes
6. Acceptance Criteria
Phase 1: Prerequisites
 llama-server --version executes without error
 LFM2.5-VL-1.6B-Q4_0.gguf exists in ~/models/LFM2.5-VL-1.6B/
 mmproj-LFM2.5-VL-1.6B-Q4_0.gguf exists in same directory
 pip install mss completes successfully
 Port 8081 is available (no conflicts)
Phase 2: File Placement
 backend/tools/lfm_vl_provider.py exists
 backend/tools/vision_mcp_server.py exists
 backend/agent/model_router_vision_patch.py exists
 start_vl.sh exists in project root (executable)
 start_vl.bat exists in project root
Phase 3: Integration
 backend/agent/model_router.py imports VisionRouter without error
 backend/main.py registers VisionMCPServer in MCP server list
 backend/agent/agent_config.yaml contains vision model block
 start-iris.bat starts vision server before backend
 No syntax errors in any modified files
Phase 4: Validation
 Vision server starts and responds on port 8081
 test_vision.py passes (provider health, screenshot, analysis)
 test_vision_mcp.py passes (tools/list, tools/call)
 Full IRISVOICE starts with "Vision router ready" log message
 Text command "What app is open?" returns accurate screen description
 Voice command "Click on [element]" triggers vision tool call in logs
 Voice pipeline logs show unchanged flow (zero regression)
7. Risk Analysis
Risk	Probability	Impact	Mitigation
mmproj file missing	High	Critical (blank responses)	Explicit verification step in startup, clear error messages
Port 8081 conflict	Medium	High (server won't start)	Port availability check in start script, configurable port
CPU-only inference	Medium	High (slow/unusable)	Document GPU requirement, provide transformers fallback
Voice pipeline regression	Low	Critical	Strict freeze policy, comprehensive regression testing
Model file corruption	Low	High	Checksum verification, re-download instructions
8. Rollback Conditions
Failure Symptom	Likely Cause	Action
llama-server won't start	Missing mmproj or wrong path	Verify T-03, check start_vl.sh flags
health_check returns False	Port 8081 in use or server not started	Check port availability, verify T-13
Vision returns blank/black	mmproj not loaded	Verify --mmproj flag in start_vl.sh
Import errors	Wrong file placement	Verify T-05, T-06, T-07 file locations
MCP not registering	Wrong registration location	Verify T-10 matches existing pattern
Slow responses (>5s)	CPU-only inference	Set --n-gpu-layers 1 minimum
9. Appendix
Model Files Reference
File	Size	Purpose	Critical
LFM2.5-VL-1.6B-Q4_0.gguf	~696MB	Main vision model weights	Yes
mmproj-LFM2.5-VL-1.6B-Q4_0.gguf	~300MB	Vision projection layer	CRITICAL
Download Command:

python
from huggingface_hub import hf_hub_download
import os

base = os.path.expanduser("~/models/LFM2.5-VL-1.6B/")
os.makedirs(base, exist_ok=True)

# Main model
hf_hub_download("LiquidAI/LFM2.5-VL-1.6B-GGUF",
                "LFM2.5-VL-1.6B-Q4_0.gguf",
                local_dir=base)

# Vision projector - DO NOT SKIP
hf_hub_download("LiquidAI/LFM2.5-VL-1.6B-GGUF",
                "mmproj-LFM2.5-VL-1.6B-Q4_0.gguf",
                local_dir=base)
Quick Reference Commands
bash
# Start vision server manually
bash start_vl.sh

# Check if running
curl http://localhost:8081/v1/models

# Stop vision server (macOS/Linux)
pkill -f llama-server

# Stop vision server (Windows)
taskkill /F /IM llama-server.exe

# Run tests
python test_vision.py
python test_vision_mcp.py
Glossary
Term	Definition
GGUF	GPT-Generated Unified Format — quantized model file format for llama.cpp
MCP	Model Context Protocol — standard for model tool integration
mmproj	Multimodal projection file — required for vision models in llama.cpp
LFM	Liquid Foundation Model — AI model family from Liquid AI
VL	Vision-Language — multimodal model processing both images and text
UI-TARS	Desktop automation tool for executing UI actions
Mycelium	IRISVOICE's coordinate-graph memory system
End of PRD

