# Plan — Chat Card Redesign (Orbital + Prism Glass)

**Date:** 2026-07-12
**Design:** `docs/Design/ChatCard-Redesign-Design.md` (approved, mockup 5)
**Goal:** Replace the plan/permission/question cards with a borderless **Orbital** treatment and the document cards with a **Prism Glass** treatment, using exact aether tokens and a dynamic (orb-tracking) glow.

---

## Phase 1 — Agent cards → Orbital (borderless)

**Files:** `components/chat/TaskListCard.tsx`, `components/chat/PermissionCard.tsx`, `components/chat/QuestionCard.tsx`, `components/chat-view.tsx` (render sites only if prop shapes change).

1. **Token wiring (prep).** Confirm `TaskListCard`/`PermissionCard`/`QuestionCard` consume `glowColor` from `BrandColorContext` (the same source as `XurOrb`). The node/core flare must use `glowColor`, never a hardcoded hex. If a component currently hardcodes a color, thread `glowColor` through.
2. **`TaskListCard.tsx` rewrite.**
   - Remove card background / border / `border-radius` / glass — render **borderless** (chat-flow).
   - Header: `12px` radial-gradient core (flare = `glowColor`) + **action-only badge** (derive from active tool via existing `TOOL_TITLES`, e.g. `WEBSEARCH`; **drop the `Plan ·` prefix**) + `done/total` meta right-aligned.
   - Step list: `6px` nodes on a `1px` hairline connector (per-node `::after` so it stays centered); sans-serif body that **wraps** (remove `truncate`); small mono tool label; node border/flare = status color (green/amber/pending).
   - Keep collapse-when-`>4`-steps behavior, but borderless.
3. **`PermissionCard.tsx` rewrite.** Borderless Orbital: `10px` core + content + `Allow`/`Deny` (glow / neutral). Keep existing grant/deny/confirm handlers.
4. **`QuestionCard.tsx` rewrite.** Borderless Orbital: `10px` core + question text + option pills (neutral border). Keep existing option-select handler.
5. **`chat-view.tsx`.** Verify render sites (`taskProgress.steps.length > 0`, `pendingPermissions`, `pendingQuestions`) still pass the same props; adjust only if a prop was renamed.

## Phase 2 — Document cards → Prism Glass

**Files:** `components/chat/RichDocument.tsx`, `components/chat/DocumentPanel.tsx`, `components/chat/MermaidDiagram.tsx`.

6. **`RichDocument.tsx` restyle.** Glass container (`var(--glass-bg)`, `blur(24px)`, `1px` border + `2px` left `glowColor` accent) + fresnel overlay + unified header (format badge + meta) + body per type (markdown/html/table/diagram/text/email/video/picture — see design doc §4) + "also as" format pills (current highlighted). Preserve format switching + trust routing (trusted raw, else DOMPurify).
7. **`DocumentPanel.tsx` restyle.** Same glass + fresnel; toolbar (copy/download/close + format switcher) unchanged in behavior.
8. **`MermaidDiagram.tsx` restyle.** Wrap in the glass card; keep lazy load + render.

## Phase 3 — Verification

9. `npx tsc --noEmit` (clean), `npm run lint` (clean), `npm test` (passing).
10. **Visual:** run the dev server, screenshot the chat view with a live plan + permission + question + one of each document type; compare to mockup 5 (`card-options-5`). Confirm: borderless agent cards, wrapping step text (no truncation), action-only headers, glass document cards for all 8 types.
11. **Dynamic glow:** switch the orb/brand color (theme) and confirm card nodes/cores shift with it.

## Phase 4 — (Separate, future) Document editing feature

The user's second concern — the agent should be able to **edit/update an already-rendered document** when it learns more (web search) or gets user feedback — is a *feature*, not styling. It is intentionally **out of scope** for this plan and tracked as its own workstream:
- Backend: extend `document:render` so re-emission by `turn_id`/`document_id` updates **content** (not just format), and the agent can append/revise.
- Frontend: `RichDocument`/`DocumentPanel` reflect content updates (already updates by `turn_id`; extend to content edits + a subtle "updated" indicator).
- A dedicated plan will be written before implementation.

---

## Risks / notes
- **Token drift:** the only way to break consistency is hardcoding a color. Enforce `glowColor` from context everywhere.
- **Collapse UX:** borderless collapse must still be discoverable (header remains the toggle).
- **Perf:** glass `backdrop-filter: blur(24px)` is already used elsewhere; no new cost.
- **Trust:** document HTML sanitization must remain intact through the restyle.
