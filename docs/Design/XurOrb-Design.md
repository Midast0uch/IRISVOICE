# XurOrb — Design Document

> **Purpose:** Design rationale and architecture reference for the XurOrb component that replaces `components/iris/IrisOrb.tsx`.

**Date:** 2026-06-18
**Status:** Design complete, implementation plan at `docs/plans/2026-06-18-iris-orb-v2-spiral-dissolve-winner.md`
**Component name:** XurOrb
**Replaces:** `components/iris/IrisOrb.tsx` (665 lines, framer-motion)

---

## Problem

The existing `IrisOrb.tsx` is visually rich but has fundamental issues:

1. **Static navigation reveal** — Users see a glowing orb with no indication that categories exist. The only hint is `ChatActivationText` cycling through three hints near the orb.
2. **15+ framer-motion layers** — The orb stacks atmospheric pulse, neon core, plasma corona, edge bloom, liquid metal ring, glassmorphic base, reactor backlight, and more. Beautiful but heavy, hard to maintain, and disconnected from speech rhythm.
3. **No cadence reactivity** — The orb reacts to `audioLevel` (RMS volume) but not to speech rhythm (cadence). Whispering produces no visual response. TTS playback produces no visual response.
4. **No discoverable structure** — The 6 category system (Voice, Agent, Automate, System, Customize, Monitor) is invisible until you navigate. Users don't know what they can do.

XurOrb solves these by:
- Making the navigation system discoverable through visual structure (hex nodes on a radial arc)
- Replacing 15 framer-motion layers with a canvas-based particle shell system driven by **backend spectral flux cadence detection**
- Integrating the three primary actions (MENU, VOICE, CHAT) as always-visible glitch text labels on the orb's surface
- Feeling playful and alive through 3 cycling click animation modes (C-opening, D-burst, A-bloom)

---

## Design Exploration

We iterated through **10+ mockup concepts** in `app/orb-preview/page.tsx`:

### Orb Visual Variants (Section 1 — Spiral Variants)

| Badge | Name | Description | Verdict |
|-------|------|-------------|---------|
| Ref | Original PrototypeOrb | 68 particles, 2D Lissajous | Starting point |
| A | Density + depth-aware alpha | ~3.2× more particles, depth wave | Good but flat |
| **B** | **Shells with paired click behaviors** | **3 concentric shells, random C/D/A click pairs** | **★ WINNER** |
| C | Layered concentric shells | 105%/70%/42% scale, opening transition | Strong visual |
| D | Shells + depth + burst | 180/130/80 particles, magnetic pull text | Good breath |

**B (PrototypeOrbShellsRotating) won** — it combines the shell visual with 3 randomly cycling click animation pairs (C/D/A), giving the orb personality without committing to a single transition.

### Category Menu Layouts (Section 4 — Menu Mockups)

| Family | Description | Verdict |
|--------|-------------|---------|
| Radial Hex | 6 hex nodes in hexagonal arrangement | Strong but static |
| Radial Arc | 6 nodes on a half-arc above the orb | Cleaner than full circle |
| Wheel | Circular ring of 8+ nodes | Too crowded |
| Concentric | Inner 3 + outer 3 | Visually busy |
| Grid 2×3 | Flat grid below the orb | Felt like a menu |

**Radial Arc won** — half-arc above the orb keeps focus on the orb while revealing categories.

### Connection Styles

| Style | Verdict |
|-------|---------|
| No lines | Lost the "system" feeling |
| Faint lines | Looked like scaffolding |
| **Hover-only lines** | **Winner** — emergent, not scaffolding |
| Always-visible spokes | Too busy |

### Node Transition Variants (9 total)

**Group A:** Magnet Pull, Photon Burst, Orbit Sweep
**Group B:** Pulse Wave, Gravity Drop, Shatter
**Group C:** Iris Shutter, Fade+Stagger, **Spiral Dissolve (winner)**

The user picked Spiral Dissolve, then asked to add Gravity Drop and Magnet Pull as random alternates → **C-Random Rotate winner**.

