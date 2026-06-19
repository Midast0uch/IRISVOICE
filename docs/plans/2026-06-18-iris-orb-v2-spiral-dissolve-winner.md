# XurOrb — Spiral Dissolve Winner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `components/iris/IrisOrb.tsx` with a new `XurOrb.tsx` that combines:
- The **spiral variants Section 1 winner** — `PrototypeOrbShellsRotating`'s canvas shells extracted into `OrbCanvas` + its 3 click animation modes (C-opening, D-burst, A-bloom) as individually tweakable parameter bundles in `animationModes.ts`
- The **C-Random Rotate winner** (`RadialArcNodes` with 6 hex category nodes) as the level 2 menu
- **GlitchText** labels (MENU / VOICE / CHAT) always visible at level 1 idle
- **3 cosmetic click animations** (C-pair opening transition, D-pair gentle burst, A-pair big bloom) cycled randomly on orb/MENU/CHAT clicks — each mode's timing adjustable independently
- **Cadence detection** driving the orb's breath at ALL navigation levels
- Voice activation via: VOICE label click, double-click the orb, or wake word from backend
- Existing navigation wiring: single-click orb → go back, CHAT → chat-wings, hex node → WheelView

**Tech Stack:** Next.js 14 (App Router), React 18, Framer Motion, TypeScript, TailwindCSS, canvas (OrbCanvas), custom hooks (`useNavigation`, `useBrandColor`, `useUILayoutState`, `useReducedMotion`, `useManualDragWindow`).

### C-pair / D-pair / A-pair Animation Modes

The 3 modes are extracted from `PrototypeOrbShellsRotating.tsx` as **parameter bundles** — plain JS objects that define scale, bloom, speed, and decay values. Each mode affects the canvas particle rendering differently:

| Mode | Animation Type | Duration | Effect | Timing Note |
|------|---------------|----------|--------|-------------|
| **C** | Opening transition | ~2.3s (1.7s open + 0.6s settle) | Shells expand 0.7→1.05, bloom 1→1.18, speed 1→2.5→1 | **Needs shortening** |
| **D** | Gentle burst | ~0.75s decay (0.022/frame) | Pulse + 0.9× speed, 0.25 bloom | **Needs slight shortening** |
| **A** | Big bloom | ~2s decay (0.008/frame) | 0.7× speed, 0.25 bloom, deliberate duration | OK |

The C-pair opening transition timing (`OPENING_MS = 1700`, `SETTLING_MS = 600`) and D-pair decay rate (`0.022` per frame) will be extracted as configurable constants in `animationModes.ts` so each can be tweaked independently.

---

## Conventions

- **Atomic commits** — one Task = one commit.
- **Run `npx tsc --noEmit` after every edit** — must stay clean.
- **Verify in browser** — `http://localhost:3000/orb-preview` for the preview surface; the live app loads `IrisOrb` so the shim keeps it working.
- **Frequent checkpoints** — commit at the end of every Task, never bundle multiple Tasks into one commit.
- **Test before moving on** — run `npx tsc --noEmit` and confirm pages load before committing.

---

## Navigation Level Map

| Level | What's Visible | Actions |
|-------|---------------|---------|
| **1 idle** | Orb (ShellsRotating) + GlitchText (MENU/VOICE/CHAT) + cadence breathing | Click orb → back (nop at 1), double-click → voice, VOICE → toggle voice, CHAT → chat-wings, MENU → level 2 |
| **1 → glitch** | Same as 1 idle + C/D/A animation mode cycles on orb click | Same as level 1 idle |
| **2** | Orb + GlitchText + RadialArcNodes (6 hex categories) + cadence | Click orb → back to 1, click hex node → WheelView (level 3), CHAT → wings, VOICE → voice |
| **3** | WheelView with selected category + orb (smaller, cadence still active) | Click orb → back to 2 |

**Cadence is always active** — `PrototypeOrbBreathing` in D-mode runs at all levels. Voice command can activate via:
- Click VOICE glitch label
- Double-click the orb
- Wake word from backend (routed through `onCallbacksReady`)

**No ChatActivationText** — it's replaced by the GlitchText labels themselves.

---

## Task 1: Create shared utility files

**Files:**
- Create: `components/iris/utils/hexToRgba.ts`
- Create: `components/iris/radial/categories.ts`

**Step 1.1: `hexToRgba.ts`**

Extract from `components/preview/MenuMockups.tsx` line 1296:

```ts
export function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
```

**Step 1.2: `categories.ts`**

Category array matching the C-Random Rotate winner from MenuMockups — exact icons (mix of tabler + lucide), title-case labels:

```ts
import { Mic, Palette, Activity } from "lucide-react"
import { IconRobot, IconTopologyStar3, IconBasketCog } from "@tabler/icons-react"
import type { ComponentType } from "react"

export interface CategoryNode {
  id: string
  label: string
  icon: ComponentType<{ size?: number; className?: string }>
}

export const CATEGORIES: CategoryNode[] = [
  { id: "voice",     label: "Voice",     icon: Mic },
  { id: "agent",     label: "Agent",     icon: IconRobot },
  { id: "automate",  label: "Automate",  icon: IconTopologyStar3 },
  { id: "system",    label: "System",    icon: IconBasketCog },
  { id: "customize", label: "Customize", icon: Palette },
  { id: "monitor",   label: "Monitor",   icon: Activity },
]
```

Verify: `npx tsc --noEmit` → 0 errors.

Commit:
```
git add components/iris/utils/ components/iris/radial/categories.ts
git commit -m "feat(iris): add hexToRgba utility and categories constant"
```

---

## Task 2: Create `WinTransitionEngine`

**File:**
- Create: `components/iris/radial/WinTransitionEngine.ts`

**Why:** The win transition type logic (`pickRandomTransition`) and the Photon Burst flash helper (`photonFlash`) are used by the RadialArcNodes for node enter/exit animations. However, the orb's own click animations are now handled separately by `animationModes.ts` (C/D/A cycles). This file is kept for the RadialArcNodes only.

```ts
export type WinTransition = 'spiral' | 'gravity' | 'magnet'

export const WIN_DURATION_MS = 700
export const ENTER_DURATION_MS = 600

export function pickRandomTransition(current: WinTransition): WinTransition {
  const options: WinTransition[] = ['spiral', 'gravity', 'magnet']
  const filtered = options.filter(t => t !== current)
  return filtered[Math.floor(Math.random() * filtered.length)]
}

export function photonFlash(t: number): { brightness: number; scale: number } {
  if (t < 0.15) {
    const flash = t / 0.15
    return { brightness: 1 + flash * 2, scale: 1 + flash * 0.25 }
  }
  const settle = (t - 0.15) / 0.85
  return { brightness: 3 - settle * 2, scale: 1.25 - settle * 0.25 }
}
```

Verify: `npx tsc --noEmit` → 0 errors.

Commit:
```
git add components/iris/radial/WinTransitionEngine.ts
git commit -m "feat(iris): add WinTransitionEngine with photonFlash helper"
```

---

## Task 3: Create `GlitchText` component

**File:**
- Create: `components/iris/radial/GlitchText.tsx`

Same as original plan — scramble animation, uppercase monospace, glow text shadow, opacity transition. Used for MENU/VOICE/CHAT labels.

Props: `text`, `visible`, `color`, `fontSize?`, `className?`.

These labels are ALWAYS visible at level 1 idle. They disappear when navigating to level 2+ (MENU clicked) or when chat-wings open.

Commit:
```
git add components/iris/radial/GlitchText.tsx
git commit -m "feat(iris): add GlitchText scramble component"
```

---

## Task 4: Extract `HexNode` component

**File:**
- Create: `components/iris/radial/HexNode.tsx`

**Why:** The C-Random Rotate winner renders hex nodes via a local `HexNode` function inside `MenuMockups.tsx`. Extract it so both the preview page and the production `RadialArcNodes` can use it.

Copy from `MenuMockups.tsx` the `HexNode` function (around line 790-850). Keep the exact hex clip path, hover glow, icon rendering, and onClick/onHover props.

Props:
```ts
interface HexNodeProps {
  glowColor: string
  icon: ComponentType<{ size?: number; className?: string }>
  isActive: boolean
  onHover: (hovered: boolean) => void
  onClick?: () => void
}
```

Verify that `MenuMockups.tsx` still compiles (it keeps its own copy for now).

Commit:
```
git add components/iris/radial/HexNode.tsx
git commit -m "feat(iris): extract HexNode component from MenuMockups"
```

---

## Task 5: Create `RadialArcNodes` (the level 2 category menu)

**File:**
- Create: `components/iris/radial/RadialArcNodes.tsx`

