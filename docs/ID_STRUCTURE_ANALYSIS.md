# IRIS Voice ID Structure Analysis

## ✅ CLEANUP COMPLETED (2026-03-04)

**Status:** All ID structure cleanup tasks have been completed as per spec `.kilo/specs/iris-id-structure-cleanup`

### Changes Implemented:
1. **Backend Sections Created:** `model_selection`, `inference_mode`, `skills`, `profile`
2. **Backend Sections Renamed:** `gui` → `desktop_control`
3. **Field Reorganization:** Wake fields → `wake` section, TTS fields → `speech` section
4. **Terminology:** `SUBNODE_CONFIGS` → `SECTION_CONFIGS`, `SubNode` → `Section`, `MiniNode` → `Card`, `subnode_id` → `section_id`
5. **Removed:** audio-model-card, voice-engine-card, workflows-card, shortcuts-card, mcp-servers-card, saved-workflows-card, favorites section, confirmed mini node feature
6. **Field IDs:** `assistant_name` → `agent_name`, `personality` → `persona`

### Backward Compatibility: NO BACKWARD COMPATIBILITY - All old terminology explicitly rejected (11 tests passing)

---

## Overview

This document provides a comprehensive visual mapping of the ID structure between the frontend (UI) and backend. **Note: The mismatches described below have been RESOLVED by the cleanup.**

**Key Terminology:**
- **Card IDs** (e.g., `microphone-card`) - Frontend UI component identifiers
- **Section IDs** (e.g., `input`, `model_selection`) - Backend data organization keys
- **Field IDs** (e.g., `input_device`) - Individual input field identifiers

---

## CARD IDs with Missing Backend Sections

The following Card IDs map to Section IDs that **DO NOT EXIST** in the backend:

| Card ID | Maps To Section | Backend Exists? | Impact |
|---------|-----------------|-----------------|--------|
| `audio-model-card` | `model` | ❌ NO | Backend has `audio_model` (underscore) |
| `models-card` | `model_selection` | ❌ NO | Section doesn't exist in backend |
| `inference-card` | `inference_mode` | ❌ NO | Section doesn't exist in backend |
| `wake-word-card` | `input` | ⚠️ PARTIAL | Section exists but wake fields missing |
| `speech-card` | `output` | ⚠️ PARTIAL | Section exists but speech fields missing |
| `mcp-servers-card` | `extensions` | ❌ NO | Section doesn't exist in backend |
| `skills-card` | `extensions` | ❌ NO | Section doesn't exist in backend |
| `saved-workflows-card` | `extensions` | ❌ NO | Section doesn't exist in backend |

---

## Visual Category Mappings

### 1. VOICE Category

```
┌─────────────────────────────────────────────────────────────────┐
│                        VOICE CATEGORY                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────┐      ┌─────────────────────────┐    │
│  │    microphone-card      │      │     speaker-card        │    │
│  │  ┌───────────────────┐  │      │  ┌───────────────────┐  │    │
│  │  │ input_device      │◄─┼──────┼──┤ output_device     │  │    │
│  │  │ input_volume      │  │      │  │ output_volume     │  │    │
│  │  │ wake_word_enabled │  │      │  │ tts_enabled       │  │    │
│  │  │ wake_sensitivity  │  │      │  │ tts_voice         │  │    │
│  │  │ voice_profile     │  │      │  │ tts_speed         │  │    │
│  │  └───────────────────┘  │      │  └───────────────────┘  │    │
│  └─────────────────────────┘      └─────────────────────────┘    │
│                                                                   │
│  ┌─────────────────────────┐      ┌─────────────────────────┐    │
│  │   voice-engine-card     │      │    audio-model-card     │    │
│  │  ┌───────────────────┐  │      │  ┌───────────────────┐  │    │
│  │  │ stt_engine        │  │      │  │ audio_model       │  │    │
│  │  │ voice_activity    │  │      │  │ audio_language    │  │    │
│  │  │ noise_suppression │  │      │  └───────────────────┘  │    │
│  │  └───────────────────┘  │      │   ❌ NO BACKEND SECTION │    │
│  └─────────────────────────┘      └─────────────────────────┘    │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Backend VOICE Sections:**
```
┌─────────────────────────────────────────────────────────────────┐
│                     BACKEND VOICE SECTIONS                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Section: input                   Section: output                 │
│  ┌───────────────────┐            ┌───────────────────┐          │
│  │ input_device      │✅          │ output_device     │✅         │
│  │ input_sensitivity │❌ DIFF     │ master_volume     │❌ DIFF    │
│  │ noise_gate        │❌ MISS     │ output_test       │❌ MISS    │
│  │ vad               │❌ MISS     │ latency_comp      │❌ MISS    │
│  │ input_test        │❌ MISS     └───────────────────┘          │
│  └───────────────────┘                                           │
│                                                                   │
│  Section: processing              Section: audio_model            │
│  ┌───────────────────┐            ┌───────────────────┐          │
│  │ noise_reduction   │❌ DIFF     │ model_mode        │❌ DIFF    │
│  │ echo_cancellation │❌ MISS     │ native_audio_path │❌ MISS    │
│  │ voice_enhancement │❌ MISS     │ api_base_url      │❌ MISS    │
│  │ automatic_gain    │❌ MISS     │ api_key           │❌ MISS    │
│  └───────────────────┘            │ api_model         │❌ MISS    │
│                                   │ temperature       │❌ MISS    │
│                                   │ max_tokens        │❌ MISS    │
│                                   └───────────────────┘          │
│                                                                   │
│  ❌ MISSING Sections in Frontend: wake, speech                    │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