---

## Winner Selection

### Orb Visual: B — ShellsRotating with C/D/A Animation Modes

The orb visual is extracted from `PrototypeOrbShellsRotating` into a pure canvas component (`OrbCanvas`) with 3 separately tweakable animation modes:

| Mode | Animation Type | Duration | Effect | Timing |
|------|---------------|----------|--------|--------|
| **C** | Opening transition | ~1.9s (1400ms open + 500ms settle) | Shells expand 0.7→1.05, bloom 1→1.18, speed 1→2.5→1 | Shortened from 2.3s |
| **D** | Gentle burst | ~0.75s decay (0.025/frame) | Pulse + 0.9× speed, 0.25 bloom | Slightly faster than original |
| **A** | Big bloom | ~2s decay (0.008/frame) | 0.7× speed, 0.25 bloom, deliberate | Unchanged |

**Why 3 separate modes, not one bundled effect:**
- Each mode's timing is independently adjustable via constants in `animationModes.ts`
- C-pair and D-pair were shortened from the original prototype values
- The modes cycle C → D → A → C on consecutive clicks (deterministic order, not random — easier to test)

### Category Menu: C-Random Rotate Winner

The radial arc with 6 hex nodes from `MenuMockups.tsx`. Each click on a node transitions directly to WheelView (level 3). The radial arc IS the category selector — no separate hexagonal control center.

---

## Component Architecture

```
XurOrb (components/iris/XurOrb.tsx)
├── OrbCanvas (components/iris/orb/OrbCanvas.tsx)
│   ├── 3 concentric particle shells (canvas-based)
│   ├── Depth-aware alpha
│   ├── Cadence-driven scale pulsing (from useCadenceDetection)
│   └── Animation mode effects (C/D/A) when animActive
├── animationModes.ts (components/iris/orb/animationModes.ts)
│   ├── C_OPENING_MS, C_SETTLING_MS (shortened)
│   ├── D_DECAY_PER_FRAME (slightly faster)
│   ├── A_DECAY_PER_FRAME
│   └── nextAnimationMode() — C → D → A → C cycle
├── RadialArcNodes (components/iris/radial/RadialArcNodes.tsx)
│   ├── SVG arc + spokes (hover-only lines)
│   ├── Hover ring animation
│   ├── Particles (useParticles hook)
│   ├── HexNode × 6 (category icons)
│   ├── Per-node labels (on hover)
│   ├── extraSVG prop (composable)
│   └── NO Orb inside (XurOrb owns the orb)
├── HexNode (components/iris/radial/HexNode.tsx)
│   ├── Hex clip path
│   ├── Hover glow
│   ├── Icon rendering
│   └── onClick / onHover props
├── GlitchText × 3 (components/iris/radial/GlitchText.tsx)
│   ├── MENU — top-center, 90px above orb center
│   ├── VOICE — left of orb center, 70px left
│   ├── CHAT — right of orb center, 70px right
│   └── Scramble animation (720ms, 30ms/frame)
├── WinTransitionEngine (components/iris/radial/WinTransitionEngine.ts)
│   ├── pickRandomTransition() — spiral/gravity/magnet (for RadialArcNodes only)
│   └── photonFlash() — brightness 1→3→1, scale 1→1.25→1
├── categories.ts (components/iris/radial/categories.ts)
│   └── 6 categories with tabler + lucide icons
├── hexToRgba.ts (components/iris/utils/hexToRgba.ts)
├── ChatActivationGlitch (components/iris/radial/ChatActivationGlitch.tsx)
│   └── One-shot "tap the CHAT label" hint (replaces ChatActivationText)
└── Hooks
    ├── useCadenceDetection (hooks/useCadenceDetection.ts)
    │   └── Maps voiceState → breathMode/breathLevel/isBreathing
    ├── useManualDragWindow (hooks/useManualDragWindow.ts)
    │   └── Tauri window dragging + double-click detection
    └── useReducedMotion (hooks/useReducedMotion.ts)
        └── Fallback to instant opacity for motion sensitivity
```

