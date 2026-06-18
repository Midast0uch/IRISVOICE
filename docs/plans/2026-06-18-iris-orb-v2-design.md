# IRIS Orb v2 — Design Document

> **For Claude:** Design rationale for the Spiral Dissolve winner that replaces `components/iris/IrisOrb.tsx`.

**Date:** 2026-06-18
**Status:** Winner selected, implementation in progress
**Author:** Iris Orb v2 design session

---

## Problem

The existing `IrisOrb.tsx` (665 lines, framer-motion) is visually beautiful but:

1. **Static** — doesn't reveal the navigation system. Users see a glowing orb with no indication that categories exist.
2. **Two interaction modes only** — click for navigation, double-click for voice. The only hint of *what* you can do is the `ChatActivationText` cycling through three hints near the orb.
3. **No visual feedback for transitions** — the framer-motion orb just changes state. There's no playful reveal of the underlying structure.
4. **Glitch text is hidden** — `PrototypeOrbBreathing` has a `showLabels` prop but it's gated behind a feature flag and never used in production.

The team needed a design that:
- Makes the navigation system *discoverable* through visual structure (hex nodes on an arc).
- Feels playful and alive (random transitions, photon-burst flash).
- Integrates the three primary actions (Menu, Voice, Chat) into the orb's own surface.

---

## Design Exploration

We iterated through **10+ mockup concepts** in `app/orb-preview/page.tsx`, exploring:

### Layout families
| Family | Description | Verdict |
|--------|-------------|---------|
| Radial Hex | 6 hex nodes in a hexagonal arrangement around the orb | Strong, but static |
| Radial Arc | 6 nodes on a half-arc above the orb | Cleaner than full circle |
| Wheel | Circular ring of 8+ nodes | Too crowded for 6 categories |
| Concentric | Inner 3 + outer 3 nodes | Visually busy, weak hierarchy |
| Grid 2×3 | Flat grid below the orb | Felt like a menu, not an orb |

**Radial Arc won** as the base layout — half-arc above the orb keeps the visual focus on the iris itself while revealing the category system.

### Connection styles
| Style | Description | Verdict |
|-------|-------------|---------|
| No lines | Nodes float freely | Lost the "system" feeling |
| Faint lines | Always visible, low opacity | Looked like scaffolding |
| Hover-only lines | Emerge on hover | **Winner** — emergent, not scaffolding |
| Always-visible spokes | Strong energy rays | Too busy, fights the orb |
| Chord web | All-to-all connections | Constellation, not menu |

### Transition variants (9 total)
After locking the base layout, we explored 9 different node-transition animations on orb click:

**Group A (3 variants):**
- **A1 — Magnet Pull** — nodes shrink and get pulled into the orb center sequentially
- **A2 — Photon Burst** — nodes flash white then explode outward with scale + brightness
- **A3 — Orbit Sweep** — nodes break formation and orbit around the orb in a sweeping arc

**Group B (3 variants):**
- **B1 — Pulse Wave** — expanding ring from orb center; nodes vanish as the ring passes
- **B2 — Gravity Drop** — nodes fall downward with acceleration
- **B3 — Shatter** — nodes crack and scatter in random directions

**Group C (3 variants):**
- **C1 — Iris Shutter** — nodes collapse to center with axis-specific squash (later rejected)
- **C2 — Fade + Stagger** — nodes fade out left-to-right (later rejected)
- **C3 — Spiral Dissolve** — nodes spiral outward (+90°, +50px) and fade *(winner)*

The user picked **C3 (Spiral Dissolve)** as the single best transition, then asked to add **Gravity Drop** and **Magnet Pull** as alternates that rotate randomly.

---

## Winner: C — Random Rotate

**Final design:** Each orb click randomly picks one of three transitions — Spiral Dissolve, Gravity Drop, or Magnet Pull. The user never sees the same transition twice in a row. All three share the same Photon Burst flash effect on enter.

### Why random rotation
- **Playfulness** — a deterministic transition feels mechanical. Randomness makes the orb feel alive.
- **Replay value** — users will click repeatedly to see all three.
- **No commitment** — the team didn't have to pick a *single* favorite. All three are good; randomness lets each shine.

### Why not deterministic
- Picking one and sticking with it felt too austere for a "personality orb".
- The user explicitly asked for randomness after seeing the Photon Burst enter effect work well on all three.

### Photon Burst flash (the unifying effect)
Both exit and enter share a brief flash:
- **0–15% of animation** — `brightness: 1 → 3`, `scale: 1 → 1.25`
- **15–100%** — `brightness: 3 → 1`, `scale: 1.25 → 1` (exit) or settle to 1 (enter)

This was borrowed from the Photon Burst transition (A2) — the user noted that A2's flash was the most visually striking part, and asked for it on every transition.