### 2. AGENT Category

```
┌─────────────────────────────────────────────────────────────────┐
│                        AGENT CATEGORY                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────┐      ┌─────────────────────────┐    │
│  │     models-card         │      │    inference-card       │    │
│  │  ┌───────────────────┐  │      │  ┌───────────────────┐  │    │
│  │  │ model_provider    │  │      │  │ mode              │  │    │
│  │  │ model_name        │  │      │  │ temperature       │  │    │
│  │  │ api_key           │  │      │  │ max_tokens        │  │    │
│  │  └───────────────────┘  │      │  └───────────────────┘  │    │
│  │   ❌ NO BACKEND SECTION │      │   ❌ NO BACKEND SECTION │    │
│  └─────────────────────────┘      └─────────────────────────┘    │
│                                                                   │
│  ┌─────────────────────────┐      ┌─────────────────────────┐    │
│  │   personality-card      │      │      memory-card        │    │
│  │  ┌───────────────────┐  │      │  ┌───────────────────┐  │    │
│  │  │ agent_name        │◄─┼──────┼──┤ memory_enabled    │  │    │
│  │  │ persona           │◄─┼──────┼──┤ context_window    │  │    │
│  │  │ greeting_message  │  │      │  │ memory_persistence│  │    │
│  │  └───────────────────┘  │      │  └───────────────────┘  │    │
│  └─────────────────────────┘      └─────────────────────────┘    │
│                                                                   │
│  ┌─────────────────────────┐      ┌─────────────────────────┐    │
│  │  tool-permissions-card  │      │    integrations-card    │    │
│  │  ┌───────────────────┐  │      │  ┌───────────────────┐  │    │
│  │  │ allowed_tools     │  │      │  │ gmail_toggle      │  │    │
│  │  │ tool_confirmations│  │      │  │ telegram_toggle   │  │    │
│  │  │ permission_alerts │  │      │  │ discord_toggle    │  │    │
│  │  └───────────────────┘  │      │  └───────────────────┘  │    │
│  │   ✅ Security System    │      │   ✅ MCP Integration    │    │
│  └─────────────────────────┘      └─────────────────────────┘    │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**TWO-AGENT SYSTEM ALREADY IMPLEMENTED (via Tool Bridge)**
- Brain Agent (lfm2-8b): Reasoning, planning, conversation
- Executor Agent (lfm2.5-1.2b-instruct): Tool execution, instruction following
- Communication via Model Router and Tool Bridge in backend/agent/

**Backend AGENT Sections:**
```
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND AGENT SECTIONS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ❌ MISSING: model_selection (models-card)                        │
│  ❌ MISSING: inference_mode (inference-card)                      │
│                                                                   │
│  Section: identity                Section: memory                 │
│  ┌───────────────────┐            ┌───────────────────┐          │
│  │ assistant_name    │❌ ID       │ context_visual    │❌ DIFF    │
│  │ personality       │❌ ID       │ token_count       │❌ DIFF    │
│  │ knowledge         │❌ MISS     │ conversation_hist │❌ DIFF    │
│  │ response_length   │❌ MISS     │ clear_memory      │❌ DIFF    │
│  └───────────────────┘            │ export_memory     │❌ DIFF    │
│                                   └───────────────────┘          │
│                                                                   │
│  ✅ EXISTS but no Card: wake         ✅ EXISTS but no Card: speech│
│  ┌───────────────────┐            ┌───────────────────┐          │
│  │ wake_word_enabled │            │ tts_voice         │          │
│  │ wake_phrase       │            │ speaking_rate     │          │
│  │ detection_sens    │            │ pitch_adjustment  │          │
│  │ activation_sound  │            │ pause_duration    │          │
│  │ sleep_timeout     │            │ voice_cloning     │          │
│  └───────────────────┘            └───────────────────┘          │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