**Why:** Extract the visual arc + 6 hex nodes from the C-Random Rotate winner section in `MenuMockups.tsx`. This is the level 2 menu that appears when MENU label is clicked.

Key differences from the prototype's `RadialArcBase`:
- NO `Orb` component inside — the orb is rendered separately by `XurOrb`
- NO state machine for transitions — the enter/exit transitions come from `XurOrb` via `nodeStyle` prop
- Accepts `onCategorySelect: (id: string) => void` for hex node clicks
- Accepts `isVisible: boolean` to control show/hide
- Accepts `nodeStyle: NodeStyleFn` for animated transitions
- The SVG arc, spokes, hover ring, particles are preserved exactly from the prototype

Extract from `MenuMockups.tsx` lines 580–720 approximately:
- `NodePosition` type
- `NodeStyleFn` type
- SVG arc rendering (curved path)
- Spokes (hover-only lines)
- Hover ring animation
- Particles (useParticles hook)
- HexNode × 6 with per-node labels on hover
- `extraSVG` prop preserved

Container: 246×246, same as prototype.

Commit:
```
git add components/iris/radial/RadialArcNodes.tsx
git commit -m "feat(iris): create RadialArcNodes from C-Random Rotate winner"
```

---

## Task 6: Extract `OrbCanvas` + `animationModes.ts` from `PrototypeOrbShellsRotating`

**Files:**
- Create: `components/iris/orb/OrbCanvas.tsx`
- Create: `components/iris/orb/animationModes.ts`
- Create: `components/iris/orb/C_OpeningTransition.tsx` (optional wrapper)
- Create: `components/iris/orb/D_GentleBurst.tsx` (optional wrapper)
- Create: `components/iris/orb/A_BigBloom.tsx` (optional wrapper)

**Why:** The spiral variants winner (Section 1, variant B = `PrototypeOrbShellsRotating`) has 3 click animation modes built into one file (438 lines). The user wants them as **separate, individually tweakable** parameter bundles so each mode's speed/timing can be adjusted independently.

### Step 6.1: Create `animationModes.ts`

Extract the 3 animation parameter sets from `PrototypeOrbShellsRotating.tsx`:

```ts
// components/iris/orb/animationModes.ts

export type AnimationMode = 'C' | 'D' | 'A'

// Record of which mode comes next (C → D → A → C)
export function nextAnimationMode(current: AnimationMode): AnimationMode {
  const order: AnimationMode[] = ['C', 'D', 'A']
  const idx = order.indexOf(current)
  return order[(idx + 1) % order.length]
}

// C-pair: Opening transition — shells expand outward, iris shutter text
export const C_OPENING_MS = 1400  // reduced from 1700 (user wants shorter)
export const C_SETTLING_MS = 500  // reduced from 600
export interface COpeningParams {
  shellScale: [number, number]     // [0.7, 1.05] — min to peak
  bloom: [number, number]          // [1, 1.18] — min to peak
  speedMult: [number, number]      // [1, 2.5, 1] — ramp up then down
}

// D-pair: Gentle burst — fast pulse decay
export const D_DECAY_PER_FRAME = 0.025  // was 0.022 (slightly faster)
export interface DGentleBurstParams {
  bloomAmplitude: number           // 0.25
  speedMultiplier: number          // 0.9
}

// A-pair: Big bloom — slow deliberate bloom
export const A_DECAY_PER_FRAME = 0.008
export interface ABigBloomParams {
  bloomAmplitude: number           // 0.25
  speedMultiplier: number          // 0.7
}
```

The constant values are lifted directly from `PrototypeOrbShellsRotating.tsx`:
- C: `OPENING_MS`, `SETTLING_MS`, `getTransitionState()` shellScale/bloom/speedMult
- D: `pulseRef.current` decay (`0.022` per frame), `bloomRef.current` amplitude
- A: `pulseARef.current` decay (`0.008` per frame), `bloomRef.current` amplitude

**Adjust C-pair:** The user wants C shorter. Change `C_OPENING_MS = 1400` (was 1700) and `C_SETTLING_MS = 500` (was 600).

**Adjust D-pair:** Slightly shorter. Change `D_DECAY_PER_FRAME = 0.025` (was 0.022) so it decays faster.

### Step 6.2: Create `OrbCanvas.tsx`

Extract the canvas rendering logic from `PrototypeOrbShellsRotating.tsx` into a pure visual component. This is the 3-shell particle system WITHOUT:
- Click handlers / state machine (handled by XurOrb)
- Built-in labels (handled by GlitchText)
- Animation mode cycling (handled by XurOrb via animationModes)

```tsx
interface OrbCanvasProps {
  glowColor: string
  // Cadence breathing parameters
  breathMode?: string          // 'D' for cadence-driven
  breathLevel?: number         // 0-1 audio level
  isBreathing?: boolean        // is voice active
  // Current animation mode from XurOrb
  animationMode?: AnimationMode
  animProgress?: number        // 0-1 progress of current animation
  animActive?: boolean         // is animation playing
}
```

The canvas draws:
- 3 concentric particle shells (105% / 70% / 42% scale)
- Depth-aware alpha
- Per-shell rotation speed
- Cadence-driven scale pulsing (from breathLevel)
- Animation mode effects (bloom, scale ramp, speed ramp) when `animActive`

### Step 6.3: Optional — create individual mode wrappers

If the user wants standalone testable wrappers:
```
C_OpeningTransition.tsx — wraps OrbCanvas + C animation params
D_GentleBurst.tsx       — wraps OrbCanvas + D animation params
A_BigBloom.tsx          — wraps OrbCanvas + A animation params
```

These are optional; XurOrb can pass `animationMode` directly to `OrbCanvas`.

### Step 6.4: Verify

Run: `npx tsc --noEmit` → 0 errors.
Open `http://localhost:3000/orb-preview` — ensure Section 1 spiral variants grid still loads (the original `PrototypeOrbShellsRotating.tsx` is not deleted yet).

Commit:
```
git add components/iris/orb/
git commit -m "feat(iris): extract OrbCanvas + animationModes from PrototypeOrbShellsRotating"
```

---

## Task 7: Create `ChatActivationGlitch`

**File:**
- Create: `components/iris/radial/ChatActivationGlitch.tsx`

**Why:** Replace the old `ChatActivationText` cycling hints with a one-shot "tap the CHAT label" hint that dismisses on click (persisted in localStorage).

```tsx
interface ChatActivationGlitchProps {
  uiState: UILayoutState
  navigationLevel: number
  onClick: () => void
}
```

- Only renders at level 1 idle
- Shows "tap the CHAT label to open chat" with subtle pulse animation
- Dismisses on click (localStorage flag)
- Positioned near the orb (same position as current ChatActivationText)

Commit:
```
git add components/iris/radial/ChatActivationGlitch.tsx
git commit -m "feat(iris): create one-shot CHAT label hint"
```

---

## Task 8: Extend `useManualDragWindow` for double-click

**File:**
- Modify: `hooks/useManualDragWindow.ts`

**Why:** The shared hook currently only handles single-click for window dragging. `XurOrb` needs double-click support for voice command activation.

Add to the hook params:
```ts
interface UseManualDragWindowOptions {
  elementRef: React.RefObject<HTMLElement | null>
  onClick: () => void
  onDoubleClick?: () => void     // NEW
  onDoubleClickFlash?: (show: boolean) => void  // NEW
  onPressUpdate?: (pressed: boolean) => void
}
```

Implement double-click detection (same as current IrisOrb.tsx — 500ms timer):
- Track `clickCount` and `clickTimer` refs
- On first click: start 500ms timer
- On second click within 500ms: fire `onDoubleClick` (not `onClick`)
- On timer expiry: fire `onClick`

This preserves the exact behavior from the current inline hook.

Commit:
```
git add hooks/useManualDragWindow.ts
git commit -m "feat(hooks): add double-click support to useManualDragWindow"
```

---

## Task 9: Backend cadence detection — spectral flux in STT pipeline

**Files:**
- Create: `backend/audio/cadence_detector.py`
- Modify: `backend/audio/voice_command.py`

**Why:** The current backend only sends RMS volume (`audio_level`) during listening. The orb needs speech rhythm (cadence), not just loudness. Spectral flux detects syllable beats by measuring how fast the frequency spectrum changes — whispers produce cadence beats without volume.

### Step 9.1: Create `cadence_detector.py`

A pure-Python spectral flux detector that runs on raw audio chunks:

```python
# backend/audio/cadence_detector.py
import numpy as np
from collections import deque

class CadenceDetector:
    """
    Spectral flux cadence detector.
    
    Spectral flux = sum of positive differences between consecutive FFT frames.
    High flux = spectral change = speech onset (syllable beat).
    Low flux = spectral stability = silence or sustained vowel.
    
    Produces a smoothed 0-1 envelope that tracks speech rhythm,
    independent of volume. Whispers produce cadence beats without RMS.
    """
    
    def __init__(self, sample_rate=16000, fft_size=512, hop_size=256):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.hop_size = hop_size
        self.prev_spectrum = None
        self.envelope = 0.0          # smoothed output (0-1)
        self.smoothing = 0.85        # EMA smoothing factor
        self.flux_history = deque(maxlen=10)  # for normalization
    
    def process(self, audio_chunk: np.ndarray) -> float:
        """
        Process a chunk of float32 audio samples.
        Returns cadence level 0-1.
        """
        if len(audio_chunk) < self.hop_size:
            return self.envelope
        
        # Apply Hann window
        windowed = audio_chunk[:self.fft_size] * np.hanning(self.fft_size)
        
        # Compute FFT (magnitude spectrum)
        spectrum = np.abs(np.fft.rfft(windowed))
        
        if self.prev_spectrum is None:
            self.prev_spectrum = spectrum
            return 0.0
        
        # Spectral flux: sum of positive differences
        diff = spectrum - self.prev_spectrum
        flux = np.sum(np.maximum(diff, 0.0))
        self.prev_spectrum = spectrum.copy()
        
        # Normalize using rolling history
        self.flux_history.append(flux)
        max_flux = max(self.flux_history) if self.flux_history else 1.0
        normalized = min(flux / (max_flux + 1e-6), 1.0)
        
        # Smooth with exponential moving average
        self.envelope = self.smoothing * self.envelope + (1 - self.smoothing) * normalized
        
        return self.envelope
    
    def reset(self):
        """Reset state when recording starts/stops."""
        self.prev_spectrum = None
        self.envelope = 0.0
        self.flux_history.clear()
```

### Step 9.2: Integrate into `voice_command.py`

In the audio recording loop (where `audio_level` WS messages are currently sent), add cadence detection:

```python
# In voice_command.py, in the recording loop:
from backend.audio.cadence_detector import CadenceDetector

class VoiceCommandHandler:
    def __init__(self, ...):
        # ... existing init ...
        self.cadence_detector = CadenceDetector(sample_rate=16000)
    
    async def _record_and_stream(self, ws):
        self.cadence_detector.reset()
        # ... existing recording loop ...
        for chunk in audio_stream:
            audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Existing: compute RMS volume
            rms = float(np.sqrt(np.mean(audio_np ** 2)))
            audio_level = min(rms * 3.0, 1.0)  # same scaling as current
            
            # NEW: compute cadence
            cadence_level = self.cadence_detector.process(audio_np)
            
            # Send consolidated audio envelope
            await ws.send_json({
                "type": "audio_envelope",
                "rms": audio_level,
                "cadence": cadence_level,
                "phase": "listening"
            })
```

**Key change:** Replace the existing `audio_level` WS message with a new `audio_envelope` message that carries BOTH rms and cadence. This is the simplification — one message instead of two, with richer data.

### Step 9.3: Backward compatibility

The frontend currently listens for `audio_level` messages. During the transition:
- Keep sending `audio_level` messages (for old IrisOrb.tsx)
- ALSO send `audio_envelope` messages (for XurOrb)
- Once XurOrb is fully wired, remove the old `audio_level` messages

Commit:
```
git add backend/audio/cadence_detector.py backend/audio/voice_command.py
git commit -m "feat(backend): add spectral flux cadence detection to STT pipeline"
```

---

## Task 10: Backend TTS audio level monitoring

**Files:**
- Modify: `backend/agent/tts.py` (or wherever TTSManager lives)
- Modify: `backend/audio/voice_command.py` (or the WS broadcast path)

**Why:** During TTS playback (voiceState === "speaking"), the orb needs to breathe with the TTS audio. Currently the backend plays TTS audio server-side and sends NO audio level data to the frontend. The orb is dead during speaking.

### Step 10.1: Compute RMS during TTS streaming

In `TTSManager.synthesize_stream()` (which yields float32 audio chunks), compute RMS per chunk and broadcast it:

```python
# In tts.py, in synthesize_stream():
import numpy as np

async def synthesize_stream(self, text, ws=None):
    # ... existing streaming logic ...
    for chunk in audio_chunks:
        # Existing: yield chunk to AudioEngine for playback
        yield chunk
        
        # NEW: compute RMS and broadcast to frontend
        if ws is not None:
            audio_np = np.frombuffer(chunk, dtype=np.float32)
            rms = float(np.sqrt(np.mean(audio_np ** 2)))
            tts_level = min(rms * 2.0, 1.0)
            
            await ws.send_json({
                "type": "audio_envelope",
                "rms": tts_level,
                "cadence": tts_level,  # TTS cadence = RMS (no spectral flux needed for playback)
                "phase": "speaking"
            })
```

### Step 10.2: Wire the WebSocket connection

The TTSManager needs access to the WebSocket connection to broadcast. Two approaches:

**Approach A (simpler):** Pass `ws` into `synthesize_stream()` from the voice command handler that already has the WS connection.

**Approach B (cleaner):** Use a broadcast bus — TTSManager publishes to a pub/sub channel, the WS handler subscribes and forwards to the client.

Choose **Approach A** for now — it's the least invasive change. The voice command handler already has `ws` and calls TTSManager.

### Step 10.3: Stop signal

When TTS finishes, send a final envelope with zero values:

```python
await ws.send_json({
    "type": "audio_envelope",
    "rms": 0.0,
    "cadence": 0.0,
    "phase": "idle"
})
```

This tells the frontend to stop breathing.

Commit:
```
git add backend/agent/tts.py
git commit -m "feat(backend): broadcast TTS audio level via audio_envelope WS messages"
```

---

## Task 11: Update NavigationContext for cadence + TTS audio

**Files:**
- Modify: `contexts/NavigationContext.tsx`
- Modify: `hooks/useIRISWebSocket.ts`

**Why:** The frontend needs to receive `audio_envelope` WS messages and expose `cadenceLevel` and `ttsAudioLevel` to components. Currently only `audioLevel` (RMS) is exposed.

### Step 11.1: Add new state to NavigationContext

```ts
// In NavigationContext state:
const [audioLevel, setAudioLevel] = useState(0)       // existing — RMS during listening
const [cadenceLevel, setCadenceLevel] = useState(0)    // NEW — spectral flux during listening
const [ttsAudioLevel, setTtsAudioLevel] = useState(0)  // NEW — RMS during TTS speaking
const [audioPhase, setAudioPhase] = useState<"listening" | "speaking" | "idle">("idle")  // NEW
```

### Step 11.2: Handle `audio_envelope` WS messages

In `useIRISWebSocket.ts`, add a handler for the new message type:

```ts
case "audio_envelope": {
  const { rms, cadence, phase } = message
  setAudioPhase(phase)
  if (phase === "listening") {
    setAudioLevel(rms)
    setCadenceLevel(cadence)
    setTtsAudioLevel(0)
  } else if (phase === "speaking") {
    setTtsAudioLevel(rms)
    setCadenceLevel(rms)  // TTS cadence = RMS (no spectral flux for playback)
    setAudioLevel(0)
  } else {
    setAudioLevel(0)
    setCadenceLevel(0)
    setTtsAudioLevel(0)
  }
  break
}
```

### Step 11.3: Keep backward compat for `audio_level`

Keep the existing `audio_level` handler for now (old IrisOrb.tsx still uses it). Once the shim is fully replaced, remove it.

### Step 11.4: Expose in context value

```ts
const contextValue = {
  // ... existing ...
  audioLevel,          // existing
  cadenceLevel,        // NEW
  ttsAudioLevel,       // NEW
  audioPhase,          // NEW
  // ... existing ...
}
```

Commit:
```
git add contexts/NavigationContext.tsx hooks/useIRISWebSocket.ts
git commit -m "feat(frontend): handle audio_envelope WS messages with cadence + TTS level"
```

---

## Task 12: Create `useCadenceDetection` hook

**File:**
- Create: `hooks/useCadenceDetection.ts`

**Why:** Centralize the voice state → cadence parameter mapping. XurOrb uses this hook to get the right `breathMode`, `breathLevel`, and `isBreathing` values for OrbCanvas based on the current voice state.

### Voice state → cadence mapping:

| voiceState | Cadence Source | breathMode | breathLevel | isBreathing |
|------------|---------------|------------|-------------|-------------|
| idle | None | "D" | 0 | false |
| listening | Backend spectral flux (cadenceLevel) | "D" | cadenceLevel | true |
| processing_conversation | Gentle pulse | "D" | 0.3 | true |
| processing_tool | Gentle pulse | "D" | 0.2 | true |
| speaking | Backend TTS RMS (ttsAudioLevel) | "D" | ttsAudioLevel | true |
| error | None | "D" | 0 | false |

