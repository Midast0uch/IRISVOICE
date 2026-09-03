# Lazy Loading Architecture - Developer Documentation

## Overview

The lazy loading architecture prevents automatic model loading on application startup, allowing users to configure cloud-based inference alternatives before consuming GPU RAM.

## Design Principles

### 1. No Automatic Loading

**Principle:** Models are never loaded automatically on startup.

**Implementation:**
- `ModelRouter` initializes with `InferenceMode.UNINITIALIZED`
- No model loading calls in startup sequence
- Backend waits for explicit user selection

**Code Location:** `backend/main.py`

```python
# Startup sequence
async def startup():
    # Initialize ModelRouter without loading models
    model_router = ModelRouter()
    # InferenceMode is UNINITIALIZED by default
    
    # Initialize other services
    agent_kernel = AgentKernel(model_router)
    iris_gateway = IRISGateway(...)
    
    # Backend is ready, but no models loaded
    logger.info("Backend ready - no models loaded")
```

### 2. User-Initiated Loading

**Principle:** Models load only when user explicitly selects "Local Models" mode.

**Implementation:**
- User selects inference mode through UI
- UI sends `update_field` message with `inference_mode` value
- Backend calls `ModelRouter.set_inference_mode()`
- Models load only if mode is "local"

**Code Location:** `backend/iris_gateway.py`

```python
async def _handle_settings(self, session_id: str, client_id: str, message: dict):
    field_id = message["payload"]["field_id"]
    value = message["payload"]["value"]
    
    if field_id == "inference_mode":
        # User selected inference mode
        await self._handle_inference_mode_change(session_id, value)
```

### 3. Explicit Unloading

**Principle:** Models unload when switching from Local to VPS/OpenAI modes.

**Implementation:**
- Mode transition triggers unload
- GPU memory is freed
- Logs memory usage before/after

**Code Location:** `backend/agent/model_router.py`

```python
async def set_inference_mode(self, mode: InferenceMode, config: Dict[str, Any]) -> bool:
    # Unload local models if switching away from local mode
    if self._inference_mode == InferenceMode.LOCAL and mode != InferenceMode.LOCAL:
        await self.unload_local_models()
    
    # Load local models if switching to local mode
    if mode == InferenceMode.LOCAL:
        success = await self.load_local_models()
        if not success:
            return False
    
    self._inference_mode = mode
    return True
```

## Component Architecture

### ModelRouter

**Responsibility:** Route inference requests to appropriate backend.

**State Machine:**
```
UNINITIALIZED → LOCAL (load models)
UNINITIALIZED → VPS (configure gateway)
UNINITIALIZED → OPENAI (configure client)
LOCAL → VPS/OPENAI (unload models)
VPS/OPENAI → LOCAL (load models)
VPS ↔ OPENAI (reconfigure)
```

**Key Methods:**

```python
class ModelRouter:
    async def set_inference_mode(self, mode: InferenceMode, config: Dict[str, Any]) -> bool:
        """Set inference mode and configure backend."""
        
    async def load_local_models(self) -> bool:
        """Load local models into GPU RAM."""
        
    async def unload_local_models(self) -> bool:
        """Unload local models from GPU RAM."""
        
    async def route_inference(self, prompt: str, context: Dict[str, Any]) -> str:
        """Route inference request to appropriate backend."""
        
    def get_status(self) -> Dict[str, Any]:
        """Get current inference mode and status."""
```

### LocalModelManager

**Responsibility:** Manage local model loading/unloading.

**Key Features:**
- GPU memory tracking
- Model lifecycle management
- Error handling and recovery
- Memory usage logging

**Code Location:** `backend/agent/local_model_manager.py`

```python
class LocalModelManager:
    async def load_models(self) -> bool:
        """Load models into GPU RAM."""
        # Log memory before loading
        gpu_memory_before = self._get_gpu_memory()
        
        try:
            # Load models
            self._conversation_model = await self._load_model("lfm2-8b")
            self._tool_model = await self._load_model("lfm2.5-1.2b-instruct")
            
            # Log memory after loading
            gpu_memory_after = self._get_gpu_memory()
            logger.info(f"Models loaded: {gpu_memory_after - gpu_memory_before} MB used")
            
            return True
        except Exception as e:
            logger.error(f"Failed to load models: {e}")
            return False
    
    async def unload_models(self) -> bool:
        """Unload models from GPU RAM."""
        # Free GPU memory
        del self._conversation_model
        del self._tool_model
        torch.cuda.empty_cache()
        
        logger.info("Models unloaded from GPU RAM")
        return True
```