### 3. AUTOMATE Category

```
┌─────────────────────────────────────────────────────────────────┐
│                       AUTOMATE CATEGORY                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  tool-permissions-card            vision-card                     │
│  ┌───────────────────┐            ┌───────────────────┐          │
│  │ allowed_tools     │            │ vision_enabled    │✅         │
│  │ tool_confirmations│            │ vision_model      │✅         │
│  └───────────────────┘            └───────────────────┘          │
│                                                                   │
│  workflows-card                   shortcuts-card                  │
│  ┌───────────────────┐            ┌───────────────────┐          │
│  │ workflow_1        │            │ shortcut_1        │          │
│  │ workflow_2        │            │ shortcut_2        │          │
│  │ workflow_3        │            │ shortcut_3        │          │
│  └───────────────────┘            └───────────────────┘          │
│  (type: custom - no backend)       (type: custom - no backend)   │
│                                                                   │
│  gui-card (Desktop Control)       extensions (3 cards)            │
│  ┌───────────────────┐            ┌───────────────────┐          │
│  │ gui_enabled       │✅          │ mcp_server_1      │          │
│  │ gui_precision     │✅          │ mcp_server_2      │          │
│  │ (voice automation)│            │ skill_1           │          │
│  └───────────────────┘            │ skill_2           │          │
│                                   │ saved_workflow_1  │          │
│                                   │ saved_workflow_2  │          │
│                                   └───────────────────┘          │
│                                   ❌ NO BACKEND SECTION           │
└─────────────────────────────────────────────────────────────────┘
```

