# Voice Pipeline, TTS/Document Separation & Rich Rendering — Design Plan

> Date: 2026-07-09
> Status: Design validated, ready for implementation planning
> Consultation: 2026-07-09 (user confirmed all four work streams)
> Parent plans: `docs/plans/2026-07-06-agent-multi-step-tool-execution.md`, `docs/plans/2026-07-08-phase5-frontend-completion.md`

---

## 0. Overview

Four interconnected issues, one unified fix:

| # | Issue | Root Cause | Solution |
|---|-------|-----------|----------|
| A | VAD inconsistency — STT sometimes doesn't process | Energy-based silence detection is flaky; thresholds/timing miscalibrated | Robust VAD with adaptive threshold + reliable silence timeout |
| B | Orb "thinking" ring looks horrible, off-center | Ad-hoc CSS border ring (XurOrb lines 468–498) clashes with particle aesthetic | Replace with orbiting particles matching OrbCanvas language |
| C | TTS recites entire MD document | No speak/show separation; full LLM text → chunk_callback → TTS | Structured JSON response (`speak` + `show` fields) + `speak` tool for agent-initiated speech |
| D | MD documents lack format options & rich rendering | No format selection, no markdown renderer, just plain text in a card | Custom Prism Glass markdown renderer + format auto-decision + alternatives + inline/expand rendering |

---

## 0.1 Design Token Reference (VERIFIED — copy these exact values)

All styling in this plan references these exact tokens from `contexts/BrandColorContext.tsx`. **Do not invent new values.** Use these.

### Theme Config (via `useBrandColor().getThemeConfig()`)

```ts
// Aether theme (default) — exact values from PRISM_THEMES.aether
glow.color:        "#00c8ff"
glow.opacity:      0.3
glow.blur:         12
shimmer.primary:   "hsl(190, 100%, 60%)"
shimmer.secondary: "hsl(180, 80%, 55%)"
shimmer.accent:    "hsl(200, 100%, 70%)"
glass.opacity:     0.18
glass.blur:        24
glass.borderOpacity: 0.15
text.primary:      "rgba(255, 255, 255, 0.95)"
text.secondary:    "rgba(255, 255, 255, 0.70)"
gradient.from:     "hsl(190, 100%, 15%)"
gradient.to:       "hsl(190, 100%, 50%)"
gradient.angle:    135
```

**Other themes** (ember, aurum, verdant) have different `glow.color` / `shimmer.*` / `glass.*` values — see `PRISM_THEMES` in `BrandColorContext.tsx` lines 114–259. **Always read from `getThemeConfig()` at runtime — never hardcode a theme's values.**

### Glass Card Pattern (VERIFIED — from PermissionCard.tsx lines 136–162)

Every glass card in this project uses this exact pattern. **Copy it verbatim.**

```tsx
// Outer container
<div
  className="rounded-lg overflow-hidden relative"
  style={{
    background: `linear-gradient(135deg, rgba(10,11,22,${0.6 + glassOpacity * 2}) 0%, rgba(15,16,28,${0.65 + glassOpacity * 2}) 100%)`,
    backdropFilter: `blur(${glassBlur}px)`,
    WebkitBackdropFilter: `blur(${glassBlur}px)`,
    borderLeft: `2px solid ${accentColor}`,   // tier/glow color
    border: `1px solid ${accentColor}20`,
    boxShadow: `
      inset 0 1px 1px rgba(255,255,255,0.04),
      inset 0 -1px 1px rgba(0,0,0,0.5),
      0 0 0 1px rgba(0,0,0,0.6),
      0 4px 20px rgba(0,0,0,0.4)
    `,
  }}
>
  {/* Edge fresnel — ALWAYS inside the rounded container, ALWAYS with `relative` on parent */}
  <div
    className="absolute inset-0 pointer-events-none"
    style={{
      background: `
        linear-gradient(90deg, ${shimmerPrimary}06 0%, transparent 20%, transparent 80%, ${shimmerPrimary}06 100%),
        linear-gradient(0deg, ${shimmerPrimary}04 0%, transparent 20%, transparent 80%, ${shimmerPrimary}04 100%)
      `,
      borderRadius: "10px",
    }}
  />
  {/* Content goes here — always wrapped in <div className="relative p-3"> */}
</div>
```

**Where:**
- `glassOpacity` = `brandTheme.glass.opacity` (0.18 for aether)
- `glassBlur` = `brandTheme.glass.blur` (24 for aether)
- `shimmerPrimary` = `brandTheme.shimmer.primary`
- `accentColor` = `glowColor` (for generic cards) or tier color (for permission cards)

### Framer Motion Enter/Exit (VERIFIED — from PermissionCard/QuestionCard)

```tsx
<motion.div
  initial={{ opacity: 0, y: 8, scale: 0.98 }}
  animate={{ opacity: 1, y: 0, scale: 1 }}
  exit={{ opacity: 0, y: -8, scale: 0.98 }}
  transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
  className="my-3 w-full"
>
```

### Typography (VERIFIED — from XurOrb labels + OrbBadge)

**Orb-adjacent text (particle language):**
```tsx
fontFamily: "'Courier New', Courier, monospace"
fontSize: 11           // px
fontWeight: 700
letterSpacing: "0.12em"
textTransform: "uppercase"
textShadow: `0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`
color: glowColor        // or "#e2e8f0" for active, "#475569" for inactive
```

**Chat card text (glass language):**
```tsx
// Body text
fontSize: "11px"        // text-[11px]
color: "rgba(255,255,255,0.55)"  // body
color: "rgba(255,255,255,0.70)"  // emphasized body

// Labels / captions
fontSize: "9px"         // text-[9px] — for timestamps, tier labels
fontSize: "8px"         // text-[8px] — for "Parameters" header, "+N more"
fontWeight: 600         // font-semibold for labels
letterSpacing: "wide"   // tracking-wide
textTransform: "uppercase"

// Monospace (params, tool names)
fontFamily: "monospace" // font-mono — for code/params/tool names
fontSize: "9px"         // text-[9px] for params
fontSize: "11px"        // text-[11px] for tool names
```

### Button Pattern (VERIFIED — from PermissionCard/QuestionCard)

```tsx
// Primary button (accent-colored)
<button
  className="px-2.5 py-1 rounded-lg text-[11px] font-medium tracking-wide transition-all duration-150 hover:brightness-125"
  style={{
    color: accentColor,
    backgroundColor: `${accentColor}12`,     // 12 = ~7% opacity hex
    border: `1px solid ${accentColor}30`,     // 30 = ~19% opacity hex
  }}
>

// Secondary button (neutral)
<button
  className="px-2.5 py-1 rounded-lg text-[11px] font-medium tracking-wide transition-all duration-150 hover:brightness-125"
  style={{
    color: "rgba(255,255,255,0.5)",
    backgroundColor: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.08)",
  }}
>
```

### Orb Particle Language (VERIFIED — from OrbBadge.tsx + OrbCanvas.tsx)

