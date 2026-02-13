# 🧠 IRIS Vision Integration Plan — MiniCPM-o 4.5

## Executive Summary

Integrate **MiniCPM-o 4.5** (9B param multimodal model) into IRISVOICE to create a
unified **see → hear → think → speak → act** experience. The model natively handles
vision, speech, and text in one end-to-end architecture — replacing the current
fragmented pipeline (separate STT → LLM → TTS) with a single omni-model.

---

## 🏗️ Current Architecture

```
┌──────────────────────────────────────────────────────────┐
│  IRIS Current Pipeline                                   │
│                                                          │
│  Mic → WakeWord → VAD → STT (Whisper) → LM Studio LLM   │
│                                           ↓              │
│                                     TTS (OpenAI/pyttsx3) │
│                                           ↓              │
│                                      Speaker Output      │
│                                                          │
│  GUI Automation: pyautogui + mss screenshots             │
│  Vision (stub): Anthropic Claude → JSON coords           │
│  GUI Agent:     vision + operator instruction loop       │
└──────────────────────────────────────────────────────────┘
```

### Key Files
| Module | File | Purpose |
|--------|------|---------|
| Audio Engine | `backend/audio/engine.py` | Singleton orchestrator: wake→VAD→STT→LLM→TTS→play |
| Audio Pipeline | `backend/audio/pipeline.py` | PyAudio I/O streaming |
| STT Model | `backend/audio/model_manager.py` | LFM 2.5 Audio (Whisper fallback) |
| Conversation | `backend/agent/conversation.py` | LM Studio chat completions |
| TTS | `backend/agent/tts.py` | OpenAI TTS / pyttsx3 / LiquidAI |
| Vision | `backend/automation/vision.py` | Anthropic Claude vision (stub) |
| GUI Operator | `backend/automation/operator.py` | pyautogui + mss screenshots |
| GUI Agent | `backend/automation/vision.py` | Multi-step instruction executor |

---

## 🎯 Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  IRIS Unified Omni Pipeline (MiniCPM-o 4.5)                        │
│                                                                     │
│  ┌─────────┐   ┌──────────────────────────────────────────────────┐ │
│  │ Mic     │──→│                                                  │ │
│  │ (audio) │   │                                                  │ │
│  └─────────┘   │        MiniCPM-o 4.5  (Ollama)                  │ │
│                │        ─────────────────────────                  │ │
│  ┌─────────┐   │  Accepts: images, audio, video, text             │ │
│  │ Screen  │──→│  Returns: text + audio (TTS) responses           │ │
│  │ (mss)   │   │                                                  │ │
│  └─────────┘   │  Modes:                                          │ │
│                │    • Visual Understanding (screenshots)           │ │
│  ┌─────────┐   │    • Simplex Omni (audio + vision → text/audio)  │ │
│  │ Webcam  │──→│    • Realtime Speech Conversation                │ │
│  │ (opt.)  │   │    • GUI Agent (screenshot → action plan)        │ │
│  └─────────┘   └─────────────┬────────────────────────────────────┘ │
│                              │                                      │
│                              ↓                                      │
│                 ┌────────────────────────┐                          │
│                 │  Response Router       │                          │
│                 │  ─────────────         │                          │
│                 │  • Text → UI display   │                          │
│                 │  • Audio → Speaker     │                          │
│                 │  • Actions → Operator  │                          │
│                 └────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Deployment Strategy: Ollama (Recommended for Local)

### Why Ollama?
1. **Native Windows support** — single binary installer
2. **GGUF quantization** — MiniCPM-o 4.5 Q4_K_M fits in ~6GB VRAM
3. **OpenAI-compatible API** — drop-in replacement for LM Studio
4. **Image input support** — base64 images in API calls
5. **No Python GPU dependencies** — no CUDA toolkit, no torch conflicts

### Hardware Requirements
| Quantization | VRAM | Quality | Speed |
|-------------|------|---------|-------|
| Q4_K_M | ~6 GB | Good | Fast |
| Q5_K_M | ~7 GB | Better | Good |
| Q6_K | ~8 GB | Great | Moderate |
| Q8_0 | ~10 GB | Best quantized | Slower |