**Backend AUTOMATE Sections:**
```
┌─────────────────────────────────────────────────────────────────┐
│                   BACKEND AUTOMATE SECTIONS                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  tools              vision            workflows                   │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐          │
│  │active_servers│   │vision_enabled│✅  │workflow_list │          │
│  │tool_browser  │   │screen_context│✅  │create_workflow│         │
│  │quick_actions │   │proactive_mon │   │schedule      │          │
│  │tool_categories│  │monitor_interval│  │conditions    │          │
│  └──────────────┘   │ollama_endpoint│   └──────────────┘          │
│                     │vision_model   │                            │
│                     └──────────────┘                            │
│                                                                   │
│  shortcuts          gui             favorites                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐          │
│  │global_hotkey │   │ui_tars_prov  │   │favorite_cmds │          │
│  │voice_commands│   │model_provider│   │recent_actions│          │
│  │gesture_trig  │   │api_key       │   │success_rate  │          │
│  │key_combos    │   │max_steps     │   │edit_favorites│          │
│  └──────────────┘   │safety_confirm│   └──────────────┘          │
│                     │debug_mode    │   ❌ NO matching Card       │
│                     └──────────────┘                            │
│                                                                   │
│  ❌ MISSING: extensions section (3 cards)                         │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Field ID Comparison Tables

### VOICE → input Section

| Frontend Field | Backend Field | Match Status | Notes |
|----------------|---------------|--------------|-------|
| `input_device` | `input_device` | ✅ MATCH | Same ID |
| `input_volume` | `input_sensitivity` | ❌ MISMATCH | Different purpose? |
| `wake_word_enabled` | - | ❌ MISSING IN BACKEND | In wrong section |
| `wake_word_sensitivity` | - | ❌ MISSING IN BACKEND | In wrong section |
| `voice_profile` | - | ❌ MISSING IN BACKEND | No equivalent |
| - | `noise_gate` | ❌ MISSING IN FRONTEND | Not implemented |
| - | `vad` | ❌ MISSING IN FRONTEND | Not implemented |
| - | `input_test` | ❌ MISSING IN FRONTEND | Not implemented |

### VOICE → output Section

| Frontend Field | Backend Field | Match Status | Notes |
|----------------|---------------|--------------|-------|
| `output_device` | `output_device` | ✅ MATCH | Same ID |
| `output_volume` | `master_volume` | ⚠️ ID MISMATCH | Same purpose, different ID |
| `tts_enabled` | - | ❌ MISSING IN BACKEND | In wrong section |
| `tts_voice` | - | ❌ MISSING IN BACKEND | In wrong section |
| `tts_speed` | - | ❌ MISSING IN BACKEND | In wrong section |
| - | `output_test` | ❌ MISSING IN FRONTEND | Not implemented |
| - | `latency_compensation` | ❌ MISSING IN FRONTEND | Not implemented |

### AGENT → identity Section

| Frontend Field | Backend Field | Match Status | Notes |
|----------------|---------------|--------------|-------|
| `agent_name` | `assistant_name` | ⚠️ ID MISMATCH | Same purpose, different ID |
| `persona` | `personality` | ⚠️ ID MISMATCH | Same purpose, different ID |
| `greeting_message` | - | ❌ MISSING IN BACKEND | No equivalent |
| - | `knowledge` | ❌ MISSING IN FRONTEND | No equivalent |
| - | `response_length` | ❌ MISSING IN FRONTEND | No equivalent |

### AGENT → memory Section

| Frontend Field | Backend Field | Match Status | Notes |
|----------------|---------------|--------------|-------|
| `memory_enabled` | - | ❌ MISSING IN BACKEND | Different model |
| `context_window` | - | ❌ MISSING IN BACKEND | Different model |
| `memory_persistence` | - | ❌ MISSING IN BACKEND | Different model |
| - | `context_visualization` | ❌ MISSING IN FRONTEND | Display-only |
| - | `token_count` | ❌ MISSING IN FRONTEND | Display-only |
| - | `conversation_history` | ❌ MISSING IN FRONTEND | Action field |
| - | `clear_memory` | ❌ MISSING IN FRONTEND | Action field |
| - | `export_memory` | ❌ MISSING IN FRONTEND | Action field |

---

## Critical Issues Summary

### 🔴 HIGH SEVERITY - Data Loss Risk

1. **models-card & inference-card**
   - Frontend has these cards with fields
   - Backend has NO corresponding sections
   - User settings will NOT persist

2. **audio-model-card → model vs audio_model**
   - Card maps to `model` section
   - Backend has `audio_model` section
   - Different IDs = no data sync

3. **Memory Section Mismatch**
   - Frontend: Configuration fields (enabled, window, persistence)
   - Backend: Action/display fields (visualization, count, history)
   - Completely different purposes

### 🟡 MEDIUM SEVERITY - Field Organization

1. **Wake Word Fields in Wrong Section**
   - Frontend: `input` section
   - Backend: `wake` section
   - Should be consolidated

2. **TTS Fields in Wrong Section**
   - Frontend: `output` section
   - Backend: `speech` section
   - Should be consolidated

3. **Identity Field Name Mismatches**
   - `agent_name` vs `assistant_name`
   - `persona` vs `personality`
   - Same concepts, different IDs

### 🟢 LOW SEVERITY - Missing Features

1. **Extensions Section**
   - 3 cards in frontend (mcp-servers, skills, saved-workflows)
   - No backend support
   - All fields are `type: 'custom'`

2. **Field Type Mismatches**
   - Frontend uses: `password`, `status`, `button`, `info`, `custom`, `section`
   - Backend only supports: `TEXT`, `SLIDER`, `DROPDOWN`, `TOGGLE`, `COLOR`, `KEY_COMBO`

---

## Appendix: What "GUI" Actually Does

### Current State
The `gui-card` (shown as "GUI" in the UI) provides **Desktop Automation** capabilities - allowing the AI agent to control the user's computer through voice commands.

### Features When Enabled

| Feature | What It Does | Example Voice Command |
|---------|--------------|----------------------|
| **execute_task** | Performs multi-step desktop tasks | "Open Chrome and search for weather" |
| **click_element** | Clicks buttons, links, UI elements | "Click the Save button" |
| **type_text** | Types text into focused fields | "Type my email into the login field" |
| **take_screenshot** | Captures screen for analysis | Agent sees what's on screen |
| **execute_with_vision** | Sees screen and performs actions | "Find the blue download button and click it" |

### What Users Need to Understand

**When enabled:**
- The agent can open applications, click buttons, type text
- Voice-controlled desktop automation
- Optional: Agent can "see" the screen (vision mode) for better accuracy
- Safety: Can require confirmation before destructive actions

### Alternative Naming Options

| Current | Alternative | Why It's Better |
|---------|-------------|-----------------|
| **GUI** | **Desktop Control** | Users understand "control my desktop" - "GUI" is technical jargon |
| **GUI Automation** | **Computer Control** | Clear that agent controls the computer |
| **GUI** | **Screen Automation** | Describes what it automates |
| **GUI** | **Hands-Free Mode** | Emphasizes voice control benefit |
| **GUI Automation** | **Autopilot** | Futuristic, implies agent can drive |

**Recommendation: "Desktop Control"** or **"Computer Control"**

### Current Configuration Fields

```typescript
// Current gui-card fields
gui: [
  {
    id: 'gui-card',
    label: 'GUI',  // <-- Should be "Desktop Control"
    fields: [
      { id: 'gui_enabled', label: 'GUI Automation Enabled' },  // <-- "Desktop Control"
      { id: 'gui_precision', label: 'Precision' }  // Low/Medium/High
    ]
  }
]
```

### Proposed Renamed Structure

```typescript
desktop_control: [
  {
    id: 'desktop-control-card',
    label: 'Desktop Control',
    fields: [
      { id: 'desktop_control_enabled', label: 'Enable Desktop Control' },
      { id: 'require_confirmation', label: 'Ask Before Actions', defaultValue: true },
      { id: 'use_vision_guidance', label: 'Use Screen Vision', defaultValue: false }
    ]
  }
]
```

---

### FAQ: Do I Need MiniCPM (Vision) if I Have Desktop Control?

**Short Answer: They serve different purposes. You need BOTH for intelligent automation.**

| Feature | Desktop Control | Vision (MiniCPM) |
|---------|-----------------|------------------|
| **Purpose** | **CONTROLS** the desktop | **SEES** and understands the screen |
| **Actions** | Clicks, types, opens apps | Analyzes screenshots |
| **Without the other** | Clicks blindly at coordinates | Can see but can't act |
| **Together** | Smart automation with visual understanding |  |

**Example:**
- **Desktop Control only:** "Click at coordinates (500, 300)" (may miss the button)
- **Vision only:** "I can see the Save button" (can't click it)
- **Both together:** "I see the Save button, I'll click it for you" ✅

**Backend Integration:**
- `gui_automation_server.py` has `use_vision` flag
- When enabled, it uses MiniCPM to find UI elements before clicking
- `vision-card` controls MiniCPM independently
- `desktop-control-card` controls automation, can optionally use vision

**Recommendation:** Keep both systems - they complement each other.

---

## Recommended Structure

### Option 1: Align Frontend to Backend

Update `mini-nodes.ts` to match backend `SUBNODE_CONFIGS`:

1. Rename `model` section → `audio_model`
2. Add `wake` and `speech` sections to frontend
3. Remove or stub `model_selection` and `inference_mode` cards
4. Update field IDs to match backend
5. Add missing backend fields to frontend

### Option 2: Align Backend to Frontend

Update `models.py` to match frontend `mini-nodes.ts`:

1. Rename `audio_model` section → `model`
2. Add `model_selection` and `inference_mode` sections
3. Consolidate wake fields into `input` section
4. Consolidate speech/tts fields into `output` section
5. Update field IDs to match frontend

---

## Appendix: Complete ID Mapping

### CARD_TO_SECTION_ID Mapping (navigation-constants.ts)

```
microphone-card      → input              ✅ OK
wake-word-card       → input              ⚠️ Fields mismatch
speaker-card         → output             ✅ OK
speech-card          → output             ⚠️ Fields mismatch
voice-engine-card    → processing         ⚠️ Fields mismatch
audio-model-card     → model              ❌ Backend has 'audio_model'