## Memory Management

### GPU Memory Tracking

**Before Loading:**
```python
import torch

def get_gpu_memory_usage():
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3  # GB
        reserved = torch.cuda.memory_reserved() / 1024**3    # GB
        return {"allocated": allocated, "reserved": reserved}
    return None
```

**After Loading:**
```python
memory_before = get_gpu_memory_usage()
await load_models()
memory_after = get_gpu_memory_usage()

memory_used = memory_after["allocated"] - memory_before["allocated"]
logger.info(f"Models loaded: {memory_used:.2f} GB GPU RAM used")
```

### Memory Cleanup

**Unloading Process:**
1. Delete model references
2. Clear CUDA cache
3. Force garbage collection
4. Verify memory freed

```python
async def unload_models(self):
    # Delete model references
    del self._conversation_model
    del self._tool_model
    
    # Clear CUDA cache
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    # Force garbage collection
    import gc
    gc.collect()
    
    # Verify memory freed
    memory_after = get_gpu_memory_usage()
    logger.info(f"GPU memory after unload: {memory_after['allocated']:.2f} GB")
```

## Configuration Persistence

### Saving Inference Mode

**Location:** `backend/state_manager.py`

```python
class StateManager:
    async def update_field(self, session_id: str, subnode_id: str, field_id: str, value: Any):
        if field_id == "inference_mode":
            # Save inference mode to session state
            state = await self.get_state(session_id)
            state.inference_mode = InferenceMode(value)
            await self._persist_state(session_id, state)
```

### Restoring on Startup

**Location:** `backend/main.py`

```python
async def restore_session(session_id: str):
    # Load session state
    state = await state_manager.get_state(session_id)
    
    # Restore inference mode if configured
    if state.inference_mode != InferenceMode.UNINITIALIZED:
        await model_router.set_inference_mode(
            state.inference_mode,
            state.inference_config
        )
```

## Error Handling

### Model Loading Failures

**Scenarios:**
- Insufficient GPU memory
- Model files not found
- CUDA errors
- Corrupted model files

**Handling:**
```python
async def load_local_models(self) -> bool:
    try:
        # Check GPU availability
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available")
        
        # Check available memory
        available_memory = get_available_gpu_memory()
        required_memory = estimate_model_memory()
        
        if available_memory < required_memory:
            raise RuntimeError(f"Insufficient GPU memory: {available_memory} GB available, {required_memory} GB required")
        
        # Load models
        await self._load_models()
        return True
        
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        # Send error to client
        await self._send_error(f"Model loading failed: {str(e)}")
        return False
```

### Mode Transition Failures

**Scenarios:**
- VPS connection fails
- OpenAI API key invalid
- Model unloading fails

**Handling:**
```python
async def set_inference_mode(self, mode: InferenceMode, config: Dict[str, Any]) -> bool:
    try:
        # Validate configuration
        if mode == InferenceMode.VPS:
            if not await self._validate_vps_config(config):
                raise ValueError("Invalid VPS configuration")
        
        # Perform transition
        await self._transition_to_mode(mode, config)
        return True
        
    except Exception as e:
        logger.error(f"Mode transition failed: {e}")
        # Revert to previous mode
        await self._revert_mode()
        return False
```

## Testing

### Unit Tests

**Test No Automatic Loading:**
```python
def test_no_automatic_loading():
    """Verify models are not loaded on startup."""
    model_router = ModelRouter()
    
    # Check inference mode is uninitialized
    assert model_router.get_status()["mode"] == "uninitialized"
    
    # Check no models are loaded
    assert model_router.get_status()["models_loaded"] == 0
```

**Test Mode-Specific Loading:**
```python
async def test_mode_specific_loading():
    """Verify models load only for local mode."""
    model_router = ModelRouter()
    
    # Set VPS mode - no models should load
    await model_router.set_inference_mode(InferenceMode.VPS, vps_config)
    assert model_router.get_status()["models_loaded"] == 0
    
    # Set local mode - models should load
    await model_router.set_inference_mode(InferenceMode.LOCAL, {})
    assert model_router.get_status()["models_loaded"] == 2
```