### Installation Steps
```powershell
# 1. Install Ollama (if not already)
winget install Ollama.Ollama

# 2. Pull MiniCPM-o 4.5 (vision-language model via GGUF)
ollama pull openbmb/minicpm-o4.5
# OR for custom quantization:
# Download from https://huggingface.co/openbmb/MiniCPM-o-4_5-gguf
# Create Modelfile and: ollama create minicpm-o4.5 -f Modelfile

# 3. Verify it works
ollama run openbmb/minicpm-o4.5 "Hello, describe what you can do"
```

---

## 🔧 Implementation Phases

### Phase 1: Vision Provider — MiniCPM-o via Ollama API
**Files:** `backend/automation/vision.py`, `backend/automation/__init__.py`

Replace the Anthropic Claude stub with a local MiniCPM-o provider that sends
screenshots as base64 images to Ollama's `/api/generate` endpoint.

```python
# New VisionProvider member
class VisionProvider(Enum):
    ANTHROPIC = "anthropic"
    VOLCENGINE = "volcengine"
    LOCAL = "local"
    MINICPM_OLLAMA = "minicpm_ollama"  # NEW

# Key method signature
async def _detect_with_minicpm(self, screenshot_base64: str, description: str):
    """Use MiniCPM-o 4.5 via Ollama for vision understanding"""
    response = requests.post("http://localhost:11434/api/generate", json={
        "model": "minicpm-o4.5",
        "prompt": f"Find the UI element: '{description}'. Return JSON with x,y,width,height...",
        "images": [screenshot_base64],
        "stream": False
    })
```

### Phase 2: Unified Conversation Manager with Vision Context
**File:** NEW `backend/agent/omni_conversation.py`

A new conversation manager that can include visual context (screenshots) alongside
text prompts. This gives IRIS "eyes" during normal conversation.

```python
class OmniConversationManager:
    """Multimodal conversation via Ollama with MiniCPM-o 4.5"""

    def generate_response(self, user_text: str, screenshot_b64: str = None):
        """Generate response with optional visual context"""
        payload = {
            "model": "minicpm-o4.5",
            "prompt": user_text,
            "stream": False,
        }
        if screenshot_b64:
            payload["images"] = [screenshot_b64]

        response = requests.post(
            f"{self.endpoint}/api/generate",
            json=payload, timeout=60
        )
        return response.json()["response"]
```

### Phase 3: Screen-Aware Audio Engine
**File:** `backend/audio/engine.py` (modify `_run_inference`)

Enhance the inference pipeline so that when the user speaks, IRIS also captures
a screenshot and sends both audio transcript + screenshot to MiniCPM-o.

**Before:**
```
User speaks → STT → text → LM Studio → response text → TTS → speak
```

**After:**
```
User speaks → STT → text ──┐
                           ├──→ MiniCPM-o (text + image) → response → TTS → speak
Screen capture → base64 ───┘
```

### Phase 4: Enhanced GUI Agent with Local Vision
**File:** `backend/automation/vision.py` (modify `GUIAgent`)

Replace the cloud-dependent GUI agent with fully local MiniCPM-o vision:
- Take screenshot → send to MiniCPM-o → get structured action plan
- Execute actions via `NativeGUIOperator`
- Loop until task complete

### Phase 5: Real-time Screen Monitoring (Proactive Mode)
**File:** NEW `backend/vision/screen_monitor.py`

Periodic screenshot analysis for proactive assistance:
- Configurable interval (e.g., every 5 seconds when active)
- Detect context changes (new window, error dialog, etc.)
- Proactively offer help based on what IRIS "sees"

---

## 📁 New File Structure

```
backend/
├── vision/                          # NEW module
│   ├── __init__.py
│   ├── minicpm_client.py           # Core Ollama + MiniCPM-o client
│   ├── screen_capture.py           # Screenshot utilities (from mss)
│   ├── screen_monitor.py           # Proactive screen monitoring
│   └── context_analyzer.py         # Scene understanding & change detection
├── agent/
│   ├── omni_conversation.py        # NEW: vision-aware conversation
│   └── (existing files unchanged)
├── automation/
│   ├── vision.py                   # MODIFIED: add MiniCPM provider
│   └── (existing files unchanged)
└── audio/
    └── engine.py                   # MODIFIED: screenshot during inference
```