models-card          → model_selection    ❌ NO BACKEND
inference-card       → inference_mode     ❌ NO BACKEND
personality-card     → identity           ⚠️ Fields mismatch
memory-card          → memory             ⚠️ Fields mismatch

tool-permissions-card → tools             ✅ OK
vision-card          → vision             ✅ OK
workflows-card       → workflows          ✅ OK (custom type)
shortcuts-card       → shortcuts          ✅ OK (custom type)
gui-card             → gui                ✅ OK (Desktop Control - voice automation)
mcp-servers-card     → extensions         ❌ NO BACKEND
skills-card          → extensions         ❌ NO BACKEND
saved-workflows-card → extensions         ❌ NO BACKEND

power-card           → power              ✅ OK
window-card          → display            ✅ OK
storage-card         → storage            ✅ OK
connection-card      → network            ✅ OK

startup-card         → startup            ✅ OK
behavior-card        → behavior           ✅ OK
notifications-card   → notifications      ✅ OK

analytics-card       → analytics          ✅ OK (custom type)
logs-card            → logs               ✅ OK (custom type)
diagnostics-card     → diagnostics        ✅ OK (custom type)
updates-card         → updates            ✅ OK (custom type)
```

---

## DESIRED USER EXPERIENCE & RECOMMENDATIONS

Based on the product vision, here is the simplified structure the UI should follow:

### User Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER ONBOARDING FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. LAUNCH ──> 2. AGENT SETUP ──> 3. VOICE SETUP ──> 4. OPTIONAL SETTINGS   │
│                                                                              │
│  STEP 2: AGENT SETUP (Primary - Must Configure)                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Choose Model Provider:                                              │    │
│  │  ○ Local Model (LFM 2.5 - included)                                  │    │
│  │  ○ API Key (OpenAI, etc.)                                            │    │
│  │  ○ VPS Gateway                                                       │    │
│  │                                                                      │    │
│  │  Two-Agent Architecture:                                             │    │
│  │  ┌──────────────────┐  ┌──────────────────┐                         │    │
│  │  │ Reasoning Agent  │  │ Tool Call Agent  │                         │    │
│  │  │ (handles logic)  │  │ (handles actions)│                         │    │
│  │  └──────────────────┘  └──────────────────┘                         │    │
│  │                                                                      │    │
│  │  [Can use same model for both, or different models with lazy load]   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  STEP 3: VOICE SETUP (Communication)                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Input: [Input Device Dropdown]       Volume: [Slider]               │    │
│  │  Output: [Output Device Dropdown]     Volume: [Slider]               │    │
│  │                                                                      │    │
│  │  Wake Word (Picovoice Only):                                         │    │
│  │  ○ jarvis  ○ hey computer  ○ computer  ○ [Custom trained phrase]     │    │
│  │                                                                      │    │
│  │  Agent Voice: [TTS Voice Dropdown - Nova, Alloy, etc.]               │    │
│  │                                                                      │    │
│  │  Language (if LFM 2.5 Audio supports): [Language Dropdown]           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  STEP 4: OPTIONAL SETTINGS (As Needed)                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  • User Profile & Modes (AI learns and adapts)                       │    │
│  │  • Skills (Agent creates/maintains - starts with skill-creation)     │    │
│  │  • Vision Settings                                                   │    │
│  │  • Desktop Control (voice-controlled computer automation)            │    │
│  │  • System Settings                                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### Recommended Card Structure

#### KEEP (Essential Functionality)

| Card ID | Section | Backend Exists | Notes |
|---------|---------|----------------|-------|
| `models-card` | `model_selection` | ❌ NEEDS BUILD | **CRITICAL** - Primary user choice (Local/API/VPS) |
| `inference-card` | `inference_mode` | ❌ NEEDS BUILD | **CRITICAL** - Token usage control (simplified fields) |
| `microphone-card` | `input` | ✅ | Input device, volume |
| `speaker-card` | `output` | ✅ | Output device, volume |
| `wake-word-card` | `wake` | ⚠️ REORGANIZE | Move wake fields here, use ONLY Picovoice |
| `speech-card` | `speech` | ⚠️ REORGANIZE | Move TTS fields here |
| `personality-card` | `identity` | ✅ | Agent name, persona |
| `memory-card` | `memory` | ⚠️ FIX FIELDS | User config, not display fields |
| `vision-card` | `vision` | ✅ | Vision enabled, model |
| `gui-card` | `gui` | ✅ | Desktop Control - voice-controlled desktop automation |
| `tool-permissions-card` | `tools` | ✅ | **SECURITY** - Tool permission alerts & audit log |
| `skills-card` | `skills` | ❌ NEEDS BUILD | **NEW** - Track agent/user skills |
| `profile-card` | `profile` | ❌ NEEDS BUILD | **NEW** - User profile & modes |
| `integrations-card` | `integrations` | ✅ | **EXISTS** - MCP integrations (Gmail, Telegram, Discord, etc.) |

#### REMOVE (No Backend / Not Needed)

| Card ID | Reason |
|---------|--------|
| `audio-model-card` | Confusing - audio model config should be in model_selection |
| `voice-engine-card` | Processing fields don't match backend - remove or consolidate |
| `workflows-card` | **EXPLICITLY REMOVE** per requirements |
| `shortcuts-card` | Not core functionality - remove |
| `mcp-servers-card` | **REPLACED** by integrations-card per MCP spec |
| `saved-workflows-card` | No backend, not MVP - remove |
| `favorites` (backend only) | No frontend card - remove from backend |

---

### Required Backend Sections to Build

```
┌─────────────────────────────────────────────────────────────────┐
│              NEW BACKEND SECTIONS NEEDED                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. model_selection                                              │
│     ├─ model_provider (local | api | vps)                       │
│     ├─ reasoning_model (dropdown - lazy loaded)                 │
│     ├─ tool_model (dropdown - lazy loaded)                      │
│     ├─ use_same_model_for_both (toggle)                         │
│     ├─ api_key (password - if api selected)                     │
│     └─ vps_endpoint (text - if vps selected)                    │
│                                                                  │
│  2. inference_mode (SIMPLIFIED - User-Friendly Terms)            │
│     ├─ agent_thinking_style (dropdown: concise | balanced | thorough)│
│     ├─ max_response_length (dropdown: short | medium | long)    │
│     ├─ reasoning_effort (dropdown: fast | balanced | accurate)  │
│     └─ tool_mode (dropdown: auto | ask_first | disabled)        │
│         (Controls how the tool-calling agent behaves)           │
│                                                                  │
│     NOTE: Two-agent system (Brain + Executor) already exists    │
│     via Tool Bridge in backend/agent/agent_kernel.py            │
│                                                                  │
│  3. skills                                                       │
│     ├─ skills_list (array - managed by agent)                   │
│     └─ skill_creation_enabled (toggle - always true initially)  │
│                                                                  │
│  4. profile                                                      │
│     ├─ user_profile (object - AI learned)                       │
│     ├─ active_mode (dropdown - modes activate skills)           │
│     └─ modes_list (array - user defined modes)                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

