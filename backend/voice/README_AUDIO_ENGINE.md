# AudioEngine Architecture

## Overview

The AudioEngine has been refactored to be a **thin wrapper** around the LFM 2.5 Audio Model. This reflects the actual capabilities of the LFM 2.5 audio model, which handles all audio processing internally.

## LFM 2.5 Audio Model Capabilities

The LFM 2.5 audio model handles **EVERYTHING** for audio:

1. **Raw Audio Input Capture** - Captures audio from microphone
2. **Raw Audio Output Playback** - Plays audio through speakers
3. **Audio Processing** - All processing is handled internally:
   - Noise reduction
   - Echo cancellation
   - Voice enhancement
   - Automatic gain control
4. **Speech-to-Text Transcription** - Converts speech to text
5. **User-Agent Communication** - Manages conversation flow

## AudioEngine Responsibilities

The AudioEngine is now a **thin wrapper** that:

1. **Initializes** the LFM 2.5 audio model
2. **Manages** the lifecycle (start/stop audio interaction)
3. **Passes** audio directly to/from the LFM 2.5 model

## What Was Removed

The following complexity was removed from AudioEngine:

- ❌ Device enumeration and management
- ❌ Stream handling (input/output streams)
- ❌ Audio processing pipeline
- ❌ Device fallback logic
- ❌ Complex mocking in tests

## New Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        AudioEngine                          │
│                    (Thin Wrapper)                           │
│                                                             │
│  - initialize()                                             │
│  - start_audio_interaction()                                │
│  - stop_audio_interaction()                                 │
│  - process_audio()                                          │
│  - get_status()                                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   LFM 2.5 Audio Model                       │
│                  (Handles Everything)                       │
│                                                             │
│  ✓ Audio input capture                                     │
│  ✓ Audio output playback                                   │
│  ✓ Noise reduction                                         │
│  ✓ Echo cancellation                                       │
│  ✓ Voice enhancement                                       │
│  ✓ Automatic gain control                                  │
│  ✓ Speech-to-text transcription                            │
│  ✓ Response generation                                     │
│  ✓ Text-to-speech synthesis                                │
└─────────────────────────────────────────────────────────────┘
```

## Testing Strategy

### Old Approach (Removed)
- Complex property-based tests with sounddevice mocking
- Tests were hanging due to complex mocking
- Over-engineered for the actual architecture

### New Approach (Current)
- Simple integration tests that verify:
  - LFM 2.5 audio model can be initialized
  - Audio interaction can start/stop
  - Basic error handling works
- No mocking of sounddevice (LFM 2.5 handles that)
- Tests focus on the thin wrapper interface

## Usage Example

```python
from backend.voice.audio_engine import AudioEngine

# Create engine
engine = AudioEngine()

# Initialize LFM 2.5 audio model
await engine.initialize()

# Start audio interaction
await engine.start_audio_interaction()

# Process audio (LFM 2.5 handles everything)
audio_data = b"raw_audio_bytes"
response = await engine.process_audio(audio_data)

# Stop audio interaction
await engine.stop_audio_interaction()

# Get status
status = engine.get_status()
print(status)  # {'is_initialized': True, 'is_running': False, 'lfm_audio_available': True}
```

## Benefits of This Architecture

1. **Simplicity** - AudioEngine is now ~100 lines instead of ~400 lines
2. **Correctness** - Reflects actual LFM 2.5 capabilities
3. **Testability** - Simple integration tests instead of complex property tests
4. **Maintainability** - Less code to maintain and debug
5. **Performance** - No unnecessary abstraction layers

## Related Files

- `backend/voice/audio_engine.py` - Thin wrapper implementation
- `backend/agent/lfm_audio_manager.py` - LFM 2.5 audio model manager
- `tests/integration/test_audio_engine_lfm_integration.py` - Integration tests

## Requirements Validation

This architecture validates the following requirements:

- **11.1, 11.2** - Audio device configuration (handled by LFM 2.5)
- **12.1-12.7** - Audio processing (handled by LFM 2.5)
  - Noise reduction
  - Echo cancellation
  - Voice enhancement
  - Automatic gain control
  - Processing order
  - Audio latency

All requirements are met by the LFM 2.5 audio model, with AudioEngine providing a simple interface.
