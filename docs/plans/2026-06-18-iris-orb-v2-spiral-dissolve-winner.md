# IRIS Orb v2 — Spiral Dissolve Winner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `components/iris/IrisOrb.tsx` with a new component (`IrisOrbV2.tsx`) that combines the winning Spiral Dissolve prototype (random-rotation transitions, Photon Burst flash, category hex nodes, glitch text) with the existing voice command, cadence detection, and navigation wiring.

**Architecture:** Extract the Spiral Dissolve winner (from `app/orb-preview/page.tsx` → `MockupTransitionSpiral`) into a standalone production component. Keep `IrisOrb.tsx` temporarily as a re-export shim so the live app keeps working. Build a new `IrisOrbV2.tsx` that wraps `RadialArcBase` + a new `WinTransitionEngine` (the spiral/gravity/magnet random-rotation logic) + glitch text labels (MENU/VOICE/CHAT) wired to `useNavigation` for setLevel/setMainView, and `useNavigation().startVoiceCommand` for the double-click path.

**Tech Stack:** Next.js 14 (App Router), React 18, Framer Motion, TypeScript, TailwindCSS, lucide-react, custom hooks (`useNavigation`, `useBrandColor`, `useUILayoutState`, `useReducedMotion`).

---

## Conventions

- **Atomic commits** — one Task = one commit.
- **Run `npx tsc --noEmit` after every edit** — must stay clean.
- **Verify in browser** — `http://localhost:3000/orb-preview` for the preview surface; the live app loads `IrisOrb` so the shim keeps it working.
- **Frequent checkpoints** — commit at the end of every Task, never bundle multiple Tasks into one commit.
- **Test before moving on** — run `npx tsc --noEmit` and confirm `http://localhost:3000/orb-preview` returns 200 before committing.

---

## Task 1: Extract `RadialArcBase` and `WinTransitionEngine` to production

**Files:**
- Create: `components/iris/radial/RadialArcBase.tsx`
- Create: `components/iris/radial/WinTransitionEngine.ts`
- Create: `components/iris/radial/categories.ts`

**Why:** The Spiral Dissolve winner currently lives inside `components/preview/MenuMockups.tsx` and is bundled with the rest of the prototype gallery. Production code must not depend on preview-only code. Move the shared `RadialArcBase`, the `CATEGORIES` constant, and the win-transition logic out so the new orb can import them.

**Step 1: Create `categories.ts`**

Move the `CATEGORIES` constant from `components/preview/MenuMockups.tsx` to `components/iris/radial/categories.ts`. Match the exact array — `{ id, label, icon }` shape.

```ts
// components/iris/radial/categories.ts
import { Mic, Cpu, Zap, Settings, Sliders, Activity } from "lucide-react"
import type { ComponentType } from "react"

export interface CategoryNode {
  id: string
  label: string
  icon: ComponentType<{ size?: number; className?: string }>
}

export const CATEGORIES: CategoryNode[] = [
  { id: "voice",     label: "VOICE",     icon: Mic },
  { id: "agent",     label: "AGENT",     icon: Cpu },
  { id: "automate",  label: "AUTOMATE",  icon: Zap },
  { id: "system",    label: "SYSTEM",    icon: Settings },
  { id: "customize", label: "CUSTOMIZE", icon: Sliders },
  { id: "monitor",   label: "MONITOR",   icon: Activity },
]
```

**Step 2: Create `RadialArcBase.tsx`**

Copy the `RadialArcBase` function and its `NodePosition`/`NodeStyleFn` types from `components/preview/MenuMockups.tsx` (lines 580–720, approximately) into a new file. Keep the SVG, particles, node rendering, and per-node label logic identical. Change imports to point at the new `categories.ts`.

**Step 3: Create `WinTransitionEngine.ts`**

Copy the `WinTransition` type, `photonFlash` helper, and the `MockupTransitionSpiral` transition-style state machine into a pure TS module:

```ts
// components/iris/radial/WinTransitionEngine.ts
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

**Step 4: Verify `MenuMockups.tsx` still compiles**

`MenuMockups.tsx` currently uses its local `RadialArcBase` and `CATEGORIES`. After extraction, it must keep working (don't break the preview page). Two options:
- (a) Leave `MenuMockups.tsx` untouched and let the new `components/iris/radial/` files be duplicates. Acceptable for this Task.
- (b) Re-export from the new location. Skip — over-engineering.

Choose (a). The preview page uses its own copy; production code uses the new files.

Run: `npx tsc --noEmit`
Expected: 0 errors related to the new files.

**Step 5: Commit**

```bash
git add components/iris/radial/
git commit -m "feat(iris): extract RadialArcBase and WinTransitionEngine to production"
```

---

## Task 2: Build `GlitchText` component with scramble animation

**Files:**
- Create: `components/iris/radial/GlitchText.tsx`

**Why:** The PrototypeOrbBreathing component already renders glitch text (MENU/VOICE/CHAT) when `showLabels={true}`. The new orb needs the same labels but positioned at the **center** of the layout — on the orb itself — not around the periphery. Build a standalone component that scrumbles text in/out like PrototypeOrbBreathing but takes explicit position props.

**Step 1: Create `GlitchText.tsx`**

```tsx
"use client"
import { useState, useEffect, useRef } from "react"

const SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←"
const SCRAMBLE_DURATION_MS = 720
const FRAME_MS = 30

export interface GlitchTextProps {
  text: string
  visible: boolean
  color: string
  fontSize?: number
  className?: string
}

export function GlitchText({ text, visible, color, fontSize = 14, className = "" }: GlitchTextProps) {
  const [display, setDisplay] = useState("")
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (!visible || !text) {
      setDisplay("")
      return
    }
    const len = text.length
    const totalFrames = Math.round(SCRAMBLE_DURATION_MS / FRAME_MS)
    let frame = 0
    timerRef.current = setInterval(() => {
      frame++
      let out = ""
      for (let i = 0; i < len; i++) {
        if (frame / totalFrames > i / len) {
          out += text[i]
        } else {
          out += SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)]
        }
      }
      setDisplay(out)
      if (frame >= totalFrames) {
        clearInterval(timerRef.current!)
        timerRef.current = null
        setDisplay(text)
      }
    }, FRAME_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [text, visible])

  return (
    <span
      className={className}
      style={{
        display: "inline-block",
        opacity: visible ? 1 : 0,
        transition: "opacity 0.25s ease",
        fontFamily: "'Courier New', Courier, monospace",
        fontWeight: 700,
        fontSize,
        letterSpacing: "0.18em",
        textTransform: "uppercase",
        color,
        textShadow: `0 0 14px ${color}aa, 0 0 4px ${color}66`,
        whiteSpace: "nowrap",
        pointerEvents: "none",
        userSelect: "none",
      }}
    >
      {display || (visible ? text : "")}
    </span>
  )
}
```

**Step 2: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 3: Commit**

```bash
git add components/iris/radial/GlitchText.tsx
git commit -m "feat(iris): add GlitchText scramble component"
```

---

## Task 3: Build `IrisOrbV2` — the new orb component (skeleton)

**Files:**
- Create: `components/iris/IrisOrbV2.tsx`
- Modify: `components/iris/types.ts` (add `IrisOrbV2Props`)

**Why:** Create the new orb that wraps `RadialArcBase` + the win-transition state machine + the glitch text labels. This Task builds the skeleton with the state machine wired up; later Tasks add voice command and navigation.

**Step 1: Extend `types.ts`**

Add at the end of `components/iris/types.ts`:

```ts
import type { WinTransition } from "./radial/WinTransitionEngine"

export interface IrisOrbV2Props {
  isExpanded: boolean
  onClick: () => void
  onDoubleClick: () => void
  centerLabel: string
  size?: number
  wakeFlash: boolean
  glowColor?: string
  uiState?: UILayoutState
  onCategorySelect?: (categoryId: string) => void
  onMenuClick?: () => void
  onChatClick?: () => void
}
```

**Step 2: Create `IrisOrbV2.tsx` skeleton**

```tsx
"use client"
import { useState, useRef, useCallback, useEffect } from "react"
import { motion } from "framer-motion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { UILayoutState } from "@/hooks/useUILayoutState"
import { CATEGORIES } from "./radial/categories"
import {
  RadialArcBase,
  type NodeStyleFn,
} from "./radial/RadialArcBase"
import {
  WinTransition,
  pickRandomTransition,
  photonFlash,
  WIN_DURATION_MS,
  ENTER_DURATION_MS,
} from "./radial/WinTransitionEngine"
import { GlitchText } from "./radial/GlitchText"
import type { IrisOrbV2Props } from "./types"

const CONTAINER_SIZE = 246
const CENTER = 123
const NODE_RADIUS = 90