### Hook implementation:

```ts
// hooks/useCadenceDetection.ts
import { useNavigation } from "@/contexts/NavigationContext"

export interface CadenceData {
  breathMode: string       // always "D" (the winner)
  breathLevel: number      // 0-1
  isBreathing: boolean
}

export function useCadenceDetection(): CadenceData {
  const { voiceState, cadenceLevel, ttsAudioLevel } = useNavigation()
  
  switch (voiceState) {
    case "listening":
      return { breathMode: "D", breathLevel: cadenceLevel, isBreathing: true }
    case "speaking":
      return { breathMode: "D", breathLevel: ttsAudioLevel, isBreathing: true }
    case "processing_conversation":
      return { breathMode: "D", breathLevel: 0.3, isBreathing: true }
    case "processing_tool":
      return { breathMode: "D", breathLevel: 0.2, isBreathing: true }
    case "error":
    case "idle":
    default:
      return { breathMode: "D", breathLevel: 0, isBreathing: false }
  }
}
```

### Client-side fallback (dev mode without backend):

If the backend isn't running, `cadenceLevel` and `ttsAudioLevel` will always be 0. For dev mode, add an optional client-side spectral flux fallback that activates when `audioPhase === "idle"` but `voiceState === "listening"`:

```ts
// Optional: if cadenceLevel is 0 but voiceState is listening, 
// fall back to audioLevel (RMS) as a proxy for cadence
case "listening":
  const level = cadenceLevel > 0 ? cadenceLevel : audioLevel * 0.7
  return { breathMode: "D", breathLevel: level, isBreathing: true }
```

Commit:
```
git add hooks/useCadenceDetection.ts
git commit -m "feat(hooks): add useCadenceDetection hook for voice state to cadence mapping"
```

---

## Task 13: Communication Layer — WS Message Type Reference

**This is a documentation task — no code changes.**

### Inbound WS messages (backend → frontend):

| Message Type | Payload | Purpose | Consumer |
|-------------|---------|---------|----------|
| `audio_envelope` | `{ rms, cadence, phase }` | Audio level + cadence during listening/speaking | NavigationContext → useCadenceDetection → XurOrb |
| `audio_level` | `{ level }` | Legacy RMS only (backward compat) | Old IrisOrb.tsx (remove after migration) |
| `wake_detected` | `{}` | Wake word heard | XurOrb via onCallbacksReady → startVoiceCommand |
| `listening_state` | `{ state }` | Voice state change | NavigationContext → voiceState |
| `text_response` | `{ text, sender, thinking, suggestions }` | Chat message from backend | NavigationContext → lastTextResponse → ChatWing |
| `chat_typing` | `{ typing }` | Backend is generating response | NavigationContext → isChatTyping → ChatWing |
| `tts_word` | `{ word_index }` | TTS word timing (if backend supports it) | ChatWing (replaces fake 200ms interval) |
| `native_audio_response` | `{ debug_text }` | Debug feedback from native audio | XurOrb via onCallbacksReady |

### Outbound WS messages (frontend → backend):

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

### REST endpoints:

| Endpoint | Method | Purpose | Caller |
|----------|--------|---------|--------|
| `/api/chat` | POST | Primary chat message (reliable, no WS dependency) | ChatWing.handleSendMessage |
| `/auth/session` | GET | Session token (future) | Launcher handoff |

### XurOrb's direct dependencies on the communication layer:

1. **Reads from NavigationContext:** `voiceState`, `audioLevel`, `cadenceLevel`, `ttsAudioLevel`, `audioPhase`
2. **Calls on NavigationContext:** `startVoiceCommand()`, `endVoiceCommand()`, `cancelVoiceCommand()`, `dispatch()`, `setMainView()`
3. **Receives via onCallbacksReady:** `handleWakeDetected` (wake word), `handleNativeAudioResponse` (debug text)
4. **Does NOT directly handle:** `lastTextResponse`, `isChatTyping`, `sendMessage` — those are ChatWing's concern

### ChatWing's direct dependencies:

1. **Reads from NavigationContext:** `voiceState`, `audioLevel`, `lastTextResponse`, `isChatTyping`, `clearChat`, `fieldErrors`
2. **Calls on NavigationContext:** `sendMessage()` (for WS messages)
3. **REST:** `POST /api/chat` (primary path), WS `text_message` (fallback)
4. **Shares with XurOrb:** `voiceState` (both breathe/react to it), `audioLevel` (both use it)

---

## Task 14: Build `XurOrb` — the main component

**File:**
- Create: `components/iris/XurOrb.tsx`
- Modify: `components/iris/types.ts` (add `XurOrbProps`)

**Why:** The single replacement for `IrisOrb.tsx`. Composes all sub-components.

### Props (`types.ts`):

```ts
import type { WinTransition } from "./radial/WinTransitionEngine"

export interface XurOrbProps {
  isExpanded: boolean
  onClick: () => void
  onDoubleClick: () => void
  centerLabel?: string       // kept for shim compat, unused in XurOrb
  size?: number
  wakeFlash: boolean
  glowColor?: string
  uiState?: UILayoutState
  onCategorySelect?: (categoryId: string) => void
  onMenuClick?: () => void
  onChatClick?: () => void
  onCallbacksReady?: (callbacks: {
    handleWakeDetected: () => void
    handleNativeAudioResponse: (payload: Record<string, unknown>) => void
  }) => void
}
```

**Note:** Cadence data (`breathMode`, `breathLevel`, `isBreathing`) is NOT passed as props. XurOrb reads it internally via the `useCadenceDetection()` hook, which pulls `voiceState`, `cadenceLevel`, and `ttsAudioLevel` from `useNavigation()`. This keeps the prop interface clean and ensures cadence is always driven by the live backend connection.

### Component structure:

```
XurOrb
  Outer container (handles Tauri drag, click intercept, double-click, wings-open blur/opacity)

  ┌─────────────────────────────────────────┐
  │  RadialArcNodes                          │  ← level 2 only (visible when menuClicked)
  │    (SVG arc, HexNode×6, particles)       │  ← no Orb inside (XurOrb owns it)
  │                                          │
  │  ┌─────────────────────────────────────┐ │
  │  │  OrbCanvas (always visible)          │ │
  │  │    canvas shells, particles          │ │
  │  │    cadence breathing active          │ │
  │  │    current animation mode applied    │ │
  │  └─────────────────────────────────────┘ │
  │                                          │
  │    GlitchText × 3                        │  ← always visible at level 1 idle
  │      MENU / VOICE / CHAT                 │  ← hidden at level 2+ or when wings open
  │                                          │
  └─────────────────────────────────────────┘
```

### State machine:

```ts
const [animationMode, setAnimationMode] = useState<AnimationMode>('C')  // C → D → A → C
const [animActive, setAnimActive] = useState(false)                      // is animation playing
const [animProgress, setAnimProgress] = useState(0)                      // 0→1 progress
const [menuOpen, setMenuOpen] = useState(false)                          // level 2: radial arc visible
const [chatOpen, setChatOpen] = useState(false)                          // chat-wings state
```

### Click handlers:

```ts
// Orb click — cycle animation mode + do navigation
const handleOrbClick = useCallback(() => {
  // Interception: if voice active → cancel voice
  if (isVoiceActive) { cancelVoiceCommand(); return }
  // If wings open → close
  if (isWingsOpen) { onClick(); return }
  // Cycle animation mode
  setAnimationMode(cur => nextAnimationMode(cur))
  setAnimActive(true)
  // Animate progress 0→1 with requestAnimationFrame
  animateProgress(ANIM_DURATION_MS[animationMode], () => setAnimActive(false))
  // Navigation: go back if level > 1
  onClick()
}, [...])

// Glitch label handlers — also cycle animation mode
const handleMenuClick = useCallback(() => {
  setAnimationMode(cur => nextAnimationMode(cur))
  setAnimActive(true)
  animateProgress(ANIM_DURATION_MS[animationMode], () => setAnimActive(false))
  setMenuOpen(true)
  dispatch({ type: "EXPAND_TO_MAIN" })
}, [...])

const handleVoiceClick = useCallback(() => {
  isVoiceActive ? endVoiceCommand() : startVoiceCommand()
}, [...])

const handleChatClick = useCallback(() => {
  setAnimationMode(cur => nextAnimationMode(cur))
  setAnimActive(true)
  animateProgress(ANIM_DURATION_MS[animationMode], () => setAnimActive(false))
  setChatOpen(true)
  setMainView("chat")
}, [...])

// Hex node click — goes directly to WheelView, no animation
const handleCategorySelect = useCallback((categoryId: string) => {
  onCategorySelect?.(categoryId)
  dispatch({ type: "EXPAND_TO_MAIN" })  // to level 3 with selectedMain
}, [])
```

