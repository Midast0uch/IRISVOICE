# Implementation Plan: Vision System Optimization & Critical Fixes

## Phase 1: Vision Service with 4-Bit Quantization

- [ ] 1.1 Create VisionService with Quantization Support
  - What to build: New consolidated vision service with 4-bit quantization
  - Files: `backend/vision/vision_service.py` (new)
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.2, 2.3, 2.4_
  - 
  - Implementation:
  ```python
  from transformers import AutoModel, BitsAndBytesConfig
  import torch
  
  class VisionService:
      def __init__(self):
          self._model = None
          self._tokenizer = None
          self._state = VisionServiceState(status="disabled")
          self._quant_config = BitsAndBytesConfig(
              load_in_4bit=True,
              bnb_4bit_compute_dtype=torch.float16,
              bnb_4bit_use_double_quant=True,
              bnb_4bit_quant_type="nf4"
          )
      
      async def enable(self) -> bool:
          """Load model with quantization on user request"""
          if self._state.status == "enabled":
              return True
          self._state.status = "loading"
          try:
              self._model = AutoModel.from_pretrained(
                  self.model_path,
                  quantization_config=self._quant_config,
                  device_map="auto",
                  trust_remote_code=True
              )
              self._state.status = "enabled"
              return True
          except Exception as e:
              self._state.status = "error"
              self._state.error_message = str(e)
              return False
      
      async def disable(self):
          """Unload model and free VRAM"""
          if self._model:
              del self._model
              torch.cuda.empty_cache()
          self._state = VisionServiceState(status="disabled")
  ```

- [ ] 1.2 Add Frontend Vision Toggle
  - What to build: UI controls for enabling/disabling vision
  - Files: `components/dark-glass-dashboard.tsx`, `hooks/useIRISWebSocket.ts`
  - _Requirements: 2.1, 2.2_
  - 
  - Add toggle field in customize section
  - Add WebSocket message handlers: `enable_vision`, `disable_vision`
  - Show loading state during model load

- [ ] 1.3 Integrate VisionService with Backend
  - What to build: Wire VisionService into iris_gateway.py
  - Files: `backend/iris_gateway.py`
  - _Requirements: 2.3, 2.4_
  - 
  - Handle `enable_vision` message
  - Handle `disable_vision` message
  - Broadcast state changes to all clients

- [ ] 1.4 Update Consumers to Use VisionService
  - What to build: Refactor OmniConversation, ScreenMonitor to use VisionService
  - Files: `backend/agent/omni_conversation.py`, `backend/vision/screen_monitor.py`
  - _Requirements: 2.3, 6.1_
  - 
  - Replace direct MiniCPMClient usage with VisionService
  - Add deprecation warnings to old components

- [ ] 1.5 Memory Profiling Tests
  - What to build: Tests to verify VRAM reduction
  - Run: `python -m pytest tests/vision/test_memory_usage.py -v`
  - _Requirements: 1.2_
  - 
  - Measure VRAM before/after quantization
  - Verify 50-60% reduction target
  - Test load/unload cycles

## Phase 2: Input Validation & Sanitization

- [ ] 2.1 Create Validation Module
  - What to build: Centralized validation with JSON Schema support
  - Files: `backend/mcp/validation.py` (new)
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - 
  - Implementation:
  ```python
  from pydantic import BaseModel, ValidationError
  from typing import Dict, Any
  
  class ToolValidator:
      def __init__(self):
          self._schemas: Dict[str, dict] = {}
      
      def register_tool(self, tool_name: str, schema: dict):
          self._schemas[tool_name] = schema
      
      def validate(self, tool_name: str, params: dict) -> ValidationResult:
          if tool_name not in self._schemas:
              return ValidationResult(False, ["Unknown tool"])
          # JSON Schema validation
          try:
              jsonschema.validate(params, self._schemas[tool_name])
              return ValidationResult(True, [])
          except jsonschema.ValidationError as e:
              return ValidationResult(False, [str(e)])
  ```

- [ ] 2.2 Add Input Sanitization to Agent Kernel
  - What to build: Sanitize user inputs before processing
  - Files: `backend/agent/agent_kernel.py`
  - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - 
  - Add `sanitize_input()` method (remove HTML/script tags)
  - Validate session_id format
  - Implement rate limiting (Redis or in-memory)
  - Truncate inputs > 10,000 characters

- [ ] 2.3 Integrate Validation into Tool Bridge
  - What to build: Call validation before tool execution
  - Files: `backend/agent/tool_bridge.py`
  - _Requirements: 3.1, 3.2_
  - 
  - Add validator instance to ToolBridge
  - Validate params in `execute_mcp_tool()`
  - Return typed error responses
  - Log validation failures