### Component Details

#### OrbCanvas
- **Source:** Extracted from `PrototypeOrbShellsRotating.tsx` (438 lines)
- **Rendering:** Canvas-based 3-shell particle system
- **Transparent background** — canvas has no background fill, just particles. The orb and nodes float on the app's existing background, just like the original IrisOrb.
- **No click handlers** — XurOrb handles all clicks
- **No built-in labels** — GlitchText handles labels
- **No animation cycling** — XurOrb passes `animationMode` + `animProgress` via props
- **Props:** `glowColor`, `breathMode`, `breathLevel`, `isBreathing`, `animationMode`, `animProgress`, `animActive`

#### RadialArcNodes
- **Source:** Extracted from C-Random Rotate winner in `MenuMockups.tsx`
- **Transparent background** — SVG and nodes have no background fill
- **No Orb inside** — the orb is rendered separately by XurOrb
- **Container:** 246×246 (scaled from original 300×300)
- **Node positioning:** 6 nodes at angles `Math.PI + (i / 5) * Math.PI` — half-arc from 180° to 360°
- **Radius:** 90px from center
- **Props:** `glowColor`, `isVisible`, `nodeStyle`, `onCategorySelect`, `extraSVG`

#### HexNode
- **Source:** Extracted from `MenuMockups.tsx`
- **Shape:** Hex clip path with hover glow
- **Props:** `glowColor`, `icon`, `isActive`, `onHover`, `onClick`

#### GlitchText
- **Always visible** at level 1 idle (MENU/VOICE/CHAT)
- **Hidden** at level 2+ or when chat-wings open
- **Scramble animation:** Random characters resolve into the final text over 720ms
- **Style:** Uppercase monospace, glow text shadow, opacity transition
- **Props:** `text`, `visible`, `color`, `fontSize?`, `className?`

#### categories.ts
- **Exact icon set from the winner prototype:**
  - Voice: `Mic` (lucide)
  - Agent: `IconRobot` (tabler)
  - Automate: `IconTopologyStar3` (tabler)
  - System: `IconBasketCog` (tabler)
  - Customize: `Palette` (lucide)
  - Monitor: `Activity` (lucide)

---

## Navigation Flow

| Level | What's Visible | Actions |
|-------|---------------|---------|
| **1 idle** | OrbCanvas + GlitchText (MENU/VOICE/CHAT) + cadence breathing | Click orb → cycle C/D/A + go back (nop at 1), double-click → voice, VOICE → toggle voice, CHAT → chat-wings, MENU → level 2 |
| **2** | OrbCanvas + GlitchText + RadialArcNodes (6 hex categories) + cadence | Click orb → back to 1, click hex node → WheelView (level 3), CHAT → wings, VOICE → voice |
| **3** | WheelView with selected category + orb (smaller, cadence still active) | Click orb → back to 2 |

### Click Behaviors

| Click Target | Animation | Navigation Action |
|---|---|---|
| **Orb** (level 1) | Cycle C/D/A mode | Cosmetic only (nop at level 1) |
| **Orb** (level > 1) | Cycle C/D/A mode | Navigate back one level |
| **Orb** (voice active) | None | Cancel voice command (intercepted) |
| **Orb** (wings open) | None | Close wings (intercepted) |
| **Orb** (double-click) | Double-click flash overlay | Toggle voice command |
| **MENU label** | Cycle C/D/A mode | Dispatch `EXPAND_TO_MAIN` → level 2 |
| **Hex node** | None (direct navigation) | Dispatch to WheelView → level 3 |
| **VOICE label** | None | Toggle `startVoiceCommand()` / `endVoiceCommand()` |
| **CHAT label** | Cycle C/D/A mode | `setMainView('chat')` → open chat-wings |

### Transparent Background

XurOrb and RadialArcNodes have **transparent backgrounds** — just like the original IrisOrb. The canvas has no background fill (only particles), the SVG has no background rect, and the container divs have no background color. The orb and nodes float on the app's existing background.