The `ANIM_DURATION_MS` map reads from the values in `animationModes.ts`:
```ts
const ANIM_DURATION_MS = { C: C_OPENING_MS + C_SETTLING_MS, D: 750, A: 2000 }
```

### Visual details:

- **isExpanded**: `scale: isExpanded ? 1.1 : 1` on outer container (framer-motion spring)
- **isWingsOpen**: `scale: 0.85, filter: blur(2px), opacity: 0.6` via framer-motion spring (same as current IrisOrb)
- **wakeFlash / doubleClickFlash**: white overlay flash (same as current)
- **useReducedMotion**: skip requestAnimationFrame animations, instant transitions
- **Cadence data**: read internally via `useCadenceDetection()` hook → feeds `breathMode`, `breathLevel`, `isBreathing` to OrbCanvas. NOT passed as props.
- **voiceState**: read from `useNavigation()` — drives click interception (cancel voice if active) and cadence mapping
- **audioLevel**: read from `useNavigation()` — used for click interception and fallback cadence
- **centerLabel**: not rendered (glitch labels carry this info)

Commit:
```
git add components/iris/types.ts components/iris/XurOrb.tsx
git commit -m "feat(iris): create XurOrb with full navigation wiring"
```

---

## Task 15: Wire `onCallbacksReady` wake word bridge

**Files:**
- Modify: `components/iris/XurOrb.tsx`

Add the wake word registration. The backend calls `handleWakeDetected` when the wake word is heard. This must set up refs that stay stable across re-renders (same pattern as current IrisOrb.tsx).

```ts
const isListeningRef = useRef(false)
isListeningRef.current = isListening

const handleWakeDetected = useCallback(() => {
  if (isListeningRef.current) return
  startVoiceCommand()
}, [startVoiceCommand])

const handleNativeAudioResponse = useCallback((payload: Record<string, unknown>) => {
  if (payload.debug_text && typeof payload.debug_text === 'string') {
    // Set temporary feedback display (cadence overlay)
    setFeedbackMessage(payload.debug_text)
    setTimeout(() => setFeedbackMessage(""), 5000)
  }
}, [])

useEffect(() => {
  onCallbacksReady?.({
    handleWakeDetected,
    handleNativeAudioResponse
  })
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [])
```

Commit:
```
git add components/iris/XurOrb.tsx
git commit -m "feat(iris): wire wake word bridge in XurOrb"
```

---

## Task 16: Build the re-export shim

**File:**
- Modify: `components/iris/IrisOrb.tsx`

Convert `IrisOrb.tsx` to a thin shim that wraps `XurOrb`. Keep the `IrisOrbProps` interface unchanged so `app/page.tsx` doesn't break. The shim maps old props to new props:

```tsx
"use client"
import { XurOrb } from "./XurOrb"
import type { IrisOrbProps } from "./types"

export function IrisOrb(props: IrisOrbProps) {
  // Map props, wire onCallbacksReady, set up voice state
  return <XurOrb { ...mappedProps } />
}
```

Key mappings:
- `onCallbacksReady` → passed through to XurOrb (wake word bridge)
- `centerLabel` → unused in v2 (mapped to empty)
- `wakeFlash` → combined with internal doubleClickFlash
- `uiState` → used for wings-open state
- `audioLevel` → read from useNavigation, passed to XurOrb
- `voiceState` → mapped to cadence breath params (breathMode/breathLevel/isBreathing)

**Critical: The shim must intercept `handleSingleClick` / `handleDoubleClick` the same way the current IrisOrb does.**

Verify the live app at `/` still works:
- Orb renders
- Single click navigates
- Double click starts voice
- Wake word triggers voice
- No console errors

Commit:
```
git add components/iris/IrisOrb.tsx
git commit -m "refactor(iris): convert IrisOrb.tsx to re-export shim wrapping XurOrb"
```

---

## Task 17: Delete `ChatActivationText`, add `ChatActivationGlitch` to page.tsx

**Files:**
- Delete: `components/chat-activation-text.tsx`
- Modify: `app/page.tsx`

Find all imports of `ChatActivationText` in `app/page.tsx`. Replace with `ChatActivationGlitch` from `components/iris/radial/ChatActivationGlitch.tsx`. Same position, same animations, same click → open chat behavior.

The old cycling texts ("Tap iris for menu", etc.) are gone — replaced by the GlitchText labels on the orb itself.

Verify: `npx tsc --noEmit` → 0 errors.

Commit:
```
git add components/chat-activation-text.tsx app/page.tsx
git commit -m "refactor(iris): replace ChatActivationText with one-shot CHAT label hint"
```

---

## Task 18: Add `XurOrb` to the orb-preview page

**File:**
- Modify: `app/orb-preview/page.tsx`

Add a featured section showing `XurOrb` at the top of the preview page (above the spiral variants grid). This is the production prototype section:

```tsx
import { XurOrb } from "@/components/iris/XurOrb"

// ... inside OrbPreviewPage:

<section className="flex flex-col items-center gap-6 mt-8">
  <h2 className="text-2xl font-bold tracking-wide text-white">
    IRIS Orb v2 — Production Prototype
  </h2>
  <p className="text-sm text-white/60 max-w-md text-center">
    XurOrb: OrbCanvas visual + GlitchText labels + cadence breathing.
    Click orb to cycle C/D/A animation modes. Click MENU for radial arc hex nodes.
    Click CHAT to open chat-wings. Double-click for voice.
  </p>
  <div className="p-6 rounded-2xl border-2 border-yellow-400/40 bg-black/40">
    <XurOrb
      isExpanded={true}
      onClick={() => {}}
      onDoubleClick={() => {}}
      centerLabel=""
      glowColor="#00d4ff"
      wakeFlash={false}
    />
  </div>
</section>
```

Also add a "Section 6: Radial Arc Nodes (Level 2) — C-Random Rotate Winner" below the MenuMockups section, so the radial arc can be previewed in isolation:

```tsx
import { RadialArcNodes } from "@/components/iris/radial/RadialArcNodes"

// After the MenuMockups section:
<section className="flex flex-col items-center gap-4 mt-12">
  <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
    Radial Arc Nodes — Level 2 Category Menu (C-Random Rotate)
  </h2>
  <div className="p-6 rounded-2xl border border-white/10 bg-black/20">
    <RadialArcNodes
      glowColor={theme.color}
      isVisible={true}
      onCategorySelect={(id) => console.log("selected", id)}
    />
  </div>
</section>
```

Verify: Open `http://localhost:3000/orb-preview` — both XurOrb and RadialArcNodes render.

Commit:
```
git add app/orb-preview/page.tsx
git commit -m "feat(orb-preview): add XurOrb and RadialArcNodes preview sections"
```

---

## Task 19: End-to-end visual verification

**Files:** None (verification only)

### Level 1 idle:
- [ ] Orb (OrbCanvas) visible with cadence breathing
- [ ] GlitchText labels (MENU/VOICE/CHAT) visible around the orb
- [ ] No hex nodes visible
- [ ] C/D/A animation mode cycles on orb click (C-opening, D-burst, A-bloom)
- [ ] Animation mode cycles C→D→A→C on consecutive clicks
- [ ] Each mode's timing independently adjustable via `animationModes.ts` constants

### Level 2 (click MENU):
- [ ] RadialArcNodes appear with 6 hex category nodes
- [ ] Nodes have correct icons (tabler + lucide mix)
- [ ] Hover effects work on each node
- [ ] C/D/A animation cycles on MENU click

### Level 3 (click category node):
- [ ] Navigates to WheelView with selected category
- [ ] No animation on category click — goes directly

### Voice:
- [ ] Click VOICE → toggles voice command
- [ ] Double-click orb → toggles voice command
- [ ] Wake word from backend → triggers voice command
- [ ] Cadence breathing active at all levels
- [ ] Voice state labels don't appear (cadence drives the orb)

### Cadence + Backend Audio:
- [ ] During listening (STT): orb breathes with speech rhythm (spectral flux from backend)
- [ ] During speaking (TTS): orb breathes with TTS audio level (RMS from backend)
- [ ] During processing: orb gently pulses (0.2-0.3 level)
- [ ] During idle: orb is static (no breathing)
- [ ] Whispering produces cadence beats (spectral flux detects rhythm without volume)
- [ ] `audio_envelope` WS messages arrive with `{ rms, cadence, phase }` payload
- [ ] `cadenceLevel` in NavigationContext updates during listening
- [ ] `ttsAudioLevel` in NavigationContext updates during speaking
- [ ] `useCadenceDetection` hook returns correct breathMode/breathLevel/isBreathing for each voiceState