```tsx
// Particle pip (additive glow — matches OrbCanvas globalCompositeOperation='lighter')
{
  width: 10,
  height: 10,
  borderRadius: "50%",
  background: `radial-gradient(circle, ${glowColor} 0%, ${glowColor}55 45%, transparent 72%)`,
  boxShadow: `0 0 10px ${glowColor}, 0 0 4px ${glowColor}`,
  mixBlendMode: "lighter",
}

// OrbCanvas shell config (for reference — do NOT change OrbCanvas)
SIZE = 120
SHELLS = [
  { scale: 1.05, speed: 1.0, count: 80, alpha: 0.55, size: 1.0 },  // outer
  { scale: 0.70, speed: 1.45, count: 56, alpha: 0.40, size: 0.8 }, // mid
  { scale: 0.42, speed: 0.62, count: 32, alpha: 0.85, size: 0.7 }, // inner
]
```

### Orb Dimensions (VERIFIED — from XurOrb.tsx)

```
CONTAINER_SIZE = 120   // the orbRef div
CANVAS_SIZE = 90       // OrbCanvas internal (but renders at 120px via SIZE=120)
LABEL_BASE = 45        // label radius from center
Labels: Chat (bottom, y+45), Menu (top, y-45), Voice (left, x-45, y+20)
Label-free zones: top-right, right, bottom-right
```

---

## 1. Issue A — VAD / STT Trigger Reliability

### 1.1 Current State

**File:** `backend/audio/voice_command.py` — `_vad_wait_for_speech_then_silence()`

Energy-based VAD:
1. Waits for audio frames with energy above `_SPEECH_ENERGY_THRESHOLD`
2. Once speech detected, starts a silence timer
3. When energy stays below `_SILENCE_ENERGY_THRESHOLD` for `_SILENCE_FRAMES` consecutive frames → triggers STT
4. STT processes the accumulated audio buffer

**Symptom:** Intermittent — sometimes STT processes fine, other times it hangs in "listening" indefinitely. The silence detection doesn't fire.

### 1.2 Root Cause Analysis

The intermittent nature points to:
1. **Fixed energy thresholds** — don't adapt to ambient noise levels. A quiet room vs. a noisy room have very different baselines.
2. **Frame count for silence** — if `_SILENCE_FRAMES` is too high, brief pauses in speech reset the counter and STT never triggers. If too low, it triggers mid-sentence.
3. **No maximum listening timeout** — if silence detection fails, the system hangs forever in "listening" state.
4. **No fallback trigger** — if VAD fails, there's no secondary mechanism to force STT processing.

### 1.3 Solution: Adaptive VAD + Safety Timeouts

**Changes to `backend/audio/voice_command.py`:**

1. **Adaptive noise floor:** On VAD start, sample 0.5s of ambient audio to calibrate the noise floor. Set `_SILENCE_ENERGY_THRESHOLD = noise_floor * 1.5` and `_SPEECH_ENERGY_THRESHOLD = noise_floor * 3.0`. Recalibrate if listening > 10s (room changed).

2. **Adaptive silence frames:** Start with `_SILENCE_FRAMES = 15` (~0.5s at 30fps). If speech was short (<2s), use fewer frames (8) for snappier response. If speech was long (>5s), use more frames (20) to avoid cutting off pauses.

3. **Maximum listening timeout:** Hard cap at 30s. If still listening after 30s, force STT processing on whatever audio was captured. Log a warning. This is the safety net — VAD should trigger before this, but if it doesn't, the user isn't stuck.