- [ ] 2.4 Write Validation Tests
  - What to build: Unit tests for validation layer
  - Run: `python -m pytest tests/mcp/test_validation.py -v`
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - 
  - Test valid inputs pass
  - Test invalid inputs fail with correct errors
  - Test sanitization (XSS attempts)
  - Test rate limiting

## Phase 3: Type Safety Improvements

- [ ] 3.1 Create Pydantic Models for Tools
  - What to build: Type-safe request/response models
  - Files: `backend/mcp/models.py` (new)
  - _Requirements: 5.1, 5.2_
  - 
  - `ToolRequest`, `ToolResponse` (see design.md)
  - `MCPRequest`, `MCPResponse` updates
  - All tool-specific parameter models

- [ ] 3.2 Update Tool Bridge to Use Typed Models
  - What to build: Replace Dict[str, Any] with Pydantic
  - Files: `backend/agent/tool_bridge.py`
  - _Requirements: 5.1, 5.2_
  - 
  - Update method signatures to use ToolRequest/ToolResponse
  - Remove all `Any` types from public methods
  - Ensure backward compatibility

- [ ] 3.3 Update Agent Kernel with Type Safety
  - What to build: Typed responses and inputs
  - Files: `backend/agent/agent_kernel.py`
  - _Requirements: 5.1, 5.2_
  - 
  - Type `TaskContext` properly
  - Type `process_text_message()` return
  - Remove implicit Any

- [ ] 3.4 Add MyPy to CI
  - What to build: Type checking in CI pipeline
  - Files: `.github/workflows/ci.yml` or equivalent
  - _Requirements: 5.3_
  - 
  - Add `mypy backend/` to CI
  - Configure mypy.ini (strict mode)
  - Fix all existing type errors

- [ ] 3.5 Run Type Checking
  - What to build: Verify no type errors
  - Run: `cd IRISVOICE && mypy backend/ --strict`
  - _Requirements: 5.3, 5.4_
  - 
  - Expected: 0 errors
  - Fix any remaining issues

## Phase 4: Consolidation & Cleanup

- [ ] 4.1 Deprecate Old Vision Components
  - What to build: Add deprecation warnings
  - Files: `backend/vision/minicpm_client.py`, `backend/tools/vision_system.py`, `backend/agent/gui_toolkit.py`
  - _Requirements: 6.1, 6.2, 6.3_
  - 
  - Add deprecation warnings to old classes
  - Point users to VisionService
  - Maintain backward compatibility for 2 releases

- [ ] 4.2 Update Documentation
  - What to build: Document new architecture
  - Files: `backend/vision/README.md` (new)
  - _Requirements: 6.1_
  - 
  - Migration guide from old to new
  - Memory usage comparisons
  - Configuration options

- [ ] 4.3 Final Integration Testing
  - What to build: End-to-end testing
  - Run: `python -m pytest tests/integration/test_vision_system.py -v`
  - _Requirements: 1.1, 2.3, 3.1, 5.1_
  - 
  - Test full flow: UI → Backend → VisionService → Response
  - Test error handling
  - Test memory cleanup on disable

---

## Summary

### Requirements Coverage

| Requirement | Tasks |
|-------------|-------|
| 1.1 4-bit quantization | 1.1 |
| 1.2 VRAM reduction | 1.1, 1.5 |
| 1.3 Fallback | 1.1 |
| 1.4 Speed acceptable | 1.5 |
| 2.1 Vision toggle | 1.2 |
| 2.2 No auto-load | 1.1 |
| 2.3 Lazy loading | 1.1, 1.3 |
| 2.4 Unload on disable | 1.1, 1.3 |
| 2.5 Progress display | 1.2 |
| 3.1 Schema validation | 2.1, 2.3 |
| 3.2 Typed errors | 2.1, 2.3, 3.1 |
| 3.3 Sanitize inputs | 2.2 |
| 3.4 Log failures | 2.1 |
| 4.1 HTML sanitization | 2.2 |
| 4.2 Session validation | 2.2 |
| 4.3 Rate limiting | 2.2 |
| 4.4 Truncate long | 2.2 |
| 5.1 Pydantic params | 3.1, 3.2 |
| 5.2 Typed returns | 3.1, 3.2, 3.3 |
| 5.3 MyPy CI | 3.4 |
| 5.4 No Any | 3.2, 3.3, 3.5 |
| 6.1 Consolidate | 1.1, 1.4, 4.1 |
| 6.2 Backward compat | 4.1 |
| 6.3 Deprecation warnings | 4.1 |
| 6.4 Remove deprecated | 4.1 (after 2 releases) |

### Total Tasks: 16

### Estimated Timeline: 4 weeks
- Week 1: Phase 1 (Vision Service)
- Week 2: Phase 2 (Validation)
- Week 3: Phase 3 (Type Safety)
- Week 4: Phase 4 (Cleanup + Testing)
