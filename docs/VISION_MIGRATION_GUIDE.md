# Vision System Migration Guide

## Overview

The IRIS vision system has been consolidated into a single, efficient service with **4-bit quantization** support. This guide helps you migrate from old implementations to the new unified `VisionService`.

## What's New

### VisionService (New)
- **Location**: `backend/vision/vision_service.py`
- **Features**:
  - 4-bit quantization (60-70% VRAM reduction: 8-12GB → 3-4GB)
  - User-controlled lazy loading
  - Shared model instance across all features
  - Pydantic models for type safety
  - Comprehensive memory profiling

### Deprecated Implementations

| Old Implementation | Status | Replacement |
|-------------------|--------|-------------|
| `MiniCPMClient` | ⚠️ Deprecated | `VisionService` |
| `VisionSystem` | ⚠️ Deprecated | `VisionService` |
| `VisionModelClient` | ⚠️ Deprecated | `VisionService` |
| Direct Ollama calls | ❌ Removed | `VisionService` |

## Migration Steps

### 1. MiniCPMClient → VisionService

**Before:**
```python
from backend.vision import MiniCPMClient

client = MiniCPMClient(endpoint="http://localhost:11434")

# Check availability
if client.check_availability():
    # Analyze image
    result = client.analyze(image_b64, "Describe this")
    
    # Chat with vision
    response = client.chat(
        messages=[{"role": "user", "content": "What's in the image?"}],
        images=[image_b64]
    )
```

**After:**
```python
from backend.vision.vision_service import get_vision_service
import asyncio

vision_service = get_vision_service()

# Enable vision (user-controlled, lazy loading)
await vision_service.enable()

# Analyze image
result = await vision_service.analyze(
    image_b64=image_b64,
    prompt="Describe this"
)

# Chat with vision
response = await vision_service.chat(
    messages=[{"role": "user", "content": "What's in the image?"}],
    images=[image_b64]
)

# Disable when done to free VRAM
await vision_service.disable()
```

### 2. VisionSystem → VisionService

**Before:**
```python
from backend.tools.vision_system import get_vision_system

vision_sys = get_vision_system()
vision_sys.initialize()

# Process with vision
result = vision_sys.process_image(image_data)
```

**After:**
```python
from backend.vision.vision_service import get_vision_service

vision_service = get_vision_service()
await vision_service.enable()

# Process with vision
result = await vision_service.analyze(
    image_b64=image_data,
    prompt="Analyze this image"
)
```

### 3. ScreenMonitor Updates

**Before:**
```python
from backend.vision.screen_monitor import ScreenMonitor

monitor = ScreenMonitor()
monitor.start()  # Would auto-start if MiniCPM available
```

**After:**
```python
from backend.vision.screen_monitor import ScreenMonitor

monitor = ScreenMonitor()
# ScreenMonitor now checks if VisionService is enabled
if monitor.start():
    print("Monitoring started")
else:
    print("Vision service not enabled - user must enable first")
```

### 4. OmniConversationManager

**Before:**
```python
from backend.agent.omni_conversation import get_omni_conversation_manager

omni = get_omni_conversation_manager()
omni.config["vision_enabled"] = True

# Would auto-use vision if available
response = omni.generate_response("What do you see?")
```

**After:**
```python
from backend.agent.omni_conversation import get_omni_conversation_manager
from backend.vision.vision_service import get_vision_service

# User must explicitly enable vision
vision_service = get_vision_service()
await vision_service.enable()

omni = get_omni_conversation_manager()
# Vision only used if user has enabled it
response = omni.generate_response("What do you see?")
```

## Key Differences

### Memory Management
- **Old**: Each client loaded its own model instance
- **New**: Single shared model with reference counting

### User Control
- **Old**: Vision auto-enabled if model detected
- **New**: User must explicitly enable via UI/API

### Error Handling
- **Old**: Silent fallback to text-only
- **New**: Clear error messages, explicit state tracking

### Type Safety
- **Old**: `Dict[str, Any]` everywhere
- **New**: Pydantic models with validation

## API Changes

### WebSocket Messages (New)

```javascript
// Enable vision
{
  "type": "enable_vision",
  "payload": {}
}

// Disable vision
{
  "type": "disable_vision",
  "payload": {}
}

// Get status
{
  "type": "get_vision_status",
  "payload": {}
}
```

### Response Format

```javascript
// Vision status response
{
  "type": "vision_status",
  "payload": {
    "status": "enabled",  // "disabled" | "loading" | "enabled" | "error"
    "vram_usage_mb": 3584,
    "model_name": "minicpm-o4.5",
    "quantization_enabled": true,
    "is_available": true
  }
}
```

## Configuration

### Environment Variables

```bash
# Model settings
VISION_MODEL_PATH=/path/to/minicpm-o4.5
VISION_USE_QUANTIZATION=true

# Optional: Custom model
VISION_MODEL_NAME=custom-model
```

### Programmatic Configuration

```python
from backend.vision.vision_service import VisionService

# Create with custom config
service = VisionService(
    model_path="/custom/path",
    use_quantization=True,
    device="cuda"
)
```

## Troubleshooting

### "Vision service not available"
- Check if user has enabled vision
- Verify model path is correct
- Check GPU memory (need ~4GB with quantization)

### "Failed to load model"
- Verify transformers and bitsandbytes installed
- Check CUDA availability: `torch.cuda.is_available()`
- Try disabling quantization if VRAM limited

### High VRAM usage
- Ensure quantization enabled (default)
- Call `disable()` when vision not needed
- Check for memory leaks with memory profiling tests

## Testing

Run vision system tests:

```bash
# Memory profiling tests
pytest tests/test_vision_memory.py -v

# Type safety tests
pytest tests/test_type_safety.py -v

# Validation tests
pytest tests/test_input_validation.py -v
```

## Rollback Plan

If issues arise, you can temporarily revert to old implementations:

```python
# Set environment variable to use legacy mode
import os
os.environ["VISION_LEGACY_MODE"] = "true"

# This will make get_vision_service() return a compatibility wrapper
from backend.vision.vision_service import get_vision_service
```

## Timeline

- **Now**: Old implementations deprecated but functional
- **v2.1**: Deprecation warnings added
- **v2.2**: Old implementations removed
- **v2.3**: Only VisionService supported

## Support

For migration issues:
1. Check this guide first
2. Run the test suite to verify setup
3. Review the examples in `examples/vision_migration/`
4. Open an issue with the `vision-migration` label