export function IrisOrbV2({
  isExpanded,
  onClick,
  onDoubleClick,
  centerLabel,
  size = 200,
  wakeFlash = false,
  glowColor,
  uiState = UILayoutState.UI_STATE_IDLE,
  onCategorySelect,
  onMenuClick,
  onChatClick,
}: IrisOrbV2Props) {
  const theme = useBrandColor().getThemeConfig()
  const resolvedGlow = glowColor || theme.glow.color
  const isWingsOpen =
    uiState === UILayoutState.UI_STATE_CHAT_OPEN ||
    uiState === UILayoutState.UI_STATE_BOTH_OPEN

  const [isGlitch, setIsGlitch] = useState(false)
  const [spiralT, setSpiralT] = useState(0)
  const [enterT, setEnterT] = useState(1)
  const [transitionType, setTransitionType] = useState<WinTransition>("spiral")
  const prefersReducedMotion = useReducedMotion()

  const handleOrbClick = useCallback(() => {
    onClick?.()
  }, [onClick])

  const nodeStyle: NodeStyleFn = (i, pos) => {
    if (!isGlitch) {
      const { brightness, scale } = photonFlash(enterT)
      const reversed = 1 - enterT
      let dx = 0, dy = 0, rot = 0
      if (transitionType === "spiral") {
        const baseAngle = Math.PI + (i / 5) * Math.PI
        const spiralAngle = baseAngle + Math.PI / 2
        dx = Math.cos(spiralAngle) * 50 * reversed
        dy = Math.sin(spiralAngle) * 50 * reversed
        rot = 90 * reversed
      } else if (transitionType === "gravity") {
        const gravity = reversed * 150
        dy = gravity
        rot = reversed * 30 * (i < 3 ? -1 : 1)
      } else {
        const shrink = reversed * 0.8
        return {
          transform: `translate(calc(-50% + ${pos.x * (1 - reversed * 0.8)}px), calc(-50% + ${pos.y * (1 - reversed * 0.8)}px)) scale(${1 - shrink})`,
          opacity: enterT,
          filter: `brightness(${brightness})`,
          visibility: "visible" as const,
          transition: "none",
        }
      }
      return {
        transform: `translate(calc(-50% + ${pos.x + dx}px), calc(-50% + ${pos.y + dy}px)) rotate(${rot}deg) scale(${scale})`,
        opacity: enterT,
        filter: `brightness(${brightness})`,
        visibility: "visible" as const,
        transition: "none",
      }
    }

    const flashT = Math.min(1, spiralT / 0.15)
    const brightness = 1 + flashT * 2
    const scale = 1 + flashT * 0.25
    const done = spiralT >= 1

    if (transitionType === "gravity") {
      const distFromCenter = Math.abs(i - 2.5) / 2.5
      const stagger = distFromCenter * 0.3
      const t = Math.max(0, Math.min(1, (spiralT - stagger) / 0.7))
      const gravity = t * t * 150
      const rot = t * 30 * (i < 3 ? -1 : 1)
      return {
        transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y + gravity}px)) rotate(${rot}deg) scale(${scale})`,
        opacity: done ? 0 : 1 - spiralT,
        filter: `brightness(${brightness})`,
        visibility: done ? "hidden" as const : "visible" as const,
        transition: "none",
      }
    }

    if (transitionType === "magnet") {
      const stagger = i / 5
      const t = Math.max(0, Math.min(1, (spiralT - stagger * 0.4) / 0.6))
      const ease = t * t
      return {
        transform: `translate(calc(-50% + ${pos.x * (1 - ease * 0.8)}px), calc(-50% + ${pos.y * (1 - ease * 0.8)}px)) scale(${1 - ease * 0.8})`,
        opacity: 1 - ease,
        filter: `brightness(${brightness})`,
        visibility: done ? "hidden" as const : "visible" as const,
        transition: "none",
      }
    }

    // spiral
    const baseAngle = Math.PI + (i / 5) * Math.PI
    const angle = baseAngle + spiralT * Math.PI / 2
    const extraR = spiralT * 50
    const dx = Math.cos(angle) * extraR
    const dy = Math.sin(angle) * extraR
    return {
      transform: `translate(calc(-50% + ${pos.x + dx}px), calc(-50% + ${pos.y + dy}px)) rotate(${spiralT * 90}deg) scale(${scale})`,
      opacity: done ? 0 : 1 - spiralT,
      filter: `brightness(${brightness})`,
      visibility: done ? "hidden" as const : "visible" as const,
      transition: "none",
    }
  }

  return (
    <div
      className="relative"
      style={{
        width: CONTAINER_SIZE,
        height: CONTAINER_SIZE,
        filter: isWingsOpen ? "blur(2px)" : "none",
        opacity: isWingsOpen ? 0.6 : 1,
        transition: "filter 0.3s ease, opacity 0.3s ease",
      }}
    >
      <RadialArcBase
        glowColor={resolvedGlow}
        nodeId="iris-v2"
        isGlitchMode={isGlitch}
        onOrbClick={handleOrbClick}
        nodeStyle={nodeStyle}
      />
    </div>
  )
}
```

**Step 3: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: errors only if `RadialArcBase.tsx` exports don't match what we imported. Fix imports as needed.

**Step 4: Commit**

```bash
git add components/iris/types.ts components/iris/IrisOrbV2.tsx
git commit -m "feat(iris): add IrisOrbV2 skeleton with win-transition state machine"
```

---

## Task 4: Wire the click + transition state machine to `IrisOrbV2`

**Files:**
- Modify: `components/iris/IrisOrbV2.tsx`

**Why:** Right now `handleOrbClick` just calls the prop's `onClick`. The win transition requires the orb click to:
1. Pick a random transition type
2. Animate `spiralT` from 0→1 (exit)
3. Animate `enterT` from 0→1 (enter) when the user clicks again
4. Call the `onClick` prop so the parent can update its state

**Step 1: Replace `handleOrbClick` with the full state machine**

```tsx
const rafRef = useRef<number | null>(null)

const cancelRaf = () => {
  if (rafRef.current !== null) {
    cancelAnimationFrame(rafRef.current)
    rafRef.current = null
  }
}

useEffect(() => cancelRaf, [])

const animateTo = (
  setter: (v: number) => void,
  durationMs: number,
  onDone?: () => void
) => {
  cancelRaf()
  let start: number | null = null
  const tick = (ts: number) => {
    if (start === null) start = ts
    const t = Math.min(1, (ts - start) / durationMs)
    setter(t)
    if (t < 1) {
      rafRef.current = requestAnimationFrame(tick)
    } else {
      rafRef.current = null
      onDone?.()
    }
  }
  rafRef.current = requestAnimationFrame(tick)
}

const handleOrbClick = useCallback(() => {
  onClick?.()
  if (isGlitch) {
    setIsGlitch(false)
    setSpiralT(0)
    setEnterT(0)
    animateTo(setEnterT, ENTER_DURATION_MS)
  } else {
    setTransitionType((cur) => pickRandomTransition(cur))
    setIsGlitch(true)
    animateTo(setSpiralT, WIN_DURATION_MS)
  }
}, [isGlitch, onClick])
```

**Step 2: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 3: Commit**

```bash
git add components/iris/IrisOrbV2.tsx
git commit -m "feat(iris): wire click state machine for random win-transition"
```

---

## Task 5: Add the PrototypeOrb + glitch text overlay

**Files:**
- Modify: `components/iris/IrisOrbV2.tsx`

**Why:** The new layout needs the actual PrototypeOrb (the visual orb with the breathing/glow effects) at the center, plus the three glitch text labels (MENU/VOICE/CHAT) positioned around it. These are rendered when `isGlitch` is true, layered on top of the `RadialArcBase`.

**Step 1: Import `PrototypeOrbBreathing`**

Add to the top of `IrisOrbV2.tsx`:

```tsx
import { PrototypeOrbBreathing } from "@/components/preview/PrototypeOrbBreathing"
```

**Step 2: Render the orb + glitch labels inside the container**

Replace the JSX inside the outermost `<div>` with:

```tsx
<>
  <RadialArcBase
    glowColor={resolvedGlow}
    nodeId="iris-v2"
    isGlitchMode={isGlitch}
    onOrbClick={handleOrbClick}
    nodeStyle={nodeStyle}
  />

  {/* PrototypeOrb at center — always visible, with glitch text when isGlitch */}
  <div
    className="absolute"
    style={{
      left: "50%",
      top: "50%",
      width: 150,
      height: 150,
      transform: "translate(-50%, -50%)",
      zIndex: 5,
      pointerEvents: "none",
    }}
  >
    <PrototypeOrbBreathing
      glowColor={resolvedGlow}
      breathMode="D"
      breathLevel={0}
      isBreathing={false}
      showLabels={isGlitch}
    />
  </div>

  {/* Glitch text labels at the center, positioned around the orb */}
  {isGlitch && (
    <>
      <div
        className="absolute"
        style={{
          left: "50%",
          top: "50%",
          transform: "translate(-50%, -90px)",
          zIndex: 6,
        }}
      >
        <GlitchText text="MENU" visible={true} color={resolvedGlow} fontSize={12} />
      </div>
      <div
        className="absolute"
        style={{
          left: "50%",
          top: "50%",
          transform: "translate(calc(-50% - 70px), -50%)",
          zIndex: 6,
        }}
      >
        <GlitchText text="VOICE" visible={true} color={resolvedGlow} fontSize={12} />
      </div>
      <div
        className="absolute"
        style={{
          left: "50%",
          top: "50%",
          transform: "translate(calc(-50% + 70px), -50%)",
          zIndex: 6,
        }}
      >
        <GlitchText text="CHAT" visible={true} color={resolvedGlow} fontSize={12} />
      </div>
    </>
  )}
</>
```

**Step 3: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 4: Manual visual check**

Open `http://localhost:3000/orb-preview`, import `IrisOrbV2` temporarily in the preview page (or use the existing mockup grid), click the orb. You should see the Spiral/Gravity/Magnet random transition play, then the PrototypeOrb with MENU/VOICE/CHAT labels appear at the center.

**Step 5: Commit**

```bash
git add components/iris/IrisOrbV2.tsx
git commit -m "feat(iris): add PrototypeOrb + glitch text overlay to IrisOrbV2"
```

---

## Task 6: Wire voice double-click to startVoiceCommand

**Files:**
- Modify: `components/iris/IrisOrbV2.tsx`

**Why:** The user wants the Voice label (or double-click on the orb) to start voice command. The existing `IrisOrb.tsx` calls `useNavigation().startVoiceCommand()` and `endVoiceCommand()`. Wire the same calls.

**Step 1: Add voice action handlers**

Add to the top of `IrisOrbV2()`:

```tsx
const {
  voiceState,
  startVoiceCommand,
  endVoiceCommand,
} = useNavigation()

const isVoiceActive = voiceState !== "idle"

const handleDoubleClick = useCallback(() => {
  if (isVoiceActive) {
    endVoiceCommand()
  } else {
    startVoiceCommand()
  }
  onDoubleClick?.()
}, [isVoiceActive, startVoiceCommand, endVoiceCommand, onDoubleClick])
```

**Step 2: Pass `handleDoubleClick` to the container**

Add `onDoubleClick={handleDoubleClick}` to the outermost `<div>`:

```tsx
<div
  className="relative"
  onDoubleClick={handleDoubleClick}
  style={{ ... }}
>
```

**Step 3: Verify**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 4: Commit**

```bash
git add components/iris/IrisOrbV2.tsx
git commit -m "feat(iris): wire double-click to startVoiceCommand in IrisOrbV2"
```

---

## Task 7: Wire category node clicks via the inner `HexNode`

**Files:**
- Modify: `components/iris/radial/RadialArcBase.tsx`

**Why:** The current `RadialArcBase` renders `HexNode` with a hover handler but no click handler. We need to add an `onClick` prop so `IrisOrbV2` can pass per-node click handlers that fire `onCategorySelect(id)`.

**Step 1: Add `onCategorySelect` prop to `RadialArcBase`**

In `components/iris/radial/RadialArcBase.tsx`, add to the props interface:

```tsx
onCategorySelect?: (id: string) => void
```

**Step 2: Pass it to `HexNode`**

In the node rendering JSX, add `onClick={() => onCategorySelect?.(cat.id)}`:

```tsx
<HexNode
  glowColor={glowColor}
  icon={cat.icon}
  isActive={!isGlitchMode && hoveredId === cat.id}
  onHover={(v) => !isGlitchMode && setHoveredId(v ? cat.id : null)}
  onClick={() => onCategorySelect?.(cat.id)}
/>
```

**Step 3: Verify `HexNode` supports `onClick`**

Check `components/preview/MenuMockups.tsx` for the `HexNode` definition. If it doesn't accept `onClick`, add the prop. It should be a simple `<button onClick={onClick}>`.

**Step 4: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 5: Commit**

```bash
git add components/iris/radial/RadialArcBase.tsx
git commit -m "feat(iris): pass onCategorySelect through RadialArcBase to HexNode"
```

---

## Task 8: Wire the category node click to `useNavigation().setLevel(2)`

**Files:**
- Modify: `components/iris/IrisOrbV2.tsx`

**Why:** The user wants clicking a category node to open the existing category selector at navigation level 2. The NavigationContext exposes `setLevel` (or `dispatch` with `EXPAND_TO_MAIN`).

**Step 1: Add the navigation handler**

In `IrisOrbV2.tsx`, add to the top of the component body:

```tsx
const { dispatch } = useNavigation() // add `dispatch` to the destructure

const handleCategorySelect = useCallback(
  (categoryId: string) => {
    onCategorySelect?.(categoryId)
    dispatch({ type: "EXPAND_TO_MAIN" })
  },
  [dispatch, onCategorySelect]
)
```

**Step 2: Pass it to `RadialArcBase`**

```tsx
<RadialArcBase
  glowColor={resolvedGlow}
  nodeId="iris-v2"
  isGlitchMode={isGlitch}
  onOrbClick={handleOrbClick}
  onCategorySelect={handleCategorySelect}
  nodeStyle={nodeStyle}
/>
```

**Step 3: Verify**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 4: Commit**

```bash
git add components/iris/IrisOrbV2.tsx
git commit -m "feat(iris): wire category node click to setLevel(2)"
```

---

## Task 9: Wire MENU/VOICE/CHAT glitch labels to navigation actions

**Files:**
- Modify: `components/iris/IrisOrbV2.tsx`

**Why:** The three glitch text labels need to be clickable and trigger the right action:
- **MENU** → dispatch `EXPAND_TO_MAIN` (open navigation level 2)
- **VOICE** → `startVoiceCommand()` (or scroll to cadence section if needed)
- **CHAT** → `setMainView('chat')` (open the chat view)

**Step 1: Replace the glitch label `<div>` blocks with `<button>`s**

```tsx
<button
  type="button"
  className="absolute"
  onClick={onMenuClick ?? (() => dispatch({ type: "EXPAND_TO_MAIN" }))}
  style={{
    left: "50%",
    top: "50%",
    transform: "translate(-50%, -90px)",
    zIndex: 6,
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: 0,
  }}
>
  <GlitchText text="MENU" visible={true} color={resolvedGlow} fontSize={12} />
</button>

<button
  type="button"
  className="absolute"
  onClick={() => {
    if (isVoiceActive) {
      endVoiceCommand()
    } else {
      startVoiceCommand()
    }
  }}
  style={{
    left: "50%",
    top: "50%",
    transform: "translate(calc(-50% - 70px), -50%)",
    zIndex: 6,
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: 0,
  }}
>
  <GlitchText text="VOICE" visible={true} color={resolvedGlow} fontSize={12} />
</button>

<button
  type="button"
  className="absolute"
  onClick={onChatClick ?? (() => {
    // open chat view
    setMainView("chat")
  })}
  style={{
    left: "50%",
    top: "50%",
    transform: "translate(calc(-50% + 70px), -50%)",
    zIndex: 6,
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: 0,
  }}
>
  <GlitchText text="CHAT" visible={true} color={resolvedGlow} fontSize={12} />
</button>
```

Add `setMainView` to the `useNavigation()` destructure.

**Step 2: Verify**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 3: Commit**

```bash
git add components/iris/IrisOrbV2.tsx
git commit -m "feat(iris): wire MENU/VOICE/CHAT glitch labels to navigation actions"
```

---

## Task 10: Build a re-export shim so the live app keeps using `IrisOrb`

**Files:**
- Modify: `components/iris/IrisOrb.tsx`

**Why:** The live app (`app/page.tsx` and friends) imports `IrisOrb` from `components/iris/IrisOrb.tsx`. We can't break the build. Convert `IrisOrb.tsx` to a thin re-export shim that points at the new `IrisOrbV2` while preserving the old prop shape.

**Step 1: Read the current `IrisOrb.tsx` and its callers**

Read `app/page.tsx` (or wherever `IrisOrb` is used) and confirm the prop shape. The current props are: `isExpanded`, `onClick`, `onDoubleClick`, `centerLabel`, `size`, `glowColor`, `wakeFlash`, `uiState`, `onCallbacksReady`.

The new `IrisOrbV2Props` has the same shape minus `onCallbacksReady` (which was the wake-word bridge). We must keep that bridge functional or the app's voice pipeline will break.

**Step 2: Add a wrapper that satisfies the old `IrisOrbProps` interface**

```tsx
// components/iris/IrisOrb.tsx
"use client"

import { useCallback, useEffect, useRef } from "react"
import { useNavigation } from "@/contexts/NavigationContext"
import { IrisOrbV2 } from "./IrisOrbV2"
import type { IrisOrbProps } from "./types"

export function IrisOrb({
  isExpanded,
  onClick,
  onDoubleClick,
  centerLabel,
  size = 200,
  glowColor,
  wakeFlash = false,
  uiState,
  onCallbacksReady,
}: IrisOrbProps) {
  const { startVoiceCommand } = useNavigation()
  const isListeningRef = useRef(false)

  const handleWakeDetected = useCallback(() => {
    if (isListeningRef.current) return
    startVoiceCommand()
  }, [startVoiceCommand])

  const handleNativeAudioResponse = useCallback(
    (payload: Record<string, unknown>) => { /* same as original */ },
    []
  )

  useEffect(() => {
    onCallbacksReady?.({ handleWakeDetected, handleNativeAudioResponse })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <IrisOrbV2
      isExpanded={isExpanded}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      centerLabel={centerLabel}
      size={size}
      glowColor={glowColor}
      wakeFlash={wakeFlash}
      uiState={uiState}
    />
  )
}
```

**Step 3: Verify the live app still works**

Open `http://localhost:3000/` (the main app, not orb-preview). Click the orb — should still trigger the existing navigation. Double-click — should start voice command. The visual transitions should be the new Spiral/Gravity/Magnet random rotation, not the old framer-motion orb.

**Step 4: Commit**

```bash
git add components/iris/IrisOrb.tsx
git commit -m "refactor(iris): convert IrisOrb.tsx to re-export shim wrapping IrisOrbV2"
```

---

## Task 11: Replace `ChatActivationText` functionality with the new CHAT label

**Files:**
- Create: `components/iris/radial/ChatActivationGlitch.tsx` (new)
- Modify: `components/chat-activation-text.tsx` (deprecate)

**Why:** The old `ChatActivationText` cycles through ["Tap iris for menu", "Double-click for🎙️", "Tap here for chat"] near the orb. With the new design, this hint is unnecessary — the CHAT label IS the hint, and clicking it opens chat. Replace the cycling text with a one-shot "tap CHAT label" hint that disappears once the user has clicked chat at least once.

**Step 1: Create `ChatActivationGlitch.tsx`**

```tsx
"use client"
import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { UILayoutState } from "@/hooks/useUILayoutState"

interface ChatActivationGlitchProps {
  uiState: UILayoutState
  navigationLevel: number
  onClick: () => void
}

export const ChatActivationGlitch = function ChatActivationGlitch({
  uiState,
  navigationLevel,
  onClick,
}: ChatActivationGlitchProps) {
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    if (typeof window === "undefined") return
    if (localStorage.getItem("iris-chat-hint-dismissed") === "1") {
      setDismissed(true)
    }
  }, [])

  if (navigationLevel !== 1 || dismissed) return null

  const opacity = uiState === UILayoutState.UI_STATE_IDLE ? 0.7 : 0

  return (
    <motion.p
      className="text-sm font-semibold text-white text-center whitespace-nowrap cursor-pointer"
      style={{ zIndex: 1, pointerEvents: "auto" }}
      animate={{ opacity, scale: [1, 1.02, 1] }}
      transition={{ opacity: { duration: 0.3 }, scale: { duration: 3, repeat: Infinity, ease: "easeInOut" } }}
      whileHover={{ opacity: 1, scale: 1.05 }}
      onClick={() => {
        localStorage.setItem("iris-chat-hint-dismissed", "1")
        setDismissed(true)
        onClick()
      }}
    >
      tap the CHAT label to open chat
    </motion.p>
  )
}
```

**Step 2: Replace the import in `app/page.tsx`**

Find where `ChatActivationText` is imported and replace with `ChatActivationGlitch`. Also change the component name in the JSX.

**Step 3: Delete or deprecate `components/chat-activation-text.tsx`**

Option A: delete the file. Option B: re-export from the new component for backward compat. Choose A — the file is internal to this app.

```bash
rm components/chat-activation-text.tsx
```

**Step 4: Verify**

Run: `npx tsc --noEmit`
Expected: 0 errors after import update.

**Step 5: Commit**

```bash
git add components/iris/radial/ChatActivationGlitch.tsx components/chat-activation-text.tsx app/page.tsx
git commit -m "refactor(iris): replace ChatActivationText with CHAT label hint"
```

---

## Task 12: Add cadence detection scroll target

**Files:**
- Modify: `app/orb-preview/page.tsx` (already has `id="cadence-section"` from prior work)

**Why:** The user wants the Voice action to work with the cadence detection. The orb-preview already has a `cadence-section` div. The new orb's VOICE label (and double-click) should scroll to the cadence section when in preview mode. In the live app, the cadence section is a Tauri-only feature, so the scroll is preview-only.

**Step 1: Add a `scrollToCadence` handler in the preview page**

In `app/orb-preview/page.tsx`, add a callback that the new orb can call:

```tsx
const handleMenuClick = () => {
  // dispatch EXPAND_TO_MAIN — but in preview there's no live nav context
  // so just scroll to the existing section
  const el = document.getElementById("cadence-section")
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
}
```

Pass `onMenuClick={handleMenuClick}` to the new orb in the preview page.

**Step 2: Verify**

Open `http://localhost:3000/orb-preview`, click MENU label — page should scroll to the cadence section.

**Step 3: Commit**

```bash
git add app/orb-preview/page.tsx
git commit -m "feat(orb-preview): wire MENU label click to scroll to cadence section"
```

---

## Task 13: Add the new orb to the orb-preview page

**Files:**
- Modify: `app/orb-preview/page.tsx`

**Why:** The preview page should show the new `IrisOrbV2` as the first/featured item, with the other mockups as reference. This is the only way to visually confirm the new orb works in the live UI shell.

**Step 1: Import `IrisOrbV2`**

```tsx
import { IrisOrbV2 } from "@/components/iris/IrisOrbV2"
```

**Step 2: Add a featured section above the mockup grid**

```tsx
<section className="flex flex-col items-center gap-6 mt-8">
  <h2 className="text-2xl font-bold tracking-wide text-white">
    IRIS Orb v2 — Production Prototype
  </h2>
  <p className="text-sm text-white/60 max-w-md text-center">
    Spiral Dissolve winner. Each click randomly picks spiral, gravity, or magnet. Click MENU/VOICE/CHAT to open. Double-click for voice.
  </p>
  <div className="p-6 rounded-2xl border-2 border-yellow-400/40 bg-black/40">
    <IrisOrbV2
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

**Step 3: Verify**

Open `http://localhost:3000/orb-preview`. The new orb should appear at the top. Click it — random win-transition plays, glitch text appears, click MENU/VOICE/CHAT — labels trigger their actions.

**Step 4: Commit**

```bash
git add app/orb-preview/page.tsx
git commit -m "feat(orb-preview): add IrisOrbV2 as featured production prototype"
```

---

## Task 14: End-to-end visual verification

**Files:** None (verification only)

**Why:** Before declaring done, exercise every interaction in the browser to confirm nothing regressed.

**Step 1: Verify in the preview page**

Open `http://localhost:3000/orb-preview`:
- [ ] Featured `IrisOrbV2` visible at top
- [ ] Click orb once → nodes animate out with random transition (spiral/gravity/magnet)
- [ ] PrototypeOrb appears with MENU/VOICE/CHAT labels scrambling in
- [ ] Click MENU → scrolls to cadence section
- [ ] Click VOICE → starts voice command (only works if backend is running; otherwise no-op is fine)
- [ ] Click CHAT → opens chat view (only works in live app shell; in preview, may no-op)
- [ ] Click orb again → nodes animate back in with Photon Burst flash
- [ ] The mockup grid below is still functional (other variants still render)

**Step 2: Verify in the live app**

Open `http://localhost:3000/`:
- [ ] Orb still renders (via the shim)
- [ ] Single click → navigation toggle works
- [ ] Double click → voice command starts
- [ ] No console errors in DevTools
- [ ] Visual is the new Spiral Dissolve winner, not the old framer-motion orb

**Step 3: Document any failures**

If anything fails, do NOT commit a "fix" silently. Open a new Task to address the failure, with a clear description and minimal patch.

---

## Task 15: Final commit and summary

**Files:** None

**Step 1: Verify no dangling references**

```bash
grep -r "ChatActivationText" components/ app/
grep -r "from '@/components/chat-activation-text'" .
```

Expected: 0 results.

**Step 2: Final type check**

Run: `npx tsc --noEmit`
Expected: 0 errors.

**Step 3: Final commit**

```bash
git add -A
git diff --cached --stat
git commit -m "feat(iris): IRIS Orb v2 — Spiral Dissolve winner replaces IrisOrb

- Extract RadialArcBase and WinTransitionEngine to production
- Build GlitchText scramble component for MENU/VOICE/CHAT labels
- IrisOrbV2: random spiral/gravity/magnet transition with Photon Burst flash on enter
- Voice double-click wired to startVoiceCommand
- Category node click wired to NavigationContext dispatch EXPAND_TO_MAIN
- MENU/VOICE/CHAT labels trigger navigation actions
- IrisOrb.tsx now a re-export shim — no live app breakage
- ChatActivationText replaced with CHAT label hint
- Featured in orb-preview page"
```

---

## Rollback Plan

If Tasks 10–11 break the live app:
1. `git revert` the offending commit
2. The shim approach means `IrisOrb.tsx` always wraps `IrisOrbV2`, so reverting a single commit restores the old behavior

If Tasks 1–9 break the build:
1. Each Task is its own commit — `git revert` the failing Task
2. `MenuMockups.tsx` retains its own copy of `RadialArcBase` (Task 1 option A), so the preview page is never broken

---

## Open Questions

None — all four follow-up questions were answered:
1. Category node click → context dispatch (`EXPAND_TO_MAIN`)
2. Replace existing `IrisOrb.tsx` (via re-export shim)
3. Hardcoded category array (from existing `MenuMockups.tsx`)
4. MENU label → direct context dispatch (`EXPAND_TO_MAIN`)
