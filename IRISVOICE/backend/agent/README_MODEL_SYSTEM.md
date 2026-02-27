# Model System Documentation

## Overview

The IRISVOICE backend uses a dual-LLM architecture with two specialized models:
- **lfm2-8b**: Reasoning and planning model (brain)
- **lfm2.5-1.2b-instruct**: Tool execution and instruction following model (executor)

## Components

### ModelWrapper

The `ModelWrapper` class provides a consistent interface for interacting with individual LLM models.

**Key Features:**
- Lazy loading: Models are loaded on first use, not during initialization
- Health checking: Verify model functionality with `health_check()`
- Capability tracking: Each model declares its capabilities
- Device management: Automatic GPU/CPU selection
- Status reporting: Get detailed model status information

**Usage:**
```python
from agent.model_wrapper import ModelWrapper

# Create a wrapper (model not loaded yet)
wrapper = ModelWrapper(
    model_id="brain",
    model_path="./models/LFM2-8B-A1B",
    capabilities=["reasoning", "planning"],
    constraints={"device": "cuda", "dtype": "bfloat16"}
)

# Check if model is loaded
if not wrapper.is_loaded():
    wrapper.load()  # Explicitly load

# Generate a response
response = wrapper.generate("What is the best approach?")

# Check health
health = wrapper.health_check(load_if_needed=True)
print(health)  # {'healthy': True, 'model_id': 'brain', ...}
```

### ModelRouter

The `ModelRouter` class intelligently routes messages to the appropriate model based on task type.

**Key Features:**
- Automatic task type detection
- Context-based routing hints
- Capability-based model selection
- Health monitoring for all models
- Status reporting

**Routing Logic:**
1. **Tool execution requests** → execution model (lfm2.5-1.2b-instruct)
   - Detects keywords: "execute", "run", "call", "invoke", "tool:", etc.
2. **Planning and reasoning** → reasoning model (lfm2-8b)
   - Default for general queries and planning tasks
3. **Context hints** → Explicit routing via context dictionary

**Usage:**
```python
from agent.model_router import ModelRouter

# Initialize router (loads config from agent_config.yaml)
router = ModelRouter()

# Route a message automatically
model_id = router.route_message("What is the best strategy?")
# Returns: "brain" (reasoning model)

model_id = router.route_message("Execute the file operation")
# Returns: "executor" (execution model)

# Route with explicit context
model_id = router.route_message(
    "Some message",
    context={"requires_tools": True}
)
# Returns: "executor"

# Get specific models
reasoning_model = router.get_reasoning_model()
execution_model = router.get_execution_model()

# Check health of all models
health = router.check_all_models_health(load_if_needed=False)
```

## Configuration

Models are configured in `backend/agent/agent_config.yaml`:

```yaml
models:
  - id: "brain"
    path: "./models/LFM2-8B-A1B"
    capabilities: ["reasoning", "planning"]
    constraints:
      device: "cuda"
      dtype: "bfloat16"
    optional: false

  - id: "executor"
    path: "./models/LFM2.5-1.2B-Instruct"
    capabilities: ["tool_execution", "instruction_following"]
    constraints:
      device: "cuda"
      dtype: "bfloat16"
    optional: false
```

## Model Capabilities

### Reasoning Model (lfm2-8b)
- **Capabilities**: reasoning, planning
- **Use Cases**:
  - Analyzing user requests
  - Creating execution plans
  - Generating reasoning traces
  - Answering general queries

### Execution Model (lfm2.5-1.2b-instruct)
- **Capabilities**: tool_execution, instruction_following
- **Use Cases**:
  - Executing tool calls
  - Processing tool results
  - Following specific instructions
  - Generating action-oriented responses

## Health Checking

Both ModelWrapper and ModelRouter support health checking:

```python
# Check individual model health
wrapper = ModelWrapper(...)
health = wrapper.health_check(load_if_needed=True)
# Returns: {'healthy': True/False, 'model_id': '...', 'error': '...'}

# Check all models
router = ModelRouter()
all_health = router.check_all_models_health(load_if_needed=False)
# Returns: {'brain': {...}, 'executor': {...}}
```

## Status Reporting

Get detailed status information:

```python
# Individual model status
status = wrapper.get_status()
# Returns: {
#   'model_id': 'brain',
#   'model_path': './models/LFM2-8B-A1B',
#   'capabilities': ['reasoning', 'planning'],
#   'loaded': True/False,
#   'device': 'cuda',
#   'dtype': 'bfloat16',
#   'constraints': {...}
# }

# All models status
router = ModelRouter()
all_status = router.get_all_models_status()
```

## Error Handling

The system handles various error scenarios:

1. **Model file not found**: Logs warning, model remains unloaded
2. **Model loading failure**: Logs error, model marked as unavailable
3. **No models available**: `route_message()` raises RuntimeError
4. **Health check failure**: Returns error details in health dict

## Testing

Run the test suite:

```bash
python -m pytest tests/test_model_router.py -v
```

Tests cover:
- Router initialization
- Model retrieval by capability
- Message routing (reasoning vs execution)
- Context-based routing
- Capability listing
- Status reporting
- Model wrapper initialization
- Lazy loading behavior

## Integration with Agent Kernel

The ModelRouter is used by the AgentKernel to coordinate the dual-LLM system:

1. **Reasoning Phase**: Route to lfm2-8b for analysis and planning
2. **Execution Phase**: Route to lfm2.5-1.2b-instruct for tool execution
3. **Response Generation**: Route based on task requirements

See `agent_kernel.py` for integration details.