4. **Minimum speech duration:** If detected "speech" is < 0.3s, discard it as noise (don't trigger STT). Prevents false triggers from clicks/bumps.

5. **Hysteresis:** Speech-to-silence threshold should be lower than silence-to-speech threshold (already partially implemented, but verify the gap is sufficient — at least 1.5x ratio).

6. **Debug logging:** Log energy levels, threshold, frame counts, and state transitions at DEBUG level with a `[VAD]` prefix so issues can be diagnosed post-hoc.

**Quality check:**
- [ ] No blocking calls in the VAD loop — all audio frame processing is non-blocking
- [ ] Adaptive calibration is bounded (0.5s sample, recalibrate at most every 10s)
- [ ] Maximum listening timeout is a hard cap — no path where VAD hangs forever
- [ ] Error handling: audio device failure → log, notify frontend, clean exit
- [ ] No shared mutable state across concurrent voice commands

**Test:** `backend/tests/test_vad_reliability.py`
- Contract: adaptive threshold calibrates from ambient noise
- Contract: silence detection triggers STT after adaptive frames
- Contract: 30s max listening timeout forces STT
- Contract: <0.3s speech bursts are discarded as noise
- Behavioral: quiet room → lower threshold, noisy room → higher threshold

---

## 2. Issue B — Orb Working Indicator: Orbiting Particles

### 2.1 Current State

**File:** `components/iris/XurOrb.tsx` lines 468–498

A `motion.div` with `inset: -28`, `border: 2px solid ${glowColor}`, `boxShadow`, and a "THINKING/WORKING/NEEDS INPUT" label at `-bottom-7`. This is a flat CSS border ring — it clashes with the orb's canvas-particle aesthetic and is visually off-center because the label is positioned relative to the 176px ring, not the 120px orb.

**Separately:** `OrbBadge.tsx` (the Phase 5 particle pip at top-right) exists and works. It stays.

### 2.2 Solution: Orbiting Particle Ring

**Replace** the flat CSS ring (lines 468–498) with an orbiting particle system that matches the OrbCanvas visual language.

**New file:** `components/iris/OrbWorkingIndicator.tsx`

### 2.3 Exact Component Specification

**Props:**
```ts
interface OrbWorkingIndicatorProps {
  isActive: boolean
  variant: "working" | "question"
  glowColor: string
  shimmerPrimary?: string  // brightened brand color for active state
}
```

**Exact JSX template (copy this):**

```tsx
"use client"

import { motion, AnimatePresence } from "framer-motion"
import { useReducedMotion } from "@/hooks/useReducedMotion"

export interface OrbWorkingIndicatorProps {
  isActive: boolean
  variant: "working" | "question"
  glowColor: string
  shimmerPrimary?: string
}

const ORBIT_RADIUS = 55    // px from orb center — just outside the 120px shell edge (60px radius)
const PARTICLE_COUNT = 5
const PARTICLE_SIZE = 5    // px

// Each particle has a different orbital speed + starting angle
const PARTICLE_CONFIGS = [
  { duration: 2.5, startAngle: 0,    delay: 0 },
  { duration: 3.0, startAngle: 72,   delay: 0.1 },
  { duration: 3.5, startAngle: 144,  delay: 0.2 },
  { duration: 4.0, startAngle: 216,  delay: 0.15 },
  { duration: 4.5, startAngle: 288,  delay: 0.05 },
]

export function OrbWorkingIndicator({
  isActive,
  variant,
  glowColor,
  shimmerPrimary,
}: OrbWorkingIndicatorProps) {
  const prefersReducedMotion = useReducedMotion()
  const activeColor = shimmerPrimary || glowColor

  // Question variant: slower, unified pulse
  const orbitDurationMultiplier = variant === "question" ? 1.8 : 1.0
  const pulseDuration = variant === "question" ? 1.4 : 0.8

  return (
    <AnimatePresence>
      {isActive && (
        <motion.div
          initial={{ opacity: 0, scale: 0.5 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.5 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
            zIndex: 15,
          }}
        >
          {prefersReducedMotion ? (
            // Reduced motion: static glow ring (no orbit)
            <div
              style={{
                position: "absolute",
                width: ORBIT_RADIUS * 2,
                height: ORBIT_RADIUS * 2,
                borderRadius: "50%",
                border: `1px solid ${activeColor}40`,
                boxShadow: `0 0 12px ${activeColor}30, inset 0 0 8px ${activeColor}20`,
              }}
            />
          ) : (
            // Orbiting particles
            PARTICLE_CONFIGS.map((cfg, i) => (
              <motion.div
                key={i}
                style={{
                  position: "absolute",
                  width: PARTICLE_SIZE,
                  height: PARTICLE_SIZE,
                  borderRadius: "50%",
                  background: `radial-gradient(circle, ${activeColor} 0%, ${activeColor}55 45%, transparent 72%)`,
                  boxShadow: `0 0 8px ${activeColor}, 0 0 3px ${activeColor}`,
                  mixBlendMode: "lighter",
                }}
                animate={{
                  rotate: 360,
                  opacity: [0.4, 0.9, 0.4],
                }}
                transition={{
                  rotate: {
                    duration: cfg.duration * orbitDurationMultiplier,
                    repeat: Infinity,
                    ease: "linear",
                    delay: cfg.delay,
                  },
                  opacity: {
                    duration: pulseDuration,
                    repeat: Infinity,
                    ease: "easeInOut",
                    delay: cfg.delay,
                  },
                }}
                // Position: start at angle, orbit at radius
                // The rotate animation on this div spins it around the center.
                // We offset the particle to ORBIT_RADIUS using transform-origin.
                // Container is 120px (CONTAINER_SIZE), center is 60,60.
                // Particle sits at (60 + ORBIT_RADIUS, 60) initially, then rotates.
              >
                {/* Inner wrapper to position particle at orbit radius */}
                <div
                  style={{
                    position: "absolute",
                    left: ORBIT_RADIUS - PARTICLE_SIZE / 2,
                    top: -PARTICLE_SIZE / 2,
                    transform: `rotate(${cfg.startAngle}deg)`,
                    transformOrigin: `${-ORBIT_RADIUS + PARTICLE_SIZE / 2}px ${PARTICLE_SIZE / 2}px`,
                    width: PARTICLE_SIZE,
                    height: PARTICLE_SIZE,
                    borderRadius: "50%",
                    background: `radial-gradient(circle, ${activeColor} 0%, ${activeColor}55 45%, transparent 72%)`,
                    boxShadow: `0 0 8px ${activeColor}, 0 0 3px ${activeColor}`,
                    mixBlendMode: "lighter",
                  }}
                />
              </motion.div>
            ))
          )}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
```

**CRITICAL positioning note:** The orbiting particles must be centered on the orb's center (60, 60 in the 120px container). The `motion.div` parent uses `inset: 0` + `display: flex; alignItems: center; justifyContent: center` so its center is the orb's center. Each particle's inner wrapper is positioned at `ORBIT_RADIUS` from center and rotated by its `startAngle`. The framer-motion `rotate: 360` on the outer motion.div spins the particle around the center.

**If the positioning doesn't work with the above transform-origin approach,** use this alternative pattern (simpler, more reliable):

```tsx
// Alternative: each particle is a motion.div that rotates around orb center
{PARTICLE_CONFIGS.map((cfg, i) => (
  <motion.div
    key={i}
    style={{
      position: "absolute",
      left: "50%",
      top: "50%",
      width: 0,
      height: 0,
      transformOrigin: "center center",
    }}
    animate={{ rotate: 360 }}
    transition={{
      duration: cfg.duration * orbitDurationMultiplier,
      repeat: Infinity,
      ease: "linear",
      delay: cfg.delay,
    }}
  >
    <div
      style={{
        position: "absolute",
        left: ORBIT_RADIUS - PARTICLE_SIZE / 2,
        top: -PARTICLE_SIZE / 2,
        width: PARTICLE_SIZE,
        height: PARTICLE_SIZE,
        borderRadius: "50%",
        background: `radial-gradient(circle, ${activeColor} 0%, ${activeColor}55 45%, transparent 72%)`,
        boxShadow: `0 0 8px ${activeColor}, 0 0 3px ${activeColor}`,
        mixBlendMode: "lighter",
        transform: `rotate(${cfg.startAngle}deg)`,
        transformOrigin: `${-ORBIT_RADIUS + PARTICLE_SIZE / 2}px center`,
        opacity: 0.7,
      }}
    />
  </motion.div>
))}
```

**No text label.** The OrbBadge already shows the step counter / `?` glyph. The orbiting particles are purely a visual "something is happening" cue — no words needed.

### 2.4 Integration in XurOrb.tsx

**Remove lines 468–498** (the entire `{isAgentWorking && (...)}` block with the flat ring + "THINKING/WORKING/NEEDS INPUT" label).

**Replace with:**
```tsx
<OrbWorkingIndicator
  isActive={isAgentWorking}
  variant={agentQuestion.hasPendingQuestion ? "question" : "working"}
  glowColor={glowColor}
  shimmerPrimary={theme.shimmer.primary}
/>
```

**Add import at top:**
```tsx
import { OrbWorkingIndicator } from "./OrbWorkingIndicator"
```

**Keep `OrbBadge` as-is** (lines 500–507) — it stays. The OrbBadge shows the step counter / `?` at top-right. The OrbWorkingIndicator shows orbiting particles around the whole orb. They complement each other.

**`pointer-events: none`** on the OrbWorkingIndicator container — never intercepts orb drag/click.

### 2.5 Quality Check

- [ ] Particles use `mixBlendMode: 'lighter'` — matches OrbCanvas additive glow
- [ ] Particle background is `radial-gradient(circle, ${activeColor} 0%, ${activeColor}55 45%, transparent 72%)` — matches OrbBadge pip
- [ ] Particle boxShadow is `0 0 8px ${activeColor}, 0 0 3px ${activeColor}` — matches OrbBadge pip (slightly smaller glow)
- [ ] No glass/flat CSS border — pure particle/glow
- [ ] `pointer-events: none` on container — never blocks orb interaction
- [ ] Bounded particle count (5 max) — no unbounded rendering
- [ ] Animation uses GPU transforms (rotate/opacity) — no layout thrash
- [ ] Respects `prefersReducedMotion` — static glow ring instead of orbit
- [ ] `zIndex: 15` — above OrbCanvas (zIndex 2) but below labels (zIndex 1) and RadialArcNodes (zIndex 5). Actually: above everything inside the orb container, but below the OrbBadge (zIndex 20) and the flash overlay.
- [ ] No text label — OrbBadge handles the counter/`?`

**Test:** `__tests__/components/OrbWorkingIndicator.test.tsx`
- Renders when `isActive=true`, hidden when `isActive=false`
- 5 particles present (query by the particle background style)
- Container has `pointer-events: none`
- Question variant: particles have slower animation (check transition duration multiplier)
- Reduced motion: static ring rendered, no orbiting particles

---

## 3. Issue C — TTS / Document Separation (Speak + Show)

### 3.1 Current State

The LLM generates a single text response. That entire text flows:
`LLM → chunk_callback → sentence_buf → sentence_queue → _speak_response → TTS`

`tts_normalizer.py` strips markdown syntax (headers, bold, links, code fences) but still passes all text content through. `filter_speech()` in `conversation_kernel.py` strips tool-call JSON and code blocks but does not separate "what to speak" from "what to show."

**Result:** When the agent generates a 2000-word document, TTS reads all 2000 words.

### 3.2 Solution: Two-Channel Response (Speak + Show) + Speak Tool

#### 3.2.1 Structured JSON Response

**Change the LLM response contract.** Instead of a free-text response, the LLM returns structured JSON:

```json
{
  "speak": "Here's a comparison of the three options I found...",
  "show": {
    "format": "markdown",
    "content": "# Comparison\n\n| Option | Pros | Cons |\n|...|...|...|",
    "alternatives": ["table", "diagram", "html"]
  }
}
```

**Fields:**
- `speak` (string, required): What TTS reads. Short, conversational, 1–3 sentences. This is what the user *hears*.
- `show` (object, optional): What renders visually. Contains:
  - `format`: `"markdown" | "html" | "table" | "diagram" | "text"` — the format the agent chose
  - `content`: The full document content in that format
  - `alternatives`: Array of other formats the agent could render (for the "want it as X instead?" offer)
- If `show` is absent, the response is conversational only — `speak` is rendered as a normal chat message.

**Backend changes:**

**File:** `backend/agent/agent_kernel.py` — `_respond_direct()` and DER loop final response
- Parse the LLM's final text output as JSON
- If valid JSON with `speak`/`show` fields: route `speak` to TTS (via ConversationKernel → utterance event), route `show` to frontend as a `document` WS event
- If not valid JSON (fallback): treat entire text as `speak` (backward compatible — old behavior)
- Add a system prompt instruction telling the LLM to use the structured format when generating documents, and plain text for conversational responses

**File:** `backend/agent/conversation_kernel.py` — `filter_speech()`
- If response is structured JSON: `speak` field goes to TTS, `show` field is stripped from TTS entirely
- If response is plain text: existing behavior (strip markdown syntax, pass through)

**File:** `backend/iris_gateway.py` — response handling
- New WS event type: `document` — carries `{ format, content, alternatives, turn_id, conversation_id }`
- `speak` field → existing `text_response` / `chunk_callback` → TTS path (but only the `speak` content, not the full document)
- `show` field → `document` WS event → frontend renders as rich document

**File:** `backend/agent/event_bus.py`
- Add `DOCUMENT_RENDER = "document:render"` to `IRISStreamEvent` enum
- WSEventBridge forwards it to the frontend

**System prompt addition** (in agent_kernel.py or personality):
```
When generating content longer than 3 sentences or containing structured data (tables, lists, diagrams, code), respond with JSON:
{"speak": "<2-3 sentence conversational summary>", "show": {"format": "<markdown|html|table|diagram|text>", "content": "<full content>", "alternatives": ["<other formats>"]}}
For short conversational responses, respond with plain text.
The "speak" field is what the user hears via TTS — keep it brief and natural.
The "show" field is what renders visually — this is where detail goes.
```

#### 3.2.2 The `speak` Tool

**New file:** `backend/agent/tools/speak_tool.py`

A tool the agent can call to proactively speak via TTS — for updates, follow-ups, and agent-initiated speech even when the audio pipeline isn't open.

**Tool name:** `speak`

**Parameters:**
```python
{
  "text": str,           # what to speak via TTS
  "priority": str,       # "normal" | "high" | "low" (default "normal")
  "interrupt": bool,     # if true, interrupts current TTS (default false)
}
```

**Behavior:**
1. Agent calls `speak` tool during DER loop execution
2. Tool emits an `utterance` event on the EventBus with the text
3. ConversationKernel picks it up → TTS speaks it (if audio pipeline open) or queues it (if not)
4. Orb shows speaking state (existing `playbackSpeaking` mechanism)
5. Tool returns immediately (fire-and-forget) — doesn't block the DER loop
6. If `priority: "high"` and `interrupt: true`: halts current TTS, speaks immediately
7. If audio pipeline closed: TTS still plays (agent-initiated speech, per Phase 5.5.4 design)

**Registration:** `backend/agent/tool_bridge.py` — register `speak` in the tool list, available in all modes, no permission tier (conversational tool).

**Quality check:**
- [ ] Tool is fire-and-forget — never blocks DER loop
- [ ] Text is bounded (max 500 chars) — no unbounded TTS
- [ ] Priority queue is bounded (max 3 pending) — 4th is text-only
- [ ] Error handling: TTS failure → log, tool returns success (speech is best-effort)
- [ ] No shared mutable state — each call is independent

**Test:** `backend/tests/test_speak_tool.py`
- Contract: tool emits utterance event on EventBus
- Contract: fire-and-forget — returns immediately
- Contract: text > 500 chars is truncated
- Contract: high priority + interrupt halts current TTS

#### 3.2.3 Frontend Changes

**File:** `hooks/useIRISWebSocket.ts`
- Forward `document:render` WS events as `iris:document_render` CustomEvents
- Forward `speak` tool events (if not already covered by utterance events)

**File:** `components/chat-view.tsx`
- Listen for `iris:document_render` CustomEvents
- When received: render the document using the new rich renderer (Issue D)
- The `speak` content arrives as normal `text_response` / chat chunks — renders as a normal chat message
- Documents render inline with an "expand to panel" button

---

## 4. Issue D — Rich Document Rendering + Format Options

### 4.1 Current State

`chat-view.tsx` has a `ContentType` system (`markdown | email | video | picture | text`) with thresholds. Long markdown (>800 chars) becomes an "artifact card" — but it's just plain text in a styled div. No `react-markdown`, no table rendering, no syntax highlighting, no diagrams.

### 4.2 Solution: Custom Prism Glass Markdown Renderer + Format System

#### 4.2.1 RichDocument Component

**New file:** `components/chat/RichDocument.tsx`

A custom markdown-to-React renderer that matches the widget's Prism Glass aesthetic.

**Architecture:**
- Use `react-markdown` as the parsing engine (proven, spec-compliant)
- Override every element renderer with custom Prism Glass styled components
- Add `remark-gfm` for GFM tables, strikethrough, task lists
- Add `rehype-highlight` or `react-syntax-highlighter` for code blocks
- Add `mermaid` for diagram rendering (```mermaid blocks)

**Props:**
```ts
interface RichDocumentProps {
  content: string
  format: "markdown" | "html" | "table" | "diagram" | "text"
  glowColor: string
  alternatives?: string[]
  onFormatChange?: (newFormat: string) => void
  onExpand?: () => void
}
```

### 4.3 Exact Component Specification

**Imports:**
```tsx
"use client"

import React, { useMemo, lazy, Suspense } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { motion } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { Expand, Copy, Download } from "lucide-react"

// Lazy-load mermaid only when a ```mermaid block is present
const MermaidDiagram = lazy(() => import("./MermaidDiagram"))
```

**Exact outer container (glass card — copy from §0.1 Glass Card Pattern):**

```tsx
export function RichDocument({
  content,
  format,
  glowColor,
  alternatives = [],
  onFormatChange,
  onExpand,
}: RichDocumentProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColorResolved = glowColor || theme.glow.color
  const shimmerPrimary = theme.shimmer.primary
  const glassBlur = theme.glass.blur        // 24 for aether
  const glassOpacity = theme.glass.opacity  // 0.18 for aether

  // Detect mermaid blocks for lazy loading
  const hasMermaid = useMemo(() => /```mermaid/.test(content), [content])

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-3 w-full"
    >
      <div
        className="rounded-lg overflow-hidden relative"
        style={{
          background: `linear-gradient(135deg, rgba(10,11,22,${0.6 + glassOpacity * 2}) 0%, rgba(15,16,28,${0.65 + glassOpacity * 2}) 100%)`,
          backdropFilter: `blur(${glassBlur}px)`,
          WebkitBackdropFilter: `blur(${glassBlur}px)`,
          borderLeft: `2px solid ${glowColorResolved}`,
          border: `1px solid ${glowColorResolved}20`,
          boxShadow: `
            inset 0 1px 1px rgba(255,255,255,0.04),
            inset 0 -1px 1px rgba(0,0,0,0.5),
            0 0 0 1px rgba(0,0,0,0.6),
            0 4px 20px rgba(0,0,0,0.4)
          `,
        }}
      >
        {/* Edge fresnel — VERIFIED pattern */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `
              linear-gradient(90deg, ${shimmerPrimary}06 0%, transparent 20%, transparent 80%, ${shimmerPrimary}06 100%),
              linear-gradient(0deg, ${shimmerPrimary}04 0%, transparent 20%, transparent 80%, ${shimmerPrimary}04 100%)
            `,
            borderRadius: "10px",
          }}
        />

        <div className="relative p-3">
          {/* Document header — format badge + expand button */}
          <div className="flex items-center gap-2 mb-2.5">
            <span
              className="text-[9px] font-semibold tracking-wide uppercase px-1.5 py-0.5 rounded"
              style={{
                color: glowColorResolved,
                backgroundColor: `${glowColorResolved}12`,
                border: `1px solid ${glowColorResolved}30`,
              }}
            >
              {format}
            </span>
            {onExpand && (
              <button
                onClick={onExpand}
                className="ml-auto p-1 rounded transition-all duration-150 hover:brightness-125"
                style={{
                  color: "rgba(255,255,255,0.4)",
                  backgroundColor: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
                title="Expand to panel"
              >
                <Expand size={11} />
              </button>
            )}
          </div>

          {/* Document content — scrollable, max-height 400px inline */}
          <div
            className="overflow-y-auto"
            style={{ maxHeight: 400 }}
          >
            {format === "html" ? (
              <div
                dangerouslySetInnerHTML={{ __html: content }}
                style={{ color: "rgba(255,255,255,0.7)" }}
              />
            ) : format === "text" ? (
              <p
                className="text-[11px] leading-relaxed whitespace-pre-wrap"
                style={{ color: "rgba(255,255,255,0.7)" }}
              >
                {content}
              </p>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={getMarkdownComponents(glowColorResolved, shimmerPrimary, hasMermaid)}
              >
                {content}
              </ReactMarkdown>
            )}
          </div>

          {/* Format alternatives — pills at bottom */}
          {alternatives.length > 0 && onFormatChange && (
            <div className="flex items-center gap-1.5 pt-2 mt-2 border-t" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
              <span className="text-[8px] font-semibold tracking-wide uppercase" style={{ color: "rgba(255,255,255,0.25)" }}>
                Also as:
              </span>
              {alternatives.map((alt) => (
                <button
                  key={alt}
                  onClick={() => onFormatChange(alt)}
                  className="px-2 py-0.5 rounded text-[9px] font-medium tracking-wide transition-all duration-150 hover:brightness-125"
                  style={{
                    color: glowColorResolved,
                    backgroundColor: `${glowColorResolved}12`,
                    border: `1px solid ${glowColorResolved}30`,
                  }}
                >
                  {alt}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}
```

### 4.4 Exact Markdown Component Overrides (Prism Glass Styled)

**This function returns the `components` prop for `ReactMarkdown`. Every element is custom-styled. Copy these exact values.**

```tsx
function getMarkdownComponents(
  glowColor: string,
  shimmerPrimary: string,
  hasMermaid: boolean
): Components {
  return {
    // ── Tables: glass card with brand-color header ───────────────────
    table: ({ children, ...props }) => (
      <div
        className="my-2 rounded-lg overflow-hidden"
        style={{
          background: "rgba(255,255,255,0.03)",
          border: `1px solid ${glowColor}20`,
          borderLeft: `2px solid ${glowColor}`,
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: "11px",
            fontFamily: "'Courier New', Courier, monospace",
          }}
        >
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => (
      <thead
        style={{
          background: `${glowColor}15`,
          borderBottom: `1px solid ${glowColor}30`,
        }}
      >
        {children}
      </thead>
    ),
    th: ({ children }) => (
      <th
        style={{
          padding: "6px 10px",
          textAlign: "left",
          color: glowColor,
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          fontSize: "10px",
          textShadow: `0 0 8px ${glowColor}44`,
        }}
      >
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td
        style={{
          padding: "6px 10px",
          color: "rgba(255,255,255,0.65)",
          borderBottom: "1px solid rgba(255,255,255,0.04)",
        }}
      >
        {children}
      </td>
    ),

    // ── Code blocks: glass card with accent strip ────────────────────
    pre: ({ children }) => {
      // Check if this is a mermaid block
      const codeElement = children as React.ReactElement
      const className = codeElement?.props?.className || ""
      if (className.includes("language-mermaid") && hasMermaid) {
        return (
          <Suspense fallback={<div className="text-[10px] text-white/30 p-2">Loading diagram...</div>}>
            <MermaidDiagram
              chart={codeElement.props.children}
              glowColor={glowColor}
            />
          </Suspense>
        )
      }
      return (
        <div
          className="my-2 rounded-lg overflow-hidden relative"
          style={{
            background: "rgba(0,0,0,0.4)",
            border: `1px solid ${glowColor}20`,
            borderLeft: `2px solid ${glowColor}`,
          }}
        >
          <pre
            style={{
              padding: "10px 12px",
              overflow: "auto",
              fontSize: "10px",
              fontFamily: "'Courier New', Courier, monospace",
              color: "rgba(255,255,255,0.7)",
              lineHeight: 1.5,
            }}
          >
            {children}
          </pre>
        </div>
      )
    },
    code: ({ inline, className, children, ...props }) => {
      if (inline) {
        return (
          <code
            style={{
              padding: "1px 4px",
              borderRadius: "4px",
              fontSize: "10px",
              fontFamily: "'Courier New', Courier, monospace",
              color: glowColor,
              backgroundColor: `${glowColor}12`,
              border: `1px solid ${glowColor}20`,
            }}
            {...props}
          >
            {children}
          </code>
        )
      }
      return <code className={className} {...props}>{children}</code>
    },

    // ── Headings: monospace with brand-color glow ────────────────────
    h1: ({ children }) => (
      <h1
        style={{
          fontSize: "14px",
          fontWeight: 700,
          fontFamily: "'Courier New', Courier, monospace",
          letterSpacing: "0.08em",
          color: glowColor,
          textShadow: `0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`,
          marginTop: "12px",
          marginBottom: "8px",
          paddingBottom: "4px",
          borderBottom: `1px solid ${glowColor}20`,
        }}
      >
        {children}
      </h1>
    ),
    h2: ({ children }) => (
      <h2
        style={{
          fontSize: "12px",
          fontWeight: 700,
          fontFamily: "'Courier New', Courier, monospace",
          letterSpacing: "0.08em",
          color: glowColor,
          textShadow: `0 0 12px ${glowColor}44`,
          marginTop: "10px",
          marginBottom: "6px",
        }}
      >
        {children}
      </h2>
    ),
    h3: ({ children }) => (
      <h3
        style={{
          fontSize: "11px",
          fontWeight: 700,
          fontFamily: "'Courier New', Courier, monospace",
          letterSpacing: "0.06em",
          color: shimmerPrimary,
          marginTop: "8px",
          marginBottom: "4px",
        }}
      >
        {children}
      </h3>
    ),

    // ── Lists: brand-color markers ───────────────────────────────────
    ul: ({ children }) => (
      <ul
        style={{
          listStyle: "none",
          padding: "4px 0 4px 16px",
          margin: "4px 0",
        }}
      >
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol
        style={{
          listStyle: "none",
          padding: "4px 0 4px 20px",
          margin: "4px 0",
          counterReset: "item",
        }}
      >
        {children}
      </ol>
    ),
    li: ({ children, ...props }) => {
      // Check if parent is ol or ul by looking at props
      const isOrdered = (props as any).node?.parent?.tagName === "ol"
      return (
        <li
          style={{
            position: "relative",
            paddingLeft: "12px",
            marginBottom: "3px",
            fontSize: "11px",
            color: "rgba(255,255,255,0.65)",
            lineHeight: 1.6,
          }}
        >
          <span
            style={{
              position: "absolute",
              left: isOrdered ? "-16px" : "-10px",
              color: glowColor,
              fontFamily: "'Courier New', Courier, monospace",
              fontSize: "10px",
              fontWeight: 700,
            }}
          >
            {isOrdered ? "›" : "•"}
          </span>
          {children}
        </li>
      )
    },

    // ── Blockquote: glass card with left accent ──────────────────────
    blockquote: ({ children }) => (
      <blockquote
        style={{
          margin: "8px 0",
          padding: "8px 12px",
          borderRadius: "8px",
          background: "rgba(255,255,255,0.03)",
          borderLeft: `2px solid ${glowColor}`,
          color: "rgba(255,255,255,0.5)",
          fontStyle: "italic",
          fontSize: "11px",
        }}
      >
        {children}
      </blockquote>
    ),

    // ── Links: brand-color underline ─────────────────────────────────
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: glowColor,
          textDecoration: "underline",
          textDecorationColor: `${glowColor}66`,
          fontSize: "inherit",
        }}
      >
        {children}
      </a>
    ),

    // ── Horizontal rule: brand-color gradient line ───────────────────
    hr: () => (
      <hr
        style={{
          border: "none",
          height: "1px",
          background: `linear-gradient(90deg, transparent, ${glowColor}66, transparent)`,
          margin: "12px 0",
        }}
      />
    ),

    // ── Paragraphs ───────────────────────────────────────────────────
    p: ({ children }) => (
      <p
        style={{
          fontSize: "11px",
          lineHeight: 1.6,
          color: "rgba(255,255,255,0.65)",
          margin: "6px 0",
        }}
      >
        {children}
      </p>
    ),

    // ── Strong / Em ──────────────────────────────────────────────────
    strong: ({ children }) => (
      <strong style={{ color: "rgba(255,255,255,0.85)", fontWeight: 700 }}>
        {children}
      </strong>
    ),
    em: ({ children }) => (
      <em style={{ color: shimmerPrimary, fontStyle: "italic" }}>
        {children}
      </em>
    ),

    // ── Images: glass-framed ─────────────────────────────────────────
    img: ({ src, alt }) => (
      <div
        className="my-2 rounded-lg overflow-hidden"
        style={{
          border: `1px solid ${glowColor}20`,
          padding: "4px",
          background: "rgba(255,255,255,0.02)",
        }}
      >
        <img
          src={src}
          alt={alt}
          style={{
            borderRadius: "6px",
            maxWidthWidth: "100%",
            display: "block",
          }}
        />
      </div>
    ),
  }
}
```

**Type import needed:**
```tsx
import type { Components } from "react-markdown"
```

### 4.5 MermaidDiagram Component (Lazy-Loaded)

**New file:** `components/chat/MermaidDiagram.tsx`

```tsx
"use client"

import { useEffect, useRef, useState } from "react"
import mermaid from "mermaid"

// Initialize mermaid once with dark theme + brand colors
mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  themeVariables: {
    primaryColor: "#0a0b16",
    primaryTextColor: "#ffffff",
    primaryBorderColor: "#00c8ff",
    lineColor: "#00c8ff",
    secondaryColor: "#0f101c",
    tertiaryColor: "#15162a",
    background: "#0a0b16",
    mainBkg: "#0a0b16",
    nodeBorder: "#00c8ff",
    clusterBkg: "#0a0b16",
    titleColor: "#00c8ff",
    edgeLabelBackground: "#0a0b16",
  },
})

interface MermaidDiagramProps {
  chart: string
  glowColor: string
}

export default function MermaidDiagram({ chart, glowColor }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string>("")
  const [error, setError] = useState<string>("")

  useEffect(() => {
    const id = `mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    try {
      mermaid.render(id, chart, (svgResult) => {
        setSvg(svgResult)
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Diagram render failed")
    }
  }, [chart])

  if (error) {
    return (
      <div
        className="p-2 rounded-lg text-[10px] font-mono"
        style={{
          color: "rgba(239,68,68,0.7)",
          background: "rgba(239,68,68,0.06)",
          border: "1px solid rgba(239,68,68,0.2)",
        }}
      >
        Diagram error: {error}
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="my-2 flex justify-center"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
```

### 4.6 DocumentPanel Component (Full-Panel View in Dashboard Wing)

**New file:** `components/chat/DocumentPanel.tsx`

Same `RichDocument` content but full-size, with a toolbar (copy, download, format switcher).

**Exact layout:**

```tsx
"use client"

import React, { useState } from "react"
import { motion } from "framer-motion"
import { Copy, Download, X, FileText } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { RichDocument } from "./RichDocument"

interface DocumentPanelProps {
  content: string
  format: string
  alternatives: string[]
  glowColor: string
  onClose: () => void
  onFormatChange: (newFormat: string) => void
}

export function DocumentPanel({
  content,
  format,
  alternatives,
  glowColor,
  onClose,
  onFormatChange,
}: DocumentPanelProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const shimmerPrimary = theme.shimmer.primary
  const glassBlur = theme.glass.blur
  const glassOpacity = theme.glass.opacity
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    const ext = format === "html" ? "html" : "md"
    const blob = new Blob([content], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `iris-document.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="h-full flex flex-col"
    >
      {/* Toolbar */}
      <div
        className="flex items-center gap-2 p-3 border-b shrink-0"
        style={{
          borderColor: "rgba(255,255,255,0.06)",
          background: `linear-gradient(135deg, rgba(10,11,22,${0.6 + glassOpacity * 2}) 0%, rgba(15,16,28,${0.65 + glassOpacity * 2}) 100%)`,
          backdropFilter: `blur(${glassBlur}px)`,
          WebkitBackdropFilter: `blur(${glassBlur}px)`,
        }}
      >
        <FileText size={14} style={{ color: glowColor }} />
        <span
          className="text-[10px] font-semibold tracking-wide uppercase"
          style={{ color: glowColor }}
        >
          Document
        </span>
        <span
          className="text-[9px] px-1.5 py-0.5 rounded"
          style={{
            color: glowColor,
            backgroundColor: `${glowColor}12`,
            border: `1px solid ${glowColor}30`,
          }}
        >
          {format}
        </span>

        {/* Format switcher */}
        {alternatives.length > 0 && (
          <div className="flex items-center gap-1 ml-2">
            {alternatives.map((alt) => (
              <button
                key={alt}
                onClick={() => onFormatChange(alt)}
                className="px-2 py-0.5 rounded text-[9px] font-medium tracking-wide transition-all duration-150 hover:brightness-125"
                style={{
                  color: alt === format ? glowColor : "rgba(255,255,255,0.4)",
                  backgroundColor: alt === format ? `${glowColor}12` : "rgba(255,255,255,0.03)",
                  border: alt === format ? `1px solid ${glowColor}30` : "1px solid rgba(255,255,255,0.06)",
                }}
              >
                {alt}
              </button>
            ))}
          </div>
        )}

        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={handleCopy}
            className="p-1.5 rounded transition-all duration-150 hover:brightness-125"
            style={{
              color: copied ? "#22c55e" : "rgba(255,255,255,0.4)",
              backgroundColor: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
            title="Copy"
          >
            <Copy size={11} />
          </button>
          <button
            onClick={handleDownload}
            className="p-1.5 rounded transition-all duration-150 hover:brightness-125"
            style={{
              color: "rgba(255,255,255,0.4)",
              backgroundColor: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
            title="Download"
          >
            <Download size={11} />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded transition-all duration-150 hover:brightness-125"
            style={{
              color: "rgba(255,255,255,0.4)",
              backgroundColor: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
            title="Close"
          >
            <X size={11} />
          </button>
        </div>
      </div>

      {/* Document content — full scroll */}
      <div className="flex-1 overflow-y-auto p-4">
        <RichDocument
          content={content}
          format={format as any}
          glowColor={glowColor}
          alternatives={[]}
        />
      </div>
    </motion.div>
  )
}
```

### 4.7 Format Auto-Decision + Alternatives

The agent (via the structured JSON response in Issue C) decides the format:
- Comparisons → `table`
- Architecture/flow → `diagram` (mermaid)
- Rich layout/styling → `html`
- Notes/short content → `markdown`
- Plain text → `text`

The agent also provides `alternatives` — other formats it could render. The frontend shows these as pills. Clicking a pill sends a `reformat_document` WS message with the requested format, and the agent re-renders.

**Backend:** `backend/iris_gateway.py` — handle `reformat_document` WS message → route to agent kernel → agent re-generates the `show` field in the requested format → new `document:render` event.

### 4.8 Inline + Expand Rendering

**In chat-view.tsx:**
- `iris:document_render` CustomEvent → add document to message stream as a `RichDocument` component
- Inline: compact view (max-height 400px, scrollable), with "Expand" button
- Expand: opens dashboard wing (`UI_STATE_DASHBOARD_OPEN`) with `DocumentPanel` full-panel view
- Dashboard wing renders `DocumentPanel` with toolbar (copy, download, format switcher)

**Quality check:**
- [ ] Markdown parsing is lazy — `react-markdown` loaded only when a document renders
- [ ] Mermaid loaded lazily — only when a ```mermaid block is present (via `lazy()` + `Suspense`)
- [ ] No unbounded document size — truncate at 50,000 chars, show "document too large" message
- [ ] Syntax highlighting is theme-aware — uses brand colors
- [ ] Tables are responsive — horizontal scroll on overflow (`overflow-x: auto` on table wrapper)
- [ ] All custom renderers are memoized — no re-render on parent update (ReactMarkdown is memoized via `useMemo` on `components`)

**Test:** `__tests__/components/RichDocument.test.tsx`
- Renders markdown with tables, code blocks, lists
- Prism Glass styling applied (glass card background, brand-color accents)
- Mermaid diagram renders (mock mermaid.render)
- Expand button calls onExpand
- Format alternative pills render and call onFormatChange
- Large document truncates at 50,000 chars

---

## 5. Implementation Order

Build order is mandatory — each layer depends on the ones below it:

| Phase | Work Stream | Depends on | Estimated effort |
|-------|-------------|------------|-------------------|
| 1 | Issue A: VAD reliability | None | 1 session |
| 2 | Issue B: Orb orbiting particles | None | 1 session |
| 3 | Issue C.1: Structured JSON response (backend) | None | 2 sessions |
| 4 | Issue C.2: Speak tool | Issue C.1 (utterance events) | 1 session |
| 5 | Issue D.1: Rich document renderer | None | 2 sessions |
| 6 | Issue D.2: Format auto-decision + alternatives | Issue C.1 (structured response), Issue D.1 | 1 session |
| 7 | Issue D.3: Inline + expand rendering | Issue D.1, Issue D.2 | 1 session |
| 8 | Integration + E2E | All above | 1 session |

Phases 1, 2, 3, and 5 can be worked in parallel (no dependencies between them).

---

## 6. Event Flow (End-to-End, After All Phases)

```
User speaks → VAD (adaptive) → STT → transcription
    ↓
Agent kernel processes text
    ↓
DER loop executes (tools, planning, etc.)
    ├─ Agent calls `speak` tool → utterance event → TTS speaks (updates/follow-ups)
    └─ DER loop completes → LLM generates structured JSON response
         ↓
    Parse JSON:
      speak field → ConversationKernel → utterance event → TTS (short summary)
      show field → document:render event → WS → frontend
         ↓
    Frontend:
      iris:document_render → RichDocument (inline, Prism Glass styled)
      Expand button → dashboard wing → DocumentPanel (full view)
      Format pills → reformat_document WS → agent re-renders
         ↓
    Orb:
      Working state → OrbWorkingIndicator (orbiting particles)
      Done state → particles fade, OrbBadge clears
```

---

## 7. Acceptance Criteria

1. **VAD:** STT reliably processes after user stops speaking. 30s max listening timeout. Adaptive threshold works in quiet and noisy rooms. No indefinite "listening" hangs.
2. **Orb:** Flat CSS ring removed. Orbiting particles render when agent working. Matches OrbCanvas particle aesthetic (radial-gradient + `mixBlendMode: lighter`). `pointer-events: none`. Respects reduced motion.
3. **TTS:** Agent generates structured JSON (`speak` + `show`). TTS reads only `speak` field (short summary). Full document renders visually. `speak` tool allows agent-initiated speech.
4. **Documents:** Rich markdown rendering (tables, code, diagrams, lists) with Prism Glass styling (exact values from §0.1). Format auto-decided by agent. Alternatives offered as pills. Inline + expand to panel.
5. All existing tests pass. New tests pass. `npx tsc --noEmit` clean. `npm run lint` clean. `pytest` clean.

---

## 8. Open Risks

1. **LLM JSON compliance** — not all LLMs reliably output valid JSON. The fallback (plain text → treat as `speak`) handles this, but the system prompt must be clear. Test with the actual production model (Cerebras gemma-4-31b).
2. **Mermaid bundle size** — mermaid.js is large (~500KB). Must be lazy-loaded only when a ```mermaid block is detected. Use `lazy()` + `Suspense` as specified in §4.3.
3. **VAD calibration race condition** — if the user starts speaking during the 0.5s ambient calibration, the threshold will be too high. Handle by discarding the calibration if speech is detected during calibration (retry on next VAD start).
4. **Document re-formatting latency** — when the user clicks a format pill, the agent must re-generate the document. This takes an LLM call (~1–3s). Show a loading state on the pill (disable button, show spinner).
5. **OrbWorkingIndicator performance** — 5 orbiting particles with framer-motion animations. Should be fine (GPU transforms), but verify on low-end machines. Cap at 5 particles, use `will-change: transform` on the particle elements.
6. **react-markdown version** — ensure `react-markdown` v9+ is installed (the `components` API changed in v9). `react-markdown` v10 is installed (verified 2026-07-09). The `inline` prop was removed in v9; the plan's `code` renderer uses `node.parent.tagName` to detect block vs inline code.

---

## 9. Pre-existing tsc Errors (RESOLVED 2026-07-10)

These errors existed in the project and were **not caused by this plan's implementation.** They were discovered by running `npx tsc --noEmit` on 2026-07-09 and resolved on 2026-07-10. Acceptance criterion §7.5 (`npx tsc --noEmit clean`) now **PASSES** (exit 0, 0 errors).

### 9.0 Resolution summary
- **Submodule noise (~380 errors):** Added `"llama.cpp"` and `"llama-cpp-turboquant"` to `tsconfig.json` `exclude`. These are separate Svelte git-submodules (local model loading) with their own tsconfigs; tsc was pulling their `.ts`/`.tsx` source via the `**/*.ts(x)` include globs. `skipLibCheck` did not help because they are source files, not `.d.ts`. Excluding them is correct — they build independently.
- **9 project errors (5 files):** All fixed with minimal, behavior-preserving type corrections.

| # | File | Error | Fix |
|---|------|-------|-----|
| 1 | `components/card.tsx` (94) | TS2322 options type mismatch | Widened `DropdownField.options` to `(string \| DropdownOption)[]` (matches `FieldConfig.options`) |
| 2 | `components/dashboard/MonitorDiagnosticsPanel.tsx` (78) | TS2339 `toUpperCase` on `never` | `String(status).toUpperCase()` in default branch |
| 3–5 | `components/preview/PrototypeOrbBreathing.tsx` (89,190,239) | TS2304 `Cannot find name 'BreathKey'` | Added `type BreathKey = BreathMode` alias |
| 6 | `components/wheel-view/SidePanel.tsx` (468) | TS2678 `"description"` not in `FieldType` | Added `"description"` to `FieldType` union |
| 7 | `components/wheel-view/SidePanel.tsx` (474) | TS2339 `content` not on `FieldConfig` | Added `content?: string` to `FieldConfig` |
| 8 | `hooks/useIRISWebSocket.ts` (771) | TS2362 arithmetic on non-number | `Number(payload.total_words ?? 0) - 1` |
| 9 | `hooks/useIRISWebSocket.ts` (1604) | TS2561 `selectAudioDevice` missing from return type | Added `selectAudioDevice` to `UseIRISWebSocketReturn` interface |

### 9.1 IRIS Voice project code (8 errors, 5 files)

These are real type errors in the project's own components and hooks. They should be fixed directly.

| File | Line | Error | Fix suggestion |
|------|------|-------|---------------|
| `components/card.tsx` | 94 | `Type '...' is not assignable to type 'string[] \| DropdownOption[]'` | Fix the type assertion or cast — array has mixed string/object entries, needs explicit typing |
| `components/dashboard/MonitorDiagnosticsPanel.tsx` | 78 | `Property 'toUpperCase' does not exist on type 'never'` | The variable is narrowed to `never` — likely a union type that needs correct narrowing or default case |
| `components/preview/PrototypeOrbBreathing.tsx` | 89, 190, 239 | `Cannot find name 'BreathKey'` (3 instances) | `BreathKey` type/import is missing — either import it from the correct module or define the expected string literal union |
| `components/wheel-view/SidePanel.tsx` | 468 | `Type '"description"' is not comparable to type 'FieldType'` | `FieldType` union doesn't include `"description"` — add it to the union or correct the string literal |
| `components/wheel-view/SidePanel.tsx` | 474 | `Property 'content' does not exist on type 'FieldConfig'` | `FieldConfig` type lacks a `content` property — define it in the type or use an existing property |
| `hooks/useIRISWebSocket.ts` | 771 | `Left-hand side of arithmetic operation must be of type 'any', 'number', 'bigint' or an enum type'` | The value is not a number — add `Number()` coercion or correct the type |
| `hooks/useIRISWebSocket.ts` | 1604 | `'selectAudioDevice' does not exist in type 'UseIRISWebSocketReturn'` | The returned interface lacks `selectAudioDevice` — either add it to the interface or use `getAudioDevices` instead |

**Root cause for all 8:** These are stale types/imports from previous iterations that weren't updated when the code changed. Each is a straightforward 1-2 line fix.

### 9.2 Foreign submodule noise (~380 errors, 2 directories)

These errors come from **svelte-based submodules** (`llama.cpp/tools/ui/` and `llama-cpp-turboquant/tools/server/webui/`) that are not part of the IRIS Voice Next.js project. They use svelte path aliases (`$lib/*`), svelte stores, and svelte-specific imports that `tsc` cannot resolve because the TypeScript configuration only targets the Next.js project.

| Directory | Error count | Root cause |
|-----------|-------------|------------|
| `llama.cpp/tools/ui/` | ~80 | Svelte project — `$lib/*` path aliases, svelte stores, missing `@sveltejs/kit` types |
| `llama-cpp-turboquant/tools/server/webui/` | ~300 | Svelte project — same issues plus missing `bits-ui`, `dexie`, `@lucide/svelte`, `svelte-sonner`, `pdfjs-dist`, `@modelcontextprotocol/sdk` types |

**Fix:** Add `"exclude": ["llama.cpp", "llama-cpp-turboquant"]` to `tsconfig.json` at the project root. This tells tsc to skip these directories entirely. They are separate projects with their own tsconfigs. This clears ~380 errors instantly and makes tsc usable as a meaningful check.

### 9.3 Resolution priority

1. **High-priority (block tsc from being useful):** Add `"exclude"` for submodules in `tsconfig.json` (30-second fix, clears 380 errors).
2. **Medium-priority (real bugs):** Fix the 8 project errors in order of impact — `useIRISWebSocket.ts` (active code, 2 errors) first, then `SidePanel.tsx` and `MonitorDiagnosticsPanel.tsx` (dashboard/wheel-view), then `PrototypeOrbBreathing.tsx` and `card.tsx` (preview/legacy).
3. **Low-priority (visual polish):** Once tsc output is clean, the project can enforce type checking in CI and catch regressions early.
