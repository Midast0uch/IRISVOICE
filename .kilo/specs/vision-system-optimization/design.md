# Design: Vision System Optimization & Critical Fixes

## Overview

This design addresses memory optimization for the vision system through 4-bit quantization and user-controlled loading, while also fixing critical type safety and validation issues in the Agent Kernel and Tool Bridge.

## Architecture

### Vision Service Architecture (New)

```
┌─────────────────────────────────────────────────────────────┐
│                    VisionService (New)                       │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ ModelLoader  │  │  Quantizer   │  │  StateMgr    │       │
│  │  (lazy)      │  │  (4-bit)     │  │(enable/disable)│      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         └─────────────────┴─────────────────┘                │
│                           │                                  │
│                    ┌──────▼──────┐                          │
│                    │ MiniCPM Model│                          │
│                    │  (3-4 GB)   │                          │
│                    └─────────────┘                          │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│              Consumers (Refactored)                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐    │
│  │ ToolBridge  │ │ OmniConversation│ │ ScreenMonitor    │    │
│  └─────────────┘ └─────────────┘ └─────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 4-Bit Quantization Implementation

**Using BitsAndBytesConfig:**
```python
from transformers import AutoModel, BitsAndBytesConfig

quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,  # Nested quantization for extra memory savings
    bnb_4bit_quant_type="nf4"  # Normalized float 4 (better for weights)
)

model = AutoModel.from_pretrained(
    model_path,
    quantization_config=quant_config,
    device_map="auto",  # Automatically distribute across available GPUs/CPU
    trust_remote_code=True
)
```

**Expected Memory Reduction:**
- Original (FP16): ~8-12 GB VRAM
- 4-bit Quantized: ~3-4 GB VRAM
- CPU Offloading: Can reduce to ~2 GB VRAM (slower)

### User-Controlled Loading Flow

```
User Action → WebSocket → iris_gateway.py → VisionService
                                              │
                   ┌──────────────────────────┘
                   ▼
            ┌──────────────┐
            │ State Check  │
            └──────┬───────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   ┌────────┐ ┌────────┐ ┌────────┐
   │ DISABLED│ │ LOADING│ │ ENABLED│
   │ (0 GB)  │ │ (busy) │ │ (3-4GB)│
   └────────┘ └────────┘ └────────┘
```

**State Management:**
- `disabled`: Model not loaded, minimal memory usage
- `loading`: User triggered load, show progress indicator
- `enabled`: Model loaded and ready for inference
- `error`: Loading failed, show error message

### Validation Layer Architecture

```
┌────────────────────────────────────────────────────────────┐
│                  Validation Pipeline                        │
├────────────────────────────────────────────────────────────┤
│  Input → Sanitizer → Schema Validator → Type Converter →    │
│         (HTML/JS)   (JSON Schema)      (Pydantic)          │
│                                                              │
│  Error Handling:                                            │
│  - ValidationError → Typed error response                   │
│  - SanitizationWarning → Log and continue                   │
│  - RateLimitError → 429 Too Many Requests                   │
└────────────────────────────────────────────────────────────┘
```

## Data Models

### VisionServiceState (Pydantic)
```python
class VisionServiceState(BaseModel):
    status: Literal["disabled", "loading", "enabled", "error"]
    vram_usage_mb: Optional[int] = None
    load_progress_percent: Optional[int] = None
    error_message: Optional[str] = None
    last_used: Optional[datetime] = None
```

### ToolRequest (Pydantic)
```python
class ToolRequest(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=100)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    timestamp: datetime = Field(default_factory=datetime.now)
    
    @validator('parameters')
    def validate_params(cls, v, values):
        # Schema validation based on tool_name
        return v
```

### ToolResponse (Typed)
```python
class ToolSuccessResponse(BaseModel):
    success: Literal[True] = True
    result: Any
    execution_time_ms: int
    tool_name: str

class ToolErrorResponse(BaseModel):
    success: Literal[False] = False
    error_code: str
    error_message: str
    suggestion: Optional[str] = None

ToolResponse = Union[ToolSuccessResponse, ToolErrorResponse]
```

## Files to Modify

| File | Changes |
|------|---------|
| `backend/vision/vision_service.py` | New consolidated service |
| `backend/vision/minicpm_client.py` | Add 4-bit quantization |
| `hooks/useIRISWebSocket.ts` | Add vision toggle actions |
| `components/dark-glass-dashboard.tsx` | Add vision enable/disable UI |
| `backend/agent/tool_bridge.py` | Add validation layer |
| `backend/agent/agent_kernel.py` | Add input sanitization |
| `backend/mcp/validation.py` | New validation module |

## Key Design Decisions

### Decision 1: BitsAndBytes for Quantization
**Choice:** Use `transformers.BitsAndBytesConfig` with 4-bit NF4 quantization
**Rationale:**
- Standard HuggingFace approach
- Minimal code changes required
- Well-tested in production
**Alternative considered:** GPTQ (more complex, requires calibration)

### Decision 2: Pydantic for Type Safety
**Choice:** Replace Dict[str, Any] with Pydantic models
**Rationale:**
- Runtime validation
- JSON Schema generation
- IDE autocomplete support
**Alternative considered:** dataclasses (no validation)

### Decision 3: State Machine for Vision Service
**Choice:** Explicit state machine (disabled/loading/enabled/error)
**Rationale:**
- Clear user feedback
- Prevents race conditions
- Enables proper cleanup
**Alternative considered:** Boolean flag (insufficient for loading state)

## Migration Strategy

### Phase 1: Vision Service (Week 1)
1. Create VisionService with 4-bit quantization
2. Add user toggle in UI
3. Test memory usage

### Phase 2: Validation Layer (Week 2)
1. Create validation module
2. Add schema definitions for all tools
3. Update ToolBridge to use validation

### Phase 3: Type Safety (Week 3)
1. Create Pydantic models for all tool interfaces
2. Update Agent Kernel to use typed responses
3. Add mypy to CI

### Phase 4: Cleanup (Week 4)
1. Deprecate old vision components
2. Add deprecation warnings
3. Update documentation

## Testing Strategy

1. **Memory Profiling:** Measure VRAM before/after quantization
2. **Load Testing:** Test rapid enable/disable cycles
3. **Validation Testing:** Test invalid inputs are rejected
4. **Type Checking:** Run mypy on entire backend

## Security Considerations

1. **Input Sanitization:** Remove HTML/script tags from user input
2. **Rate Limiting:** Prevent DoS via rapid tool calls
3. **Schema Validation:** Prevent injection attacks via malformed parameters
4. **Session Validation:** Ensure session_id is properly formatted