---

## Cadence Detection System

### Architecture: Backend-Driven (Option B)

Cadence detection runs in the **backend STT pipeline**, not client-side. This ensures:
- Cadence data flows through the same WebSocket connection as everything else
- No separate client-side microphone access needed (avoids permission issues)
- Works consistently across Tauri and web modes
- TTS audio level can also be broadcast (client-side can't monitor server-played audio)

### Backend: CadenceDetector (spectral flux)

**File:** `backend/audio/cadence_detector.py`

Spectral flux = sum of positive differences between consecutive FFT frames.
- High flux = spectral change = speech onset (syllable beat)
- Low flux = spectral stability = silence or sustained vowel
- **Whispers produce cadence beats without volume** — this is the key advantage over RMS

```python
class CadenceDetector:
    def __init__(self, sample_rate=16000, fft_size=512, hop_size=256):
        # Hann window, FFT, EMA smoothing (0.85), rolling normalization (10 frames)
    
    def process(self, audio_chunk: np.ndarray) -> float:
        # Returns cadence level 0-1
    
    def reset(self):
        # Reset state when recording starts/stops
```

### Backend: TTS Audio Level

**File:** `backend/agent/tts.py`

During TTS streaming (`synthesize_stream()`), compute RMS per audio chunk and broadcast:
- TTS cadence = RMS (no spectral flux needed for playback — the rhythm IS the audio)
- When TTS finishes, send a final envelope with zero values

### Consolidated `audio_envelope` WS Message

Replaces the old `audio_level` message with a richer, unified format:

```json
{
  "type": "audio_envelope",
  "rms": 0.0,
  "cadence": 0.0,
  "phase": "listening" | "speaking" | "idle"
}
```

One message type covers both STT and TTS phases. Simpler parsing, richer data.

### Voice State → Cadence Mapping

| voiceState | Cadence Source | breathMode | breathLevel | isBreathing |
|------------|---------------|------------|-------------|-------------|
| idle | None | "D" | 0 | false |
| listening | Backend spectral flux (`cadenceLevel`) | "D" | cadenceLevel | true |
| processing_conversation | Gentle pulse | "D" | 0.3 | true |
| processing_tool | Gentle pulse | "D" | 0.2 | true |
| speaking | Backend TTS RMS (`ttsAudioLevel`) | "D" | ttsAudioLevel | true |
| error | None | "D" | 0 | false |

### useCadenceDetection Hook

**File:** `hooks/useCadenceDetection.ts`

Centralizes the voice state → cadence parameter mapping. XurOrb reads cadence internally via this hook, NOT via props. This ensures cadence is always driven by the live backend connection.

**Client-side fallback (dev mode):** If `cadenceLevel` is 0 but `voiceState === "listening"`, fall back to `audioLevel * 0.7` as a proxy.

---

## Communication Layer

### Inbound WS Messages (backend → frontend)

| Message Type | Payload | Purpose | Consumer |
|-------------|---------|---------|----------|
| `audio_envelope` | `{ rms, cadence, phase }` | Audio level + cadence during listening/speaking | NavigationContext → useCadenceDetection → XurOrb |
| `audio_level` | `{ level }` | Legacy RMS only (backward compat, remove after migration) | Old IrisOrb.tsx |
| `wake_detected` | `{}` | Wake word heard | XurOrb via onCallbacksReady → startVoiceCommand |
| `listening_state` | `{ state }` | Voice state change | NavigationContext → voiceState |
| `text_response` | `{ text, sender, thinking, suggestions }` | Chat message from backend | NavigationContext → lastTextResponse → ChatWing |
| `chat_typing` | `{ typing }` | Backend is generating response | NavigationContext → isChatTyping → ChatWing |
| `tts_word` | `{ word_index }` | TTS word timing (future) | ChatWing (replaces fake 200ms interval) |
| `native_audio_response` | `{ debug_text }` | Debug feedback from native audio | XurOrb via onCallbacksReady |

### Outbound WS Messages (frontend → backend)

| Message Type | Payload | Purpose | Sender |
|-------------|---------|---------|--------|
| `voice_command_start` | `{}` | Start STT recording | XurOrb / NavigationContext.startVoiceCommand |
| `voice_command_end` | `{}` | Stop STT recording | XurOrb / NavigationContext.endVoiceCommand |
| `voice_command_cancel` | `{}` | Cancel active voice command | XurOrb / NavigationContext.cancelVoiceCommand |
| `text_message` | `{ text }` | Chat message (WS fallback) | ChatWing.handleSendMessage |
| `crawler_query` | `{ query }` | Web search query | ChatWing.handleSendMessage |
| `tts_play` | `{ text }` | Request TTS playback | ChatWing.handlePlayTTSClick |
| `new_conversation` | `{ conversation_id, timestamp }` | New chat thread | ChatWing.handleNewConversation |
| `message_feedback` | `{ message_id, feedback }` | Thumbs up/down | ChatWing.handleFeedback |
| `terminal_input` | `{ line }` | Developer shell command | ChatWing.handleSendMessage |
| `notification_response` | `{ notification_id, action }` | Permission grant/deny | ChatWing |

### REST Endpoints

| Endpoint | Method | Purpose | Caller |
|----------|--------|---------|--------|
| `/api/chat` | POST | Primary chat message (reliable, no WS dependency) | ChatWing.handleSendMessage |
| `/auth/session` | GET | Session token (future) | Launcher handoff |

### XurOrb's Direct Dependencies

1. **Reads from NavigationContext:** `voiceState`, `audioLevel`, `cadenceLevel`, `ttsAudioLevel`, `audioPhase`
2. **Calls on NavigationContext:** `startVoiceCommand()`, `endVoiceCommand()`, `cancelVoiceCommand()`, `dispatch()`, `setMainView()`
3. **Receives via onCallbacksReady:** `handleWakeDetected` (wake word), `handleNativeAudioResponse` (debug text)
4. **Does NOT directly handle:** `lastTextResponse`, `isChatTyping`, `sendMessage` — those are ChatWing's concern

### ChatWing Integration

XurOrb and ChatWing share state via NavigationContext:
- **voiceState** — both read it. XurOrb breathes with it, ChatWing shows typing indicator + pulse dot.
- **audioLevel** — both read it. XurOrb uses it for cadence fallback, ChatWing uses it for the pulse dot animation.
- **lastTextResponse** — ChatWing processes this into conversation messages. XurOrb doesn't need it.
- **sendMessage** — ChatWing uses it for WS messages. XurOrb doesn't send chat messages.

When CHAT label is clicked → `setMainView("chat")` → ChatWing opens → both share the same NavigationContext.

The `onCallbacksReady` wake word bridge is the ONLY backend→XurOrb direct callback. Everything else flows through NavigationContext.

---

## Visual System

### Container Sizing
- Radial arc: 246×246 (scaled from 300×300, 18% smaller)
- Orb at center: 150×150
- Node radius: 90px from center
- Internal measurements scaled proportionally (radius 110→90, center 150→123)

### Transparent Background
XurOrb and RadialArcNodes have **transparent backgrounds** — same as the original IrisOrb:
- Canvas: no background fill, only particles
- SVG: no background rect
- Container divs: no background color
- The orb and nodes float on the app's existing background

### Per-Node Label Offsets
| Index | Category | Label offset | Alignment |
|-------|----------|--------------|-----------|
| 0 | Voice (far left) | dx: -15, dy: 2 | right |
| 1 | Agent (upper-left) | dx: -8, dy: -7 | right |
| 2 | Automate (top-left) | dx: 0, dy: -11 | center |
| 3 | System (top-right) | dx: 0, dy: -11 | center |
| 4 | Customize (upper-right) | dx: 8, dy: -7 | left |
| 5 | Monitor (far right) | dx: 15, dy: 2 | left |

Labels appear on hover only (not persistent), keeping the resting state clean.

### Glitch Text Label Positions
- **MENU** — top-center, 90px above orb center
- **VOICE** — left of orb center, 70px left
- **CHAT** — right of orb center, 70px right

Each is a `<button>` with a `<GlitchText>` child that scrambles random characters before settling (720ms duration, 30ms per frame).

### Wings-Open Retreat
When chat or both wings are open (`UI_STATE_CHAT_OPEN` or `UI_STATE_BOTH_OPEN`):
- Scale: 0.85
- Filter: blur(2px)
- Opacity: 0.6
- Applied via framer-motion spring (same feel as current IrisOrb)

### isExpanded Scaling
- Scale: 1.1 when `isExpanded` (navigation level > 1)
- Applied on outer container via framer-motion spring

---

## Animation Modes (C/D/A)

### Why 3 Separate Modes, Not One Bundled Effect

The original `PrototypeOrbShellsRotating` had all 3 modes in one 438-line file with hardcoded timings. XurOrb extracts them into `animationModes.ts` as **parameter bundles** — plain JS objects with configurable constants. This allows:
- Each mode's timing to be adjusted independently
- C-pair shortened from 2.3s to 1.9s (user request)
- D-pair slightly faster decay (0.025 vs 0.022 per frame)
- A-pair unchanged (deliberate, slow bloom)

### Mode Cycling
- **Deterministic order:** C → D → A → C (not random — easier to test)
- **Triggers:** Orb click, MENU click, CHAT click
- **Does NOT trigger on:** Hex node click, VOICE label click, wake word

### Photon Burst Flash (for RadialArcNodes)
The `photonFlash` helper in `WinTransitionEngine.ts` provides the flash effect for RadialArcNodes node enter/exit:
- 0–15% of animation: brightness 1→3, scale 1→1.25
- 15–100%: brightness 3→1, scale 1.25→1

This is used by RadialArcNodes only, NOT by the orb's C/D/A modes (which have their own bloom/scale effects).

---

## Audio Pipeline Simplification

The user has experienced multiple issues with the audio pipeline (memory leaks from `warm_up()`, cmd.exe bloat, WebSocket disconnect loops). XurOrb's design includes several simplifications:

### 1. Consolidated `audio_envelope` WS Message
**Before:** `audio_level` (RMS only, during listening) + nothing during TTS
**After:** One `audio_envelope` message with `{ rms, cadence, phase }` covering both listening and speaking

### 2. Backend-Driven Cadence
**Before:** CadenceBreathDemo runs client-side spectral flux on the mic — standalone, not connected to voice command flow
**After:** Backend runs spectral flux in the STT recording loop — cadence flows through the same WS connection

### 3. TTS Audio Level Broadcast
**Before:** TTS plays server-side, frontend has no audio level data — orb is dead during speaking
**After:** TTS streaming computes RMS per chunk, broadcasts via `audio_envelope` with `phase: "speaking"`

### 4. Future: TTS Word Timing Events
**Current:** ChatWing uses a fake 200ms interval for TTS word highlighting — not synced to actual audio
**Future:** Backend sends `tts_word` WS messages with `{ word_index }` timing. ChatWing replaces the fake interval with real timing.

### 5. Future: Unified AudioSession
**Current:** STT and TTS are separate systems with separate audio handling
**Future:** A unified `AudioSession` class managing both input (mic → STT + cadence) and output (TTS → speaker + level broadcast). Larger refactor, noted as future direction.

---

## Integration with the Live App

### IrisOrb.tsx Re-export Shim
The existing `components/iris/IrisOrb.tsx` (665 lines) becomes a thin wrapper that delegates to `XurOrb`:
- The live app at `/` (Tauri shell) keeps using the `IrisOrb` import path
- The new visual transitions replace the old framer-motion ones
- The `onCallbacksReady` prop (wake word bridge) is preserved with full implementation (not a stub)
- The `handleNativeAudioResponse` callback preserves the `debug_text` feedback (5-second display)
- The old `centerLabel` / `voiceStateLabel` text logic is dropped — GlitchText labels carry that information

### ChatActivationText Deprecation
The old `components/chat-activation-text.tsx` (cycling "Tap iris for menu" / "Double-click for🎙️" / "Tap here for chat") is deleted. Its replacement, `ChatActivationGlitch`, is a one-shot hint ("tap the CHAT label to open chat") that dismisses itself when clicked (persisted in localStorage).

### Tauri Window Dragging
XurOrb uses the shared `useManualDragWindow` hook (extended with double-click support):
- Drag threshold: 12px (differentiates drag from click)
- Double-click window: 500ms
- Click vs drag vs double-click detection preserved from current IrisOrb

---

## Trade-offs & Rejected Ideas

### Why not persist the animation mode choice?
We could store the last-picked mode in localStorage. We chose not to because:
- Deterministic cycling (C→D→A→C) is predictable and testable
- localStorage adds complexity for minimal benefit
- The user sees all 3 modes within 3 clicks anyway

### Why not animate the OrbCanvas during node transitions?
The OrbCanvas already has cadence breathing and C/D/A click animations. Adding node-transition animation on top would compete for attention. The clean separation (orb animations vs node animations) gives each its moment.

### Why MENU/VOICE/CHAT and not 6 labels for all categories?
- Category nodes are for *navigating within* the app (Agent, Automate, etc.)
- MENU/VOICE/CHAT are for *primary actions* (open menu, talk, chat)
- Mixing them on the arc would make it too crowded
- The center labels act as a "command bar" always visible at level 1

### Why backend cadence instead of client-side?
- Client-side spectral flux requires microphone access (permission prompts, conflicts with STT)
- Backend already has the audio stream for STT — adding spectral flux is incremental
- TTS audio plays server-side — client can't monitor it without backend broadcast
- Consolidated WS message simplifies the communication layer

### Why not a 1-second pause between exit and enter?
- Faster interaction feels more responsive
- The animation states are reversible
- The user can re-click during animation to reverse it

---

## Open Questions for Future Iteration

1. **TTS word timing** — ChatWing uses a fake 200ms interval. Future: backend sends `tts_word` WS messages with real timing.
2. **Reduced motion** — C/D/A animations use `requestAnimationFrame`. `useReducedMotion` is imported but the fallback path needs implementation (instant opacity).
3. **Touch / mobile** — Double-click detection is mouse-only. On touch devices, a tap-and-hold could substitute.
4. **Accessibility** — GlitchText labels are `<button>`s without aria-labels. Future: add `aria-label` and keyboard navigation.
5. **Unified AudioSession** — STT and TTS as separate systems. Future: unified class managing both input and output.
6. **Theme propagation** — `glowColor` is passed as a prop, but the orb could read it directly from `useBrandColor()`. Keep as-is for testability.

---

## Success Criteria

- [ ] User can click the orb and see C/D/A animation modes cycle
- [ ] MENU/VOICE/CHAT labels always visible at level 1 idle
- [ ] MENU click reveals RadialArcNodes with 6 hex category nodes
- [ ] Hex node click goes directly to WheelView
- [ ] Double-click starts voice command
- [ ] Wake word from backend triggers voice command
- [ ] Cadence breathing active at all navigation levels
- [ ] During listening: orb breathes with speech rhythm (spectral flux)
- [ ] During speaking: orb breathes with TTS audio level (RMS)
- [ ] Whispering produces cadence beats (spectral flux detects rhythm without volume)
- [ ] `audio_envelope` WS messages arrive with `{ rms, cadence, phase }`
- [ ] Transparent background — orb and nodes float on app background
- [ ] Tauri window dragging works with double-click
- [ ] Click interception: cancel voice, close wings, navigate back
- [ ] ChatWing integration: shared voiceState + audioLevel via NavigationContext
- [ ] The live app at `/` still works (via re-export shim)
- [ ] The orb-preview page showcases XurOrb prominently
- [ ] ChatActivationText replaced with one-shot CHAT label hint
- [ ] No after-image of nodes after animation completes
