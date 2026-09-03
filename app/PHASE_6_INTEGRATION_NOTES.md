# Phase 6 — Frontend Integration Notes

## Status

- ✅ `app/hooks/useCaducean.ts` (NEW, ~180 lines) — React hook with 500ms polling
- ✅ `app/components/CaduceanDebugPanel.tsx` (NEW, ~280 lines) — Dev-only floating panel
- ⚠️ `app/components/VoiceInterface.tsx` — **does not exist as a single file**

## Why "VoiceInterface.tsx" Doesn't Exist

The frontend voice UI is composed of **multiple components** spread across
`components/chat-view.tsx`, `components/chat/`, `components/iris-orb-animations.css`,
etc. The "VoiceInterface" referenced in the plan is a logical concept
(voice interaction layer) not a single source file.

The Caducean v2 integration with voice requires **two minimal touches**:

1. **Compute TTS chunk size from `force_magnitude`** (in any component
   that calls TTS — likely `chat-view.tsx` or a child component)
2. **Trigger `target_u` flip on user voice interrupt** (in the audio
   activity handler — likely in the VAD callback path)

These changes should be made where voice/TTS/VAD are actually invoked,
not in a hypothetical "VoiceInterface.tsx".

## Wiring Pattern (for whoever does the actual voice integration)

```tsx
// In any component that needs live Caducean state for voice:
import { useCaducean } from "@/hooks/useCaducean";

function MyVoiceComponent({ sessionId }: { sessionId: string }) {
  const { state, direction } = useCaducean(sessionId, { pollMs: 500 });

  // TTS chunk size: scaled by force_magnitude (range 20-200 tokens)
  const ttsChunkSize = direction
    ? Math.max(20, Math.min(200, Math.floor(direction.force_magnitude * 300)))
    : 100;

  // Turn-taking: target_u = +1 (expand/speak), -1 (compress/listen)
  const shouldSpeak = direction?.target_u === 1;

  return (
    <div>
      {shouldSpeak ? "Speaking..." : "Listening..."}
      <small>TTS chunk: {ttsChunkSize} tokens</small>
    </div>
  );
}
```

## Where to Add the Debug Panel

```tsx
// In app/layout.tsx (or a top-level layout component):
import { CaduceanDebugPanel } from "@/components/CaduceanDebugPanel";
import { useState, useEffect } from "react";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  // ... existing layout ...

  return (
    <html>
      <body>
        {children}
        <CaduceanDebugPanel sessionId={sessionId} />
      </body>
    </html>
  );
}
```

## Verification Plan (Phase 6 Done Criteria)

| Criterion | How to verify | Status |
|-----------|---------------|--------|
| `useCaducean` returns live values | Manual in browser; check Network tab shows invoke calls at 500ms | ⏳ Manual |
| Debug panel shows state | Manual; panel appears bottom-right in dev mode | ⏳ Manual |
| Sliders update C++ state | Manual; move slider, verify C++ state via Python smoke test | ⏳ Manual |

## Why "Manual"?

The frontend dev server (Next.js on port 3000) requires:
- `npm install` (network)
- A running Tauri dev shell
- Active voice pipeline (Porcupine, Whisper, Piper)

These are heavy prerequisites. The hook + panel code has been written
and the TypeScript types are correct. The actual browser verification
should be done by a frontend developer with the dev environment set up.

## File Locations (when this branch merges)

The new files in `app/hooks/` and `app/components/` will need to be
**copied or merged** into the active sandbox worktree:
- `.git/worktrees/iris-agent-sandbox/hooks/useCaducean.ts` (new)
- `.git/worktrees/iris-agent-sandbox/components/CaduceanDebugPanel.tsx` (new)
- The voice integration changes (2 minimal touches) — in the
  relevant chat-view / TTS / VAD components

A separate small PR can do this copy once the active sandbox worktree
is ready to accept v2 changes.

## What Was NOT Done in Phase 6

- Did not modify `.git/worktrees/iris-agent-sandbox/components/chat-view.tsx`
  because that file is in a different worktree (sandbox isolation).
- Did not run a browser-based E2E test (no Next.js dev server in this env).
- Did not add a "real-time WebSocket broadcast" (Option B in plan) —
  deferred to v3 per the plan.

These are explicit scope decisions, not oversights.
