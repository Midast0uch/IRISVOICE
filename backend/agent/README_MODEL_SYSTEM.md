# Model System Documentation

## Overview

IRIS uses a flexible single-LLM architecture for reasoning and conversation, with a
dedicated small model for structured tool calls.

| Component | Model | Role |
|-----------|-------|------|
| **LLM (brain)** | Any GGUF model (user's choice) | Conversation, reasoning, planning |
| **Executor** | LFM2.5-1.2B-Instruct | Structured tool call generation only |
| **Vision** (optional) | LFM2.5-VL-1.6B | Screen analysis, GUI interaction |

The LFM2-8B "brain" model from the original dual-LLM design has been removed. The
**user selects their own GGUF model** in Settings → Models Browser. That model is served
via llama-cpp-python on port 8082 (OpenAI-compatible) and handles all conversation and
reasoning. LFM2.5-1.2B-Instruct is only invoked when a tool call needs to be structured.

---

## Components

### ModelWrapper

`ModelWrapper` provides a consistent interface for an individual LLM.

**Key Features:**
- Lazy loading — model loads on first use, not at startup
- Health checking via `health_check()`
- Capability tracking
- Device management (auto GPU/CPU)

**Usage:**
```python
from agent.model_wrapper import ModelWrapper

wrapper = ModelWrapper(
    model_id="executor",
    model_path="./models/LFM2.5-1.2B-Instruct",
    capabilities=["tool_execution", "instruction_following"],
    constraints={"device": "cpu", "dtype": "float32"}
)

if not wrapper.is_loaded():
    wrapper.load()

response = wrapper.generate("Call the file_read tool with path=/tmp/test.txt")
health = wrapper.health_check(load_if_needed=True)
```

### ModelRouter

`ModelRouter` routes messages to the appropriate model.

**Routing Logic:**
1. **Tool execution requests** → executor (LFM2.5-1.2B-Instruct)
   - Detects keywords: "execute", "run", "call", "invoke", "tool:", etc.
   - Also triggered by `context={"requires_tools": True}`
2. **All other requests** → gguf_local (user's GGUF model on port 8082)

**Usage:**
```python
from agent.model_router import ModelRouter

router = ModelRouter()

# Automatic routing
model_id = router.route_message("What is the best strategy?")
# Returns: "gguf_local"

model_id = router.route_message("Execute the file operation")
# Returns: "executor"

# Explicit routing
model_id = router.route_message("Some message", context={"requires_tools": True})
# Returns: "executor"
```

### LocalModelManager

`LocalModelManager` manages the user's GGUF model:
- Spawns llama-cpp-python server on port 8082
- Activated only when the user picks a model in the Models Browser
- Never auto-loads at startup (lazy by design)
- Health-checked with exponential backoff (1 s → 2 s → 4 s → 8 s cap)

---

## Configuration

`backend/agent/agent_config.yaml`:

```yaml
models:
  # Tool calls — LFM2.5-1.2B-Instruct
  - id: "executor"
    path: "./models/LFM2.5-1.2B-Instruct"
    capabilities: ["tool_execution", "instruction_following"]
    constraints:
      device: "cpu"
      dtype: "float32"
    optional: true

  # User's GGUF model — loaded on demand via LocalModelManager
  - id: "gguf_local"
    path: null
    capabilities: ["conversation", "tool_execution", "reasoning"]
    constraints:
      inference_server_url: "http://127.0.0.1:8082/v1"
      auto_load: false
    optional: true

  # Vision (optional)
  - id: "vision"
    path: null
    capabilities: ["vision", "gui_interaction"]
    constraints:
      vision_server_url: "http://localhost:8081/v1"
      auto_load: false
    optional: true
```

---

## VRAM / RAM guidance

IRIS itself uses **no VRAM at startup**. All heavy models are lazy:

| Component | Load trigger | Typical VRAM |
|-----------|-------------|-------------|
| GGUF LLM (8B Q4_K_M) | User clicks Load in Models Browser | ~5 GB |
| LFM2.5-1.2B executor | First tool call | CPU only |
| F5-TTS (Cloned Voice) | First speech synthesis | CPU only, ~800 MB RAM |
| Piper (Built-in TTS) | First speech synthesis | CPU only, ~65 MB RAM |
| Whisper STT | First voice command | CPU only |
| LFM2.5-VL vision | Vision toggle in Settings | ~1 GB VRAM |

On an RTX 3070 (8 GB VRAM), loading an 8B model leaves ~3 GB free — enough for vision
but not a second large LLM. This is why the lfm2-8b "brain" was removed.

---

## Integration with Agent Kernel

`AgentKernel` orchestrates the full pipeline:

1. **Text/voice input** received
2. **TaskClassifier** classifies: `do_it_myself` / `spawn_children` / `delegate_external`
3. **DER loop** (`_execute_plan_der`): Director plans → Explorer executes → Reviewer validates
4. When a step needs tools → `ModelRouter.route_message()` selects the executor model
5. **Tool Bridge** dispatches MCP calls and returns results
6. Response streamed back to the frontend via WebSocket

See `agent_kernel.py` for full implementation.