### Field Consolidation Plan

#### VOICE Category - Consolidated Structure

```
input Section (microphone-card)
├── input_device (dropdown)
├── input_volume (slider 0-100)
└── noise_suppression (toggle)

output Section (speaker-card)
├── output_device (dropdown)
├── output_volume (slider 0-100)
└── latency_compensation (slider 0-500ms)

wake Section (wake-word-card) - MOVED FROM input
├── wake_word_enabled (toggle)
├── wake_phrase (dropdown: jarvis | hey computer | computer | custom)
├── detection_sensitivity (slider 0-100)
├── custom_wake_word_path (text - for trained phrases)
└── activation_sound (toggle)

speech Section (speech-card) - MOVED FROM output
├── tts_enabled (toggle)
├── tts_voice (dropdown: Nova | Alloy | Echo | Fable | Onyx | Shimmer)
├── speaking_rate (slider 0.5-2.0x)
└── language (dropdown - if LFM 2.5 Audio supports)
```

#### AGENT Category - New Structure

```
model_selection Section (models-card) - NEW
├── model_provider (dropdown: local | api | vps)
├── use_same_model (toggle)
├── reasoning_model (dropdown - populated lazy)
├── tool_model (dropdown - populated lazy, shown if !use_same_model)
├── api_key (password, shown if provider=api)
└── vps_endpoint (text, shown if provider=vps)

inference_mode Section (inference-card) - NEW
├── reasoning_temperature (slider 0-2, step 0.1)
├── reasoning_max_tokens (slider 256-8192, step 256)
├── tool_temperature (slider 0-2, step 0.1, shown if !use_same_model)
└── tool_max_tokens (slider 256-8192, step 256, shown if !use_same_model)

identity Section (personality-card)
├── agent_name (text)
├── persona (dropdown: professional | friendly | concise | creative)
└── greeting_message (text)

memory Section (memory-card) - FIXED
├── memory_enabled (toggle)
├── context_window (slider 5-50)
└── memory_persistence (toggle - save conversations)

skills Section (skills-card) - NEW
├── skills_display (custom - list of learned skills)
└─ skill_creation_enabled (toggle - agent can create skills)

profile Section (profile-card) - NEW (from memory foundation spec)
├── user_profile_display (custom - AI learned preferences)
├── active_mode (dropdown - selects skill/tool set)
└── modes_manager (custom - create/edit modes)
```