### ChatWing Integration:
- [ ] Click CHAT → opens chat-wings (same flow as original)
- [ ] ChatWing and XurOrb share voiceState via NavigationContext
- [ ] ChatWing and XurOrb share audioLevel via NavigationContext
- [ ] TTS word highlighting in ChatWing works (client-side 200ms fallback or backend tts_word events)
- [ ] Chat messages flow: REST /api/chat primary, WS text_message fallback
- [ ] No duplicate message processing (deduplication via lastProcessedResponseRef)

### CHAT:
- [ ] Click CHAT → opens chat-wings
- [ ] C/D/A animation cycles on CHAT click

### Navigation:
- [ ] Single-click orb → navigates back (if level > 1)
- [ ] Single-click orb (voice active) → cancels voice
- [ ] Single-click orb (wings open) → closes wings

### Tauri:
- [ ] Window dragging works
- [ ] Double-click for voice doesn't conflict with drag

### Shim:
- [ ] Live app at `/` loads with same prop interface
- [ ] No console errors
- [ ] Wake word triggers voice

### Accessibility:
- [ ] C/D/A animations fall back to instant opacity when `prefersReducedMotion`

---

## Task 20: Final commit and summary

### Verify no dangling references:
```bash
grep -r "ChatActivationText" components/ app/
grep -r "from '@/components/chat-activation-text'" .
```

Expected: 0 results.

### Final type check:
```bash
npx tsc --noEmit
```

Expected: 0 errors.

### Final commit:
```bash
git add -A
git diff --cached --stat
git commit -m "feat(iris): XurOrb — Spiral Dissolve winner with backend cadence detection

- XurOrb: composes OrbCanvas + GlitchText + RadialArcNodes
- Level 1: OrbCanvas + GlitchText (MENU/VOICE/CHAT) + cadence breathing, always active
- Level 2: MENU click reveals RadialArcNodes with 6 hex category nodes
- Level 3: hex node click goes directly to WheelView
- 3 animation modes (C-opening, D-burst, A-bloom) cycle on orb/MENU/CHAT clicks — each adjustable via animationModes.ts constants
- Backend cadence detection: spectral flux in STT pipeline (cadence_detector.py)
- Backend TTS audio level: RMS monitoring during TTS streaming
- Consolidated audio_envelope WS message: { rms, cadence, phase }
- useCadenceDetection hook: maps voiceState → breathMode/breathLevel/isBreathing
- NavigationContext: exposes cadenceLevel, ttsAudioLevel, audioPhase
- Voice activation: VOICE label, double-click, wake word (onCallbacksReady)
- Click interception: cancel voice, close wings, navigate back
- Tauri window dragging with double-click support (extended useManualDragWindow)
- ChatActivationText replaced with one-shot CHAT label hint
- HexToRgba utility, categories constant with tabler+lucide icons
- IrisOrb.tsx re-export shim — no live app breakage
- ChatWing integration: shared voiceState + audioLevel via NavigationContext"
```

---

## Rollback Plan

Each Task is its own commit. If a specific Task breaks the build:
1. `git revert <commit-hash>` to roll back that Task
2. The preview page keeps its own copies of prototype components, so the preview page is never broken by extraction commits

If Tasks 16-17 (shim/page.tsx) break the live app:
1. `git revert` the shim commit
2. The old `IrisOrb.tsx` is restored via reversion

---

## Audio Pipeline Simplification Notes

The user has experienced multiple issues with the audio pipeline (memory leaks from warm_up, cmd.exe bloat, WebSocket disconnect loops). The plan is open to simplifying the pipeline. Key simplifications in this plan:

### 1. Consolidated `audio_envelope` WS message
**Before:** Two separate messages (`audio_level` during listening, nothing during TTS)
**After:** One message type `audio_envelope` with `{ rms, cadence, phase }` covering both listening and speaking phases. Simpler parsing, richer data, fewer message types.

### 2. Backend-driven cadence (no client-side spectral flux in production)
**Before:** CadenceBreathDemo runs client-side spectral flux on the mic — standalone, not connected to voice command flow
**After:** Backend runs spectral flux in the STT recording loop — cadence data flows through the same WS connection as everything else. Client-side fallback only for dev mode without backend.

### 3. TTS audio level broadcast
**Before:** TTS plays server-side, frontend has no idea what audio level is — orb is dead during speaking
**After:** TTS streaming computes RMS per chunk, broadcasts via `audio_envelope` with `phase: "speaking"`. Orb breathes with TTS output.

### 4. Future: TTS word timing events
**Current:** ChatWing uses a fake 200ms interval for TTS word highlighting — not synced to actual audio
**Future:** Backend can send `tts_word` WS messages with `{ word_index }` timing. ChatWing replaces the fake interval with real timing. This is NOT in the current plan but is a natural follow-up.

### 5. Future: Unified audio session
**Current:** STT and TTS are separate systems with separate audio handling
**Future:** A unified `AudioSession` class that manages both input (mic → STT + cadence) and output (TTS → speaker + level broadcast). This would simplify the codebase significantly but is a larger refactor. Not in the current plan — noted as a future direction.

---

## Open Questions / Clarifications Made

1. **Level 1 idle has GlitchText always visible** — MENU/VOICE/CHAT labels are the default state, not a hidden mode
2. **3 animation modes, NOT a single bundled effect** — C-pair (opening transition), D-pair (gentle burst), A-pair (big bloom). Each has its own timing constants in `animationModes.ts` for independent adjustment. C-pair and D-pair need shortening from original prototype values.
3. **RadialArcNodes only appear at level 2** — when MENU is clicked. Not visible at level 1 idle.
4. **Cadence is always active** — across all navigation levels. Voice can activate via VOICE label, double-click, or wake word at any level.
5. **Category node click → WheelView directly** — no intermediate hexagonal control center. The C-Random Rotate winner's radial arc IS the category selector.
6. **Hex node click does NOT fire animation** — only navigation actions (orb click, MENU click, CHAT click) cycle the C/D/A mode.
7. **Category icons use the winner's exact set** — mix of tabler (IconRobot, IconTopologyStar3, IconBasketCog) and lucide (Mic, Palette, Activity).
8. **C-pair and D-pair timing adjustments** — C-pair: OPENING_MS from 1700→1400, SETTLING_MS from 600→500. D-pair: DECAY_PER_FRAME from 0.022→0.025.
9. **Component renamed IrisOrbV2 → XurOrb** — all files, props, types, and references use XurOrb naming.
10. **Backend cadence detection (Option B)** — spectral flux runs in the backend STT pipeline, not client-side. Cadence data flows through WS as part of the `audio_envelope` message.
11. **TTS audio level broadcast** — backend computes RMS during TTS streaming and broadcasts via `audio_envelope` with `phase: "speaking"`. Orb breathes with TTS output.
12. **Consolidated audio_envelope WS message** — replaces the old `audio_level` message. Carries `{ rms, cadence, phase }` in one message for both listening and speaking.
13. **useCadenceDetection hook** — maps voiceState → breathMode/breathLevel/isBreathing. XurOrb reads cadence internally via this hook, not via props.
14. **Audio pipeline open to simplification** — user has experienced multiple audio pipeline issues. Plan includes consolidated WS messages and backend cadence. Future: unified AudioSession class, TTS word timing events.
15. **ChatWing integration** — XurOrb and ChatWing share voiceState and audioLevel via NavigationContext. XurOrb does NOT handle lastTextResponse or sendMessage — those are ChatWing's concern. The only direct backend→XurOrb callback is onCallbacksReady (wake word + debug text).
16. **Hex Pattern Surface replaces DualRingMechanism** — the ★ WINNER variant from `WheelRingStyles.tsx` becomes the production ring mechanism. Same props, same functionalities, same use cases as the current `DualRingMechanism.tsx`. Design doc at `docs/Design/Hex-Pattern-Wheel-View.md`.

---

## Task 21: Create `HexPatternRingMechanism` — production replacement for DualRingMechanism

**Files:**
- Create: `components/wheel-view/HexPatternRingMechanism.tsx`

**Why:** The Hex Pattern Surface variant from `components/preview/WheelRingStyles.tsx` won the ring surface style comparison. It combines a honeycomb SVG pattern texture overlay with neon edge glow on interactive arc segments. This task extracts the winning variant into a production component that is a **drop-in replacement** for `DualRingMechanism.tsx` — same props interface, same functionalities, same use cases.

### Props (identical to DualRingMechanism):

```ts
interface HexPatternRingMechanismProps {
  items: Card[]
  selectedIndex: number
  onSelect: (index: number) => void
  glowColor: string
  basePlateColor?: string
  orbSize: number
  confirmSpinning?: boolean
  isVoiceActive?: boolean
  voiceIntensity?: number
}
```