**Test Model Unloading:**
```python
async def test_model_unloading():
    """Verify models unload when switching modes."""
    model_router = ModelRouter()
    
    # Load models in local mode
    await model_router.set_inference_mode(InferenceMode.LOCAL, {})
    assert model_router.get_status()["models_loaded"] == 2
    
    # Switch to VPS mode - models should unload
    await model_router.set_inference_mode(InferenceMode.VPS, vps_config)
    assert model_router.get_status()["models_loaded"] == 0
```

### Integration Tests

**Test Complete Flow:**
```python
async def test_lazy_loading_flow():
    """Test complete lazy loading flow."""
    # Start backend
    await startup()
    
    # Verify no models loaded
    status = await get_agent_status()
    assert status["models_loaded"] == 0
    
    # User selects local mode
    await send_message({
        "type": "update_field",
        "payload": {
            "field_id": "inference_mode",
            "value": "local"
        }
    })
    
    # Verify models loaded
    status = await get_agent_status()
    assert status["models_loaded"] == 2
    
    # User switches to VPS mode
    await send_message({
        "type": "update_field",
        "payload": {
            "field_id": "inference_mode",
            "value": "vps"
        }
    })
    
    # Verify models unloaded
    status = await get_agent_status()
    assert status["models_loaded"] == 0
```

## Logging

### Startup Logging

```python
logger.info("Backend starting - lazy loading enabled")
logger.info("Inference mode: UNINITIALIZED")
logger.info("No models loaded - waiting for user selection")
```

### Mode Transition Logging

```python
logger.info(f"Inference mode changing: {old_mode} → {new_mode}")

if new_mode == InferenceMode.LOCAL:
    logger.info("Loading local models into GPU RAM...")
    memory_before = get_gpu_memory_usage()
    # Load models
    memory_after = get_gpu_memory_usage()
    logger.info(f"Models loaded: {memory_after - memory_before:.2f} GB used")

if old_mode == InferenceMode.LOCAL:
    logger.info("Unloading local models from GPU RAM...")
    # Unload models
    logger.info("Models unloaded successfully")
```

### Error Logging

```python
logger.error(f"Failed to load models: {error}")
logger.error(f"GPU memory: {get_gpu_memory_usage()}")
logger.error(f"Available VRAM: {get_available_gpu_memory()} GB")
logger.error(f"Required VRAM: {estimate_model_memory()} GB")
```

## Performance Considerations

### Startup Time

**Without Lazy Loading:**
- Startup time: 30-60 seconds (model loading)
- GPU RAM consumed immediately
- User waits before configuration

**With Lazy Loading:**
- Startup time: 2-5 seconds (no model loading)
- GPU RAM free for other applications
- User can configure before loading

### Mode Transition Time

**Local → VPS/OpenAI:**
- Unload time: 2-5 seconds
- GPU RAM freed immediately
- No network delay

**VPS/OpenAI → Local:**
- Load time: 30-60 seconds
- GPU RAM consumed
- User sees loading progress

## Best Practices

1. **Always Log Memory Usage**: Track GPU memory before/after operations
2. **Validate Before Loading**: Check GPU availability and memory
3. **Handle Errors Gracefully**: Provide clear error messages to users
4. **Persist Configuration**: Save inference mode across sessions
5. **Test All Transitions**: Verify all mode transitions work correctly
6. **Monitor Performance**: Track loading times and memory usage

## Troubleshooting

### Models Won't Load

**Check:**
1. GPU availability: `torch.cuda.is_available()`
2. Available VRAM: `nvidia-smi`
3. Model files exist: `ls models/`
4. CUDA version compatibility

### Memory Leaks

**Check:**
1. Models properly deleted
2. CUDA cache cleared
3. Garbage collection running
4. No lingering references

### Slow Loading

**Check:**
1. Model file sizes
2. Disk I/O speed
3. GPU transfer speed
4. Other GPU processes

## Next Steps

- [Model-Agnostic Architecture](./DEVELOPER_MODEL_AGNOSTIC.md)
- [Agent Architecture](./AGENT_ARCHITECTURE.md)
- [Performance Optimization](./OPTIMIZATION_LOG.md)