---

### Simplified Category Summary

| Category | Cards to Keep | Cards to Remove | New Cards Needed |
|----------|--------------|-----------------|------------------|
| **VOICE** | microphone, speaker, wake-word, speech | voice-engine, audio-model | - |
| **AGENT** | personality, memory | - | **models**, **inference**, **skills**, **profile** |
| **AUTOMATE** | vision, desktop-control | tool-permissions, workflows, shortcuts | - |
| **SYSTEM** | power, display, storage, network | - | - |
| **CUSTOMIZE** | startup, behavior, notifications | - | - |
| **MONITOR** | analytics, logs, diagnostics, updates | - | - |

---

### Terminology Cleanup

| Old Term | New Term | Location |
|----------|----------|----------|
| `SUBNODE_CONFIGS` | `SECTION_CONFIGS` | backend/models.py |
| `mini-nodes.ts` | `cards.ts` or keep as-is | frontend/data/ |
| `SubNode` | `Section` | backend/models.py |
| `MiniNode` | `Card` | frontend/types/ |
| `subnode_id` | `section_id` | All WebSocket messages |
| `card_id` | `card_id` (already correct) | All references |

---

### Action Items Summary

#### 🔴 CRITICAL - Build These First
1. Create `model_selection` backend section with lazy-loaded model dropdowns
2. Create `inference_mode` backend section for two-agent config
3. Create `skills` backend section for skill tracking
4. Create `profile` backend section for user modes (memory foundation)
5. Move wake fields from `input` to new `wake` section
6. Move TTS fields from `output` to new `speech` section