### What carries over from DualRingMechanism (functionalities & use cases):

1. **2-ring distribution logic** — items split 50/50 across outer and inner rings (`splitPoint = Math.ceil(items.length / 2)`)
2. **Spring physics rotation** — selected segment centers at 12 o'clock via `framer-motion` spring (`stiffness: 80, damping: 16`)
3. **Confirm spin animation** — counter-rotation on confirm (`outerRotation + 360`, `innerRotation - 360`)
4. **Arc path generation** — `polarToCartesian` + `generateArcPath` for segment paths
5. **Segment text along arc** — `<textPath>` rendering with uppercase labels
6. **Voice aura** — dynamic background aura that pulses with `isVoiceActive` and `voiceIntensity`
7. **Base plate + depth groove** — industrial foundation layers
8. **Liquid metal structural frame** — decorative outer frame at `outerRadius + 30`
9. **Structural counter-beams** — 4 beams (2 CCW + 2 CW) at `outerRadius + 30` and `outerRadius + 28`
10. **Barrier kinetic glider** — framer-motion dashed ring at `outerRadius + 23`, 8s CW (faster than ticks)
11. **Orbital ticks** — 12 dual-layer ticks (bloom + core) via CSS `ring-outer-anim` at 20s CW
12. **Gap kinetic glider** — CSS `ring-middle-anim` dashed ring + framer-motion CCW beam at 3.5s
13. **Core kinetic glider** — CSS `ring-inner-anim` dashed ring + framer-motion CW beam at 4s
14. **Core shimmer** — pulsing white halo at `orbSize * 0.11`
15. **Particle chase relay** — dual particle "chase" at `outerRadius + 29` (ENERGY_CYCLE synced)
16. **Structural energy circuit** — rotating "power spark" at `outerRadius + 29`

### What changes (Hex Pattern Surface aesthetic):

The **interactive segment rendering** changes from liquid metal to hex pattern surface:

| Layer | DualRingMechanism (old) | HexPatternRingMechanism (new) |
|-------|------------------------|-------------------------------|
| Segment body stroke | `url(#liquid-metal-gradient)` + `url(#muted-metal-gradient)` | `url(#hex-active)` / `url(#hex-idle)` gradient |
| Segment surface texture | None (smooth metal) | Honeycomb SVG `<pattern>` overlay (opacity 0.22 idle, 0.4 selected) |
| Segment edge | Micro edge highlight (0.5px) | Neon edge outline (glowColor, 1.5px selected, 0.75px idle, with drop-shadow) |
| Segment glow background | `hexToRgba(glowColor, 0.12)` blur | Same — preserved |
| Segment filter | `url(#liquid-metal-sheen)` specular | None — hex pattern provides visual interest |

### SVG defs required:

```xml
<linearGradient id="hex-active"> — glowColor tint + dark center
<linearGradient id="hex-idle"> — dark slate + faint glowColor
<pattern id="hex-pattern"> — honeycomb polygon, glowColor stroke, 8×9.24 tile
```

### Implementation approach:

1. Copy `DualRingMechanism.tsx` as the starting base
2. Replace the `renderSegmentText` + segment rendering in both outer and inner ring maps with the Hex Pattern Surface variant from `WheelRingStyles.tsx`
3. Replace the `<defs>` section: remove liquid-metal gradients/filters, add hex-pattern gradients/pattern
4. Keep ALL kinetic gliders, structural beams, orbital ticks, particle chase, core shimmer, voice aura, base plate — these are identical
5. Keep the `ENERGY_CYCLE` import and particle chase relay
6. **CRITICAL: Keep the local `<style jsx>` block** — DualRingMechanism has a local `<style jsx>` (lines 848-872) that OVERRIDES globals.css with 3x SLOWER rotation speeds. This MUST be copied verbatim:

```jsx
<style jsx>{`
  .ring-outer-anim {
    animation: rotate-slow 60s linear infinite;
    transform-origin: center;
  }
  .ring-middle-anim {
    animation: rotate-slow 45s linear infinite reverse;
    transform-origin: center;
  }
  .ring-inner-anim {
    animation: rotate-slow 30s linear infinite;
    transform-origin: center;
  }
  @keyframes rotate-slow {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
`}</style>
```

**DO NOT rely on globals.css classes** — the preview (WheelRingStyles.tsx) uses globals.css (20s/15s/10s), but production uses this local block (60s/45s/30s). If you forget this, the rings will spin 3x too fast.

### Critical dependencies to carry over verbatim:

1. **`hexToRgba` function** — defined locally in DualRingMechanism (handles both hex AND hsl color formats)
2. **`polarToCartesian` function** — rounds to 2 decimal places for SSR hydration safety
3. **`generateArcPath` function** — generates SVG arc paths for ring segments
4. **`ENERGY_CYCLE` import** — from `@/lib/timing-config` (particle chase relay synchronization)
5. **`Card` type import** — from `@/types/navigation`
6. **Local `<style jsx>` block** — 60s/45s/30s rotation speeds (see above)
7. **Spring config** — `stiffness: 80, damping: 16` for segment centering rotation
8. **Confirm spin** — outer ring `+360°`, inner ring `-360°`, 0.8s ease-in-out
9. **Segment text along arc** — `<textPath>` rendering with uppercase labels
10. **Voice aura** — dynamic background that pulses with `isVoiceActive` and `voiceIntensity`
11. **Base plate + depth groove** — industrial foundation layers (SVG circles with gradients)
12. **Particle chase relay** — two particles (Alpha + Beta) at `outerRadius + 29`, synced to ENERGY_CYCLE segments
13. **Structural energy circuit** — rotating "power spark" ring at `outerRadius + 29`

### Verify:

```bash
npx tsc --noEmit  # 0 errors
```

Open `http://localhost:3000/orb-preview` — the WheelRingStyles preview still renders (it keeps its own copy).

Commit:
```
git add components/wheel-view/HexPatternRingMechanism.tsx
git commit -m "feat(wheel-view): create HexPatternRingMechanism with hex pattern surface aesthetic"
```

---

## Task 22: Wire `HexPatternRingMechanism` into `WheelView` + update `ConnectionLine` aesthetic + core halo labeling

**Files:**
- Modify: `components/wheel-view/WheelView.tsx`
- Modify: `components/wheel-view/ConnectionLine.tsx`

**Why:** Replace the `DualRingMechanism` import and usage with `HexPatternRingMechanism`. This is a 1:1 swap — the props interface is identical. ALSO update the `ConnectionLine` to match the hex pattern surface aesthetic. ALSO add core halo labeling — the center button shows the selected card's label instead of just the category name.

### Step 22.1: WheelView import swap

```tsx
// Old:
import { DualRingMechanism } from "./DualRingMechanism"
// ...
<DualRingMechanism
  items={cardStack}
  selectedIndex={selectedIndex}
  onSelect={handleSelect}
  glowColor={glowColor}
  basePlateColor={`hsl(${basePlateColor.hue}, ${basePlateColor.saturation}%, ${basePlateColor.lightness}%)`}
  orbSize={300}
  confirmSpinning={confirmSpinning}
  isVoiceActive={isVoiceActive}
  voiceIntensity={audioLevel}
/>

// New:
import { HexPatternRingMechanism } from "./HexPatternRingMechanism"
// ...
<HexPatternRingMechanism
  items={cardStack}
  selectedIndex={selectedIndex}
  onSelect={handleSelect}
  glowColor={glowColor}
  basePlateColor={`hsl(${basePlateColor.hue}, ${basePlateColor.saturation}%, ${basePlateColor.lightness}%)`}
  orbSize={300}
  confirmSpinning={confirmSpinning}
  isVoiceActive={isVoiceActive}
  voiceIntensity={audioLevel}
/>
```

No other changes in WheelView.tsx for the import swap — the SidePanel, keyboard navigation, confirm flow, and drag-to-move all remain identical.

### Step 22.2: Update ConnectionLine to hex pattern aesthetic

The current `ConnectionLine.tsx` (157 lines) has a 4-layer SVG beam:
1. Brand Color Saturation Layer (backlight, blur 2px, opacity 0.7)
2. Neon Edge Bloom Overlay (atmospheric, blur 4px, opacity 0.6)
3. Main High-Intensity Energy Beam (gradient, drop-shadow, opacity 0.15)
4. Base conduit — Perpetual High-Intensity Beam (glowColor, drop-shadow, opacity 0.95)

**Changes to match hex pattern aesthetic:**

Add a **hex pattern texture overlay** as a 5th layer, between the base conduit and the neon edge. This gives the connection bridge the same honeycomb texture as the ring segments:

```tsx
// Add to <defs>:
<pattern id="line-hex-pattern" x="0" y="0" width="8" height="9.24" patternUnits="userSpaceOnUse">
  <polygon
    points="4,0 8,2.31 8,6.93 4,9.24 0,6.93 0,2.31"
    fill="none"
    stroke={hexToRgba(glowColor, 0.4)}
    strokeWidth="0.4"
  />
</pattern>

// Add as 5th layer (after base conduit, before shimmer):
{/* 5. Hex Pattern Texture Overlay — matches ring segment surface */}
<line
  x1="0"
  y1={containerHeight / 2}
  x2={lineWidth}
  y2={containerHeight / 2}
  stroke="url(#line-hex-pattern)"
  strokeWidth={lineHeight * 1.5}
  strokeLinecap="round"
  style={{ opacity: 0.3 }}
/>
```

Also update the **neon edge** (layer 2) to use the same drop-shadow style as the hex pattern segment edges:

```tsx
// Layer 2 — update filter to match hex pattern neon edge:
style={{
  filter: `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})`,
  opacity: 0.6
}}
```