### Enter animation
The enter reverses the chosen exit with the same Photon Burst flash:
- **Spiral exit → spiral enter** — nodes unscrew back into position
- **Gravity exit → gravity enter** — nodes float up from below
- **Magnet exit → magnet enter** — nodes expand outward from center

This was a major fix from the first version, where the enter used a plain CSS transition with no flash — the enter felt muted compared to the energetic exit.

### Clean break
When the animation completes:
- `opacity: 0` + `visibility: hidden` on every node
- SVG, particles, arc lines all hidden via `!isGlitchMode && (...)` wrapper
- Only the PrototypeOrb + glitch text labels remain visible

This was a non-trivial debugging step — the user reported "faint after-image" on Orbit Sweep because the original opacity formula was `1 - orbitAngle / (Math.PI * 1.5) * 0.7` (maxes at 0.3, not 0). Fixed to `1 - t` plus `visibility: hidden` at completion.

---

## Layout & Visual System

### Container sizing
The radial arc mockups were originally 300×300. We scaled them to **246×246** (18% smaller) to fit better in the mockup grid and to feel more like a "compact control" rather than a "hero element". Internal measurements were scaled proportionally (radius 110→90, center 150→123, etc.).

### Node positioning
- 6 nodes at angles `Math.PI + (i / 5) * Math.PI` — half-arc from 180° to 360°
- Radius from center: 90px
- Container: 246×246
- Orb at center: 150×150

### Per-node label offsets
Each node has a unique label offset to avoid clipping at the container edge:
| Index | Category | Label offset | Alignment |
|-------|----------|--------------|-----------|
| 0 | Voice (far left) | dx: -15, dy: 2 | right |
| 1 | Agent (upper-left) | dx: -8, dy: -7 | right |
| 2 | Automate (top-left) | dx: 0, dy: -11 | center |
| 3 | System (top-right) | dx: 0, dy: -11 | center |
| 4 | Customize (upper-right) | dx: 8, dy: -7 | left |
| 5 | Monitor (far right) | dx: 15, dy: 2 | left |

Labels appear on hover only (not persistent), keeping the resting state clean.

### Glitch text labels
Three labels appear centered on the orb during glitch mode:
- **MENU** — top-center, 90px above orb center
- **VOICE** — left of orb center, 70px left
- **CHAT** — right of orb center, 70px right

Each is a `<button>` with a `<GlitchText>` child that scrambles random characters before settling on the final text (720ms duration, 30ms per frame).

---

## Architecture

```
IrisOrbV2 (components/iris/IrisOrbV2.tsx)
├── RadialArcBase (components/iris/radial/RadialArcBase.tsx)
│   ├── Orb (PrototypeOrbBreathing with showLabels)
│   ├── SVG (arc, spokes, hover ring)  [hidden during glitch]
│   ├── Particles                       [hidden during glitch]
│   ├── HexNode × 6 (per-node icons)    [animated by nodeStyle]
│   └── Per-node labels (on hover)      [hidden during glitch]
├── GlitchText × 3 (MENU, VOICE, CHAT) [visible during glitch]
└── State machine
    ├── isGlitch        (true = nodes animating out or gone)
    ├── spiralT         (0→1 exit progress, via requestAnimationFrame)
    ├── enterT          (0→1 enter progress, via requestAnimationFrame)
    └── transitionType  ('spiral' | 'gravity' | 'magnet', random per click)
```

### State machine

```ts
handleOrbClick:
  if isGlitch:
    setIsGlitch(false)       // reveal nodes again
    setSpiralT(0)
    setEnterT(0)
    animateTo(setEnterT, 600ms)   // enter animation
  else:
    setTransitionType(pickRandomTransition(current))  // pick new transition
    setIsGlitch(true)
    animateTo(setSpiralT, 700ms)   // exit animation
```

`pickRandomTransition` filters out the current type and picks one of the other two. This guarantees the user never sees the same transition twice in a row.

### Node style computation

```ts
nodeStyle(idx, pos) => CSSProperties
  if !isGlitch:  // enter or settled state
    reversed = 1 - enterT
    [compute dx, dy, rot based on transitionType]
    flash = photonFlash(enterT)  // brightness 1→3→1, scale 1→1.25→1
    return { transform, opacity: enterT, filter: flash, visibility: visible }
  else:  // exit
    [compute dx, dy, rot based on transitionType and spiralT]
    flash = 1 + min(1, spiralT/0.15) * 2
    return { transform, opacity: 1-spiralT, filter: flash, visibility: spiralT>=1 ? hidden : visible }
```

The `photonFlash` helper is the single source of truth for the flash effect — used identically on both exit and enter for consistency.

---

## Integration with the Live App