#### 🟡 HIGH PRIORITY - Fix These
7. Fix `memory` section fields (config vs display mismatch)
8. Add custom wake word phrase support (Picovoice trained file)
9. Add language selection to `speech` section (if LFM 2.5 supports)
10. Rename terminology: subnode → section throughout codebase

#### 🟢 MEDIUM PRIORITY - Clean Up
11. Remove `workflows-card`, `shortcuts-card`, `mcp-servers-card`, `saved-workflows-card`
12. Remove backend `favorites` section (no frontend)
13. Consolidate `voice-engine-card` functionality or remove
14. Remove `audio-model-card` (confusing overlap with model_selection)

#### 🔵 LOW PRIORITY - Nice to Have
15. Add conditional field display (show/hide based on other field values)
16. Implement profile modes that activate skill sets
17. Add user profile visualization from memory foundation

---

### Final Clean Structure

```
IRIS Application
├── VOICE
│   ├── Input (microphone-card) → input section
│   ├── Output (speaker-card) → output section
│   ├── Wake Word (wake-word-card) → wake section
│   └── Speech (speech-card) → speech section
├── AGENT
│   ├── Models (models-card) → model_selection section [NEW]
│   ├── Inference (inference-card) → inference_mode section [NEW]
│   ├── Personality (personality-card) → identity section
│   ├── Memory (memory-card) → memory section [FIXED]
│   ├── Skills (skills-card) → skills section [NEW]
│   ├── Profile (profile-card) → profile section [NEW]
│   ├── Tool Permissions (tool-permissions-card) → tools section [KEEP]
│   └── Integrations (integrations-card) → integrations section [EXISTS]
├── AUTOMATE
│   ├── Vision (vision-card) → vision section
│   └── Desktop Control (gui-card) → gui section
├── SYSTEM
│   ├── Power, Display, Storage, Network
├── CUSTOMIZE
│   ├── Startup, Behavior, Notifications
└── MONITOR
    ├── Analytics, Logs, Diagnostics, Updates
```

Total Cards: 22 (down from ~28)
Clean Sections: 24 (properly aligned)
Backend Coverage: 100% (every card has backend support)