The `hexToRgba` function is already defined locally in ConnectionLine.tsx (line 30-36) — no new import needed.

### Step 22.3: Add core halo labeling — center button shows selected card label

**Current behavior** (WheelView.tsx line 678-681):
```tsx
{/* 5. CONTENT AREA */}
<div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" style={{ zIndex: 10 }}>
  <span className="text-[10px] font-black uppercase tracking-[0.1em] text-white select-none" style={{ textShadow: '0 2px 4px rgba(0,0,0,0.5)' }}>
    {categoryId}
  </span>
</div>
```

**New behavior**: When a segment is selected (`selectedIndex >= 0` and `activeCard` exists), show the card's label instead of the category name. When no segment is selected, fall back to `categoryId`.

```tsx
{/* 5. CONTENT AREA — shows selected card label or category name */}
<div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" style={{ zIndex: 10 }}>
  <AnimatePresence mode="wait">
    <motion.span
      key={activeCard?.id ?? categoryId}  // re-mount on card change → triggers animation
      className="text-[10px] font-black uppercase tracking-[0.1em] text-white select-none"
      style={{ textShadow: '0 2px 4px rgba(0,0,0,0.5)' }}
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.8 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {activeCard?.label ?? categoryId}
    </motion.span>
  </AnimatePresence>
</div>
```

**Logic**:
- `activeCard` is already available in WheelView (line 689: `card={activeCard}`)
- `activeCard?.label` gives the selected card's display name (e.g., "Microphone", "Wake Word")
- When `activeCard` is null (no selection), falls back to `categoryId` (e.g., "Voice")
- The `AnimatePresence mode="wait"` ensures the old label exits before the new one enters
- The `key` prop uses `activeCard?.id ?? categoryId` to trigger re-mount on card change
- Animation: fade (opacity 0→1) + scale (0.8→1.0) over 300ms with easeOut

**Import needed**: `AnimatePresence` is already imported in WheelView (used for SidePanel). `motion` is already imported. No new imports.

### Verify:

```bash
npx tsc --noEmit  # 0 errors
```

Open the live app at `/` — navigate to a category → WheelView renders with:
- Hex pattern surface rings
- Hex-textured connection bridge
- Center button showing the selected card label (fade+scale animation on change)

Commit:
```
git add components/wheel-view/WheelView.tsx components/wheel-view/ConnectionLine.tsx
git commit -m "refactor(wheel-view): swap DualRingMechanism for HexPatternRingMechanism + hex pattern ConnectionLine + core halo labeling"
```

---

## Task 23: Delete `DualRingMechanism.tsx` and update `wheel-overview.md`

**Files:**
- Delete: `components/wheel-view/DualRingMechanism.tsx`
- Modify: `docs/wheel-overview.md` — add redirect note pointing to `docs/Design/Hex-Pattern-Wheel-View.md`

**Why:** Once `HexPatternRingMechanism` is wired in and verified, the old `DualRingMechanism.tsx` (875 lines) is dead code. The old `wheel-overview.md` is superseded by the new design doc.

### Before deleting:

1. Search for any remaining imports of `DualRingMechanism`:
```bash
grep -r "DualRingMechanism" components/ app/ contexts/ hooks/
```
Expected: 0 results (only the deleted file itself).

2. Verify the live app works end-to-end:
- Navigate to a category → WheelView renders
- Select segments → spring rotation works
- Confirm → spin animation works
- Voice active → aura pulses
- Keyboard navigation → arrow keys work

### Delete:

```bash
git rm components/wheel-view/DualRingMechanism.tsx
```

### Update `wheel-overview.md`:

Replace the content with a redirect notice:

```markdown
# WheelView Architecture — Superseded

This document has been superseded by the Hex Pattern Wheel View design document.

→ **[Hex Pattern Wheel View Design](./Design/Hex-Pattern-Wheel-View.md)**

The original DualRingMechanism has been replaced by HexPatternRingMechanism.
The new design doc covers the full layered SVG stack, kinetic gliders, and
hex pattern surface aesthetic.
```

Commit:
```
git rm components/wheel-view/DualRingMechanism.tsx
git add docs/wheel-overview.md
git commit -m "refactor(wheel-view): remove DualRingMechanism, redirect wheel-overview.md to new design doc"
```

---

## Task 24: Add `HexPatternRingMechanism` preview to orb-preview page

**Files:**
- Modify: `app/orb-preview/page.tsx`

**Why:** Add a standalone preview of the production `HexPatternRingMechanism` alongside the existing `WheelRingStyles` mockup variants, so the production component can be tested in isolation.

```tsx
import { HexPatternRingMechanism } from "@/components/wheel-view/HexPatternRingMechanism"

// After the WheelRingStyles section:
<section className="flex flex-col items-center gap-4 mt-12">
  <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
    Hex Pattern Ring Mechanism — Production
  </h2>
  <p className="text-xs text-slate-500 max-w-md text-center">
    The production replacement for DualRingMechanism. Same props, same functionalities.
    Hex pattern surface + neon edge glow on interactive segments.
  </p>
  <div className="p-6 rounded-2xl border border-white/10 bg-black/20">
    <HexPatternRingMechanism
      items={sampleCards}
      selectedIndex={0}
      onSelect={() => {}}
      glowColor={theme.color}
      orbSize={300}
    />
  </div>
</section>
```

Commit:
```
git add app/orb-preview/page.tsx
git commit -m "feat(orb-preview): add HexPatternRingMechanism production preview"
```

---

## Task 25: End-to-end WheelView verification with Hex Pattern Surface

**Files:** None (verification only)

### Visual:
- [ ] WheelView renders with hex pattern texture on segment surfaces
- [ ] Honeycomb pattern visible at idle (opacity 0.22)
- [ ] Honeycomb pattern brightens on selection (opacity 0.4)
- [ ] Neon edge outline glows on selected segment (drop-shadow)
- [ ] All 4 structural beams visible (2 CCW + 2 CW counter-rotating pairs)
- [ ] Barrier kinetic glider moves faster than orbital ticks (8s vs 60s — production speeds)
- [ ] Gap kinetic glider rotates CCW (CSS + framer-motion beam)
- [ ] Core kinetic glider rotates CW (CSS + framer-motion beam)
- [ ] Core shimmer pulses
- [ ] Particle chase relay animates (ENERGY_CYCLE synced)
- [ ] **Ring rotation speeds are SLOW (60s/45s/30s) — NOT fast (20s/15s/10s)**
- [ ] **ConnectionLine shows hex pattern texture overlay**
- [ ] **ConnectionLine neon edge matches ring segment neon edge style**
- [ ] **Center button shows selected card label (e.g. "Microphone") not just category name**
- [ ] **Card label fades + scales in (0.8→1.0, 300ms) when segment is clicked**
- [ ] **Center button falls back to categoryId when no card is selected**

### Functional:
- [ ] Click segment → spring rotation centers it at 12 o'clock
- [ ] Selected segment shows hex pattern + neon edge
- [ ] SidePanel appears with correct card fields
- [ ] ConnectionLine renders between orb and panel
- [ ] Confirm button → spin animation (counter-rotation)
- [ ] Confirm → sends `confirm_card` WS message with field values
- [ ] Keyboard navigation (arrows + Enter + Escape) works
- [ ] Voice active → aura pulses, audio level rings appear
- [ ] Processing state → orbital spinner appears
- [ ] Error state → red pulse + error message
- [ ] Drag-to-move window works
- [ ] Double-click center button → toggles voice
- [ ] Single-click center button → back to categories

### No regressions:
- [ ] `npx tsc --noEmit` → 0 errors
- [ ] No console errors
- [ ] No references to `DualRingMechanism` remain
- [ ] `wheel-overview.md` redirects to new design doc