---

## 🔌 New Dependencies

Add to `requirements.txt`:
```
# Vision / MiniCPM-o Integration
Pillow>=10.0.0          # Image processing (already used in operator.py)
mss>=9.0.0              # Screen capture (already used in operator.py)
requests>=2.31.0        # HTTP client for Ollama API (already in deps)
```

> **No new heavy dependencies needed!** Ollama handles model loading externally.
> The integration is purely HTTP API-based, keeping the Python backend lightweight.

---

## 🧪 Implementation Order & Priority

| # | Phase | Priority | Effort | Impact |
|---|-------|----------|--------|--------|
| 1 | MiniCPM-o Ollama Client | 🔴 Critical | 2 hrs | Foundation for everything |
| 2 | Vision-aware conversation | 🔴 Critical | 3 hrs | "IRIS can see" |
| 3 | Screen-aware audio engine | 🟡 High | 2 hrs | "Ask about what's on screen" |
| 4 | Local GUI agent | 🟡 High | 3 hrs | Replace cloud vision with local |
| 5 | Proactive monitoring | 🟢 Nice-to-have | 4 hrs | "Hey, I noticed..." |

---

## 🔀 Integration Points with Existing Code

### 1. `AudioEngine._run_inference()` (engine.py:278-432)
**Change:** Before calling conversation manager, capture screenshot and pass as
context to the new `OmniConversationManager`.

### 2. `VisionModelClient` (vision.py:31-178)
**Change:** Add `MINICPM_OLLAMA` provider with local Ollama API calls.

### 3. `GUIAgent.execute_instruction()` (vision.py:190-239)
**Change:** Use local MiniCPM-o instead of Anthropic for screen analysis.

### 4. `AIConversationManager` (conversation.py)
**Change:** Can stay as fallback. New `OmniConversationManager` takes priority
when MiniCPM-o is available, gracefully falling back to LM Studio text-only.

### 5. Frontend: New subnode configuration
**Change:** Add "Vision" settings under the AUTOMATE category hexagonal node:
- Toggle: "Screen awareness" (on/off)
- Dropdown: "Vision model" (MiniCPM-o / Claude / Disabled)
- Slider: "Screen capture interval" (1-30 seconds)
- Toggle: "Proactive mode" (on/off)

---

## 🎭 Immersive Experience Features

### "See & Describe" Mode
User says: *"What am I looking at?"*
→ IRIS captures screen → MiniCPM-o analyzes → speaks description

### "Help Me With This" Mode
User says: *"Help me fill out this form"*
→ IRIS captures screen → understands the form → guides user step by step

### "Watch & Alert" Mode
IRIS periodically captures screen → detects important changes
→ *"Hey, looks like you got a new email from your boss"*

### "Do This For Me" Mode (GUI Agent)
User says: *"Open Chrome and search for Python tutorials"*
→ IRIS uses vision + operator to execute multi-step task autonomously

---

## ⚡ Performance Optimization

1. **Screenshot caching** — Don't re-capture if screen hasn't changed (pixel diff)
2. **Resolution scaling** — Downscale screenshots to 1024px width before sending
3. **Prompt caching** — Ollama keeps model in memory between requests
4. **Async pipeline** — Screenshot capture happens in parallel with STT
5. **Lazy loading** — Only initialize vision module when first needed
6. **Batch mode** — Group multiple vision queries into single context

---

## 🚀 Getting Started — Next Steps

1. **Install Ollama** and pull `openbmb/minicpm-o4.5`
2. Implement Phase 1: `backend/vision/minicpm_client.py`
3. Wire it into the audio engine (Phase 3)
4. Test the "What am I looking at?" flow end-to-end
5. Add UI controls for vision settings

Ready to start implementing? Say the word and we'll begin with Phase 1! 🎯