### IrisOrb.tsx becomes a re-export shim
The existing `components/iris/IrisOrb.tsx` (665 lines) is replaced with a thin wrapper that delegates to `IrisOrbV2`. This means:
- The live app at `/` (Tauri shell) keeps using the `IrisOrb` import path
- The new visual transitions replace the old framer-motion ones
- The `onCallbacksReady` prop (wake word bridge) is preserved as a stub
- The old `centerLabel` / `voiceStateLabel` text logic is dropped — the new orb doesn't need center text because the glitch labels (MENU/VOICE/CHAT) carry that information

### Three actions wired
- **MENU label click** → `dispatch({ type: 'EXPAND_TO_MAIN' })` — opens navigation level 2 (category selector)
- **VOICE label click** → `startVoiceCommand()` / `endVoiceCommand()` — toggles voice
- **CHAT label click** → `setMainView('chat')` — opens chat view
- **Category node click** → `dispatch({ type: 'EXPAND_TO_MAIN' })` — same as MENU, but for the specific category
- **Double-click orb** → `startVoiceCommand()` / `endVoiceCommand()` — same as VOICE label

### ChatActivationText deprecation
The old `components/chat-activation-text.tsx` (cycling "Tap iris for menu" / "Double-click for🎙️" / "Tap here for chat") is deleted. Its replacement, `ChatActivationGlitch`, is a one-shot hint ("tap the CHAT label to open chat") that dismisses itself when the user clicks it (persisted in localStorage).

### Cadence detection scroll
In the orb-preview page, the MENU label click scrolls to `#cadence-section`. In the live app, the cadence section is a Tauri-only feature, so the scroll is preview-only. The scroll target `id="cadence-section"` was added in earlier work.

---

## Trade-offs & Rejected Ideas

### Why not persist the transition choice?
We could have stored the last-picked transition in localStorage and avoided repeats across sessions. We chose not to because:
- Randomness across sessions is fine — users won't notice or care
- localStorage adds complexity (migration, defaults, edge cases)
- The same-session "no repeat" rule is enough variety

### Why not animate the PrototypeOrb's own appearance during the transition?
The PrototypeOrb already has a "breathing" idle state and "voice active" state. We could have added a "transitioning" state that animates the orb's glow. We chose not to because:
- The win transition is already visually rich (nodes, flash, rotation)
- Adding orb-level animation on top would compete for attention
- The clean break (orb untouched until nodes are gone) gives the orb a moment to breathe

### Why MENU/VOICE/CHAT and not 6 labels for all categories?
The user explicitly requested the 6 category nodes for the arc, plus 3 center labels for the primary actions. This separation makes sense because:
- Category nodes are for *navigating within* the app (Agent, Automate, etc.)
- MENU/VOICE/CHAT are for *primary actions* (open menu, talk, chat)
- Mixing them on the arc would make the arc too crowded
- The center labels act as a "command bar" during glitch mode

### Why not a 1-second pause between exit and enter?
Some prototypes have the orb sit in "glitch mode" for a beat before the user can click again. We chose to allow immediate re-click because:
- Faster interaction feels more responsive
- The animation states are reversible (exit ↔ enter)
- The user can re-click during the exit animation to reverse it

### Why "Random Rotate" as the winner name?
We considered "Winner", "C", "Spiral", "Rotating Transition". "Random Rotate" won because:
- It describes the behavior, not just the visual
- It's distinct from the other sections (no ambiguity)
- It signals to the user that the transition changes each click

---

## Open Questions for Future Iteration

1. **Voice command activation latency** — the double-click path is fast, but the wake-word path (from `onCallbacksReady`) has not been re-wired. Currently the shim passes a no-op `handleWakeDetected`. Future work should re-bridge this to the new orb.

2. **Reduced motion** — the win transition uses `requestAnimationFrame` with no `prefersReducedMotion` check. The `useReducedMotion` hook is imported but unused. Future work should fall back to a plain fade for users with motion sensitivity.

3. **Touch / mobile** — the double-click detection is mouse-only. On touch devices, a tap-and-hold could substitute. Not in scope for v2.

4. **Accessibility** — the glitch text labels are `<button>`s without aria-labels. Future work should add `aria-label` and keyboard navigation.

5. **Theme propagation** — `glowColor` is passed as a prop, but the orb could read it directly from `useBrandColor()`. The prop exists for testability. Keep as-is for now.

---

## Success Criteria

- [x] User can click the orb and see a random transition (spiral/gravity/magnet)
- [x] Photon Burst flash effect on both exit and enter
- [x] MENU/VOICE/CHAT labels appear and are clickable
- [x] Category node clicks open the navigation system
- [x] Double-click starts voice command
- [x] No after-image of nodes after animation completes
- [x] The live app at `/` still works (via re-export shim)
- [x] The orb-preview page showcases the new orb prominently
- [ ] Wake word bridge re-wired to the new orb (future work)
- [ ] Reduced motion fallback (future work)
