# Phase 1: Core Foundation Implementation Plan

**Objective:** Implement LFM 2.5 Audio voice processing engine and voice pipeline (Porcupine + Silero VAD)

**Timeline:** 1-2 weeks
**Priority:** P0 (Critical)

---

## 1. LFM 2.5 Audio Integration

### 1.1 Dependencies & Setup
```python
# requirements.txt additions
llama-cpp-python>=0.2.0
pyaudio>=0.2.11
porcupine>=2.0.0
silero-vad>=4.0.0
numpy>=1.24.0
```

### 1.2 Model Management
- [ ] Model download utility (from HuggingFace or custom URL)
- [ ] GGUF Q4_0 quantization support
- [ ] Model path configuration
- [ ] Model validation and checksums

### 1.3 Audio Engine Architecture
```
AudioEngine (singleton)
├── ModelManager
│   ├── download_model()
│   ├── load_model()
│   └── unload_model()
├── InferenceEngine
│   ├── conversation_mode(audio_in) -> audio_out
│   ├── tool_mode(audio_in) -> text -> tool_result -> audio_out
│   └── switch_mode(mode)
└── AudioPipeline
    ├── input_stream (PyAudio)
    ├── output_stream (PyAudio)
    └── buffer_management
```

### 1.4 WebSocket Integration
- [ ] `/ws/voice` endpoint for audio streaming
- [ ] Voice state broadcasting (idle/listening/processing/speaking/error)
- [ ] Real-time transcript streaming
- [ ] Audio playback coordination

---

## 2. Voice Pipeline (Wake Word + VAD)

### 2.1 Porcupine Wake Word
- [ ] Wake phrase configuration (default: "Hey IRIS")
- [ ] Sensitivity tuning (0-1 scale)
- [ ] Audio preprocessing for wake detection
- [ ] ~50ms detection latency target

### 2.2 Silero VAD
- [ ] Voice activity detection
- [ ] Speech start/end detection
- [ ] Audio buffering during speech
- [ ] Silence timeout handling

### 2.3 Pipeline Flow
```
Audio Input
    ↓
Porcupine (Wake Word Detection)
    ↓ (Wake detected)
Silero VAD (Speech Detection)
    ↓ (Speech start)
Audio Buffering
    ↓ (Speech end)
LFM 2.5 Audio Inference
    ↓
Audio Output (TTS or LFM direct)
```

---

## 3. VOICE Node Backend Implementation

### 3.1 INPUT Sub-node
- [ ] `input_device`: List available microphones, switch device
- [ ] `input_sensitivity`: Gain control (0-100%)
- [ ] `noise_gate`: Toggle + threshold configuration
- [ ] `vad`: VAD enable/disable
- [ ] `input_test`: Microphone test with visual feedback

### 3.2 OUTPUT Sub-node
- [ ] `output_device`: List available speakers/headphones
- [ ] `master_volume`: Volume control (0-100%)
- [ ] `output_test`: Audio test tone
- [ ] `latency_compensation`: Delay adjustment (0-500ms)

### 3.3 PROCESSING Sub-node
- [ ] `noise_reduction`: AI noise suppression toggle
- [ ] `echo_cancellation`: Echo removal toggle
- [ ] `voice_enhancement`: Clarity boost toggle
- [ ] `automatic_gain`: AGC toggle

### 3.4 MODEL Sub-node
- [ ] `endpoint`: LFM 2.5 Audio endpoint URL/path
- [ ] `connection_test`: Test connection to model
- [ ] `temperature`: Creativity control (0-2.0)
- [ ] `max_tokens`: Response length (256-8192)
- [ ] `context_window`: Memory size (1024-32768)

---

## 4. AGENT Node Backend Implementation

### 4.1 IDENTITY Sub-node
- [ ] `assistant_name`: Custom name persistence
- [ ] `personality`: Personality engine selection
- [ ] `knowledge`: Knowledge focus area
- [ ] `response_length`: Length preference

### 4.2 WAKE Sub-node
- [ ] `wake_phrase`: Custom wake word configuration
- [ ] `detection_sensitivity`: Porcupine sensitivity
- [ ] `activation_sound`: Sound playback on wake
- [ ] `sleep_timeout`: Auto-sleep timer

### 4.3 SPEECH Sub-node
- [ ] `tts_voice`: Voice selection (Nova/Alloy/Echo/Fable/Onyx/Shimmer)
- [ ] `speaking_rate`: Speed control (0.5-2.0x)
- [ ] `pitch_adjustment`: Pitch shift (-20 to +20)
- [ ] `pause_duration`: Pause between sentences
- [ ] `voice_cloning`: Audio sample upload/path

### 4.4 MEMORY Sub-node
- [ ] `context_visualization`: Context window display
- [ ] `token_count`: Real-time token usage
- [ ] `conversation_history`: History storage/retrieval
- [ ] `clear_memory`: Clear conversation button
- [ ] `export_memory`: Export to file

---

## 5. Implementation Steps

### Week 1

**Day 1-2: LFM 2.5 Audio Setup**
1. Add dependencies to requirements.txt
2. Create `backend/audio/` module structure
3. Implement ModelManager for download/loading
4. Create AudioEngine singleton

**Day 3-4: Voice Pipeline**
1. Integrate Porcupine wake word detection
2. Integrate Silero VAD
3. Create AudioPipeline class
4. Connect pipeline to WebSocket

**Day 5-7: VOICE Node Backend**
1. Implement INPUT device management
2. Implement OUTPUT device/volume control
3. Add PROCESSING toggles
4. Create MODEL configuration endpoints

### Week 2

**Day 8-10: AGENT Node Backend**
1. Implement IDENTITY persistence
2. Connect WAKE configuration to Porcupine
3. Create SPEECH/TTS integration
4. Build MEMORY storage system

**Day 11-12: Integration & Testing**
1. End-to-end voice command test
2. State persistence verification
3. WebSocket sync testing
4. Performance optimization (<500ms target)

**Day 13-14: Documentation & Polish**
1. API documentation
2. Configuration examples
3. Error handling improvements
4. Logging implementation

---

## 6. Success Criteria

- [ ] LFM 2.5 Audio loads and responds to voice input
- [ ] Wake word detection <50ms latency
- [ ] Full voice response <500ms (end-to-end)
- [ ] All VOICE node fields functional
- [ ] All AGENT node fields functional
- [ ] State persists across restarts
- [ ] WebSocket broadcasts voice states correctly

---

## 7. Files to Create/Modify

### New Files
```
backend/audio/
├── __init__.py
├── engine.py          # AudioEngine singleton
├── model_manager.py   # LFM model management
├── pipeline.py        # Audio pipeline (input/output)
├── inference.py       # LFM inference logic
├── wake_word.py       # Porcupine integration
├── vad.py             # Silero VAD integration
└── config.py          # Audio configuration

backend/voice/
├── __init__.py
├── state_manager.py   # Voice state tracking
├── device_manager.py  # Audio I/O device management
└── processor.py       # Audio processing (noise/echo/AGC)
```

### Modified Files
```
backend/main.py        # Add /ws/voice endpoint
backend/models.py      # Add VoiceState enum, AudioConfig model
backend/state_manager.py # Add voice state persistence
requirements.txt       # Add audio dependencies
```

---

## 8. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| LFM 2.5 Audio model too large | Implement lazy loading, optional download |
| Porcupine license limitations | Provide alternative wake word options |
| Audio device compatibility | Test on Windows/macOS/Linux, fallback options |
| Latency >500ms | Profile code, optimize inference batching |
| Memory usage high | Implement model quantization, unload when idle |

---

Ready to proceed with implementation?
