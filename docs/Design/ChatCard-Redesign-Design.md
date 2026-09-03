# Chat Card Redesign — Design

**Date:** 2026-07-12
**Status:** Approved (mockup 5)
**Scope:** Visual redesign of the chat-view cards — agent cards (plan / permission / question) and document cards (rich document / document panel / mermaid).
**Mockup:** `card-options-5` (screenshot: `C:\Users\midas\Downloads\card-options-5-2026-07-12T20-37-04-529Z.png`)

---

## 1. Context & problem

The original `TaskListCard` (plan card) and the document cards had two classes of problems:

1. **Plan card** (`components/chat/TaskListCard.tsx`): styling clashed with the chat view; step descriptions used a monospace font and were truncated (`truncate`) so long "run-on" text was cut off instead of wrapped; no real list/bullet structure; the header prefixed every plan with the word "Plan" (`Plan · WebSearch`) which was redundant.
2. **Document cards** (`RichDocument` / `DocumentPanel` / `MermaidDiagram`): inconsistent chrome across formats; no unified header/body system; the format badge and "also as" reformat pills were not part of a single coherent treatment.

The user's requirements for the redesign:
- A **uniform** look across all agent cards that **matches the widget's Prism Glass aesthetic** (it does not have to read as a heavy "card").
- **No run-on text** — proper wrapping, real list/bullet structure, sans-serif body.
- **Action-only headers** — the badge shows the live action (`WEBSEARCH`, `WEBCRAWL`, `DRAFTING`, `ASKING YOU`, …), never the word "Plan".
- The **node glow must track the XurOrb color** — i.e. use the brand glow color, which is dynamic.
- Document cards get the **Refined Prism Glass** treatment across **all 8 renderable document types**.

> **Out of scope (separate workstream):** the agent's ability to *edit/update an already-rendered document* when it learns more (web search) or gets user feedback. That is a backend document-store + `document:render` update-path feature, tracked separately. This design covers only the *visual* layer.

---

## 2. Design tokens (exact aether theme)

All values are taken verbatim from `contexts/BrandColorContext.tsx` (default `aether` theme) so nothing drifts from the rest of the widget.

| Token | Value | Use |
|---|---|---|
| `--glow` (brand glow) | `#00c8ff` | Node/core glow flare, borders, accents, left accent bar. **Dynamic — same source as XurOrb.** |
| `--shimmer` | `hsl(190,100%,60%)` ≈ `#33d6ff` | Secondary accent (code blocks, fresnel). |
| Text primary | `rgba(255,255,255,0.95)` | Body text. |
| Text secondary | `rgba(255,255,255,0.70)` | Meta, captions. |
| Text pending | `rgba(255,255,255,0.45)` | Pending step text. |
| Glass bg | `linear-gradient(135deg, rgba(10,11,22,0.96), rgba(15,16,28,1.0))` | Document card fill. |
| Glass border | `rgba(0,200,255,0.13)` | `1px` border + `2px` left accent. |
| Glass blur | `24px` | `backdrop-filter: blur(24px)`. |
| Status — done | `#34d399` | Green node / glyph. |
| Status — working | `#fbbf24` | Amber node / glyph. |
| Status — failed | `#f87171` | Red node / glyph. |
| Status — pending | `rgba(255,255,255,0.40)` | Dim node / glyph. |

Fonts: `Sora` (sans, body/labels) + `JetBrains Mono` (mono, badges / tool names / meta). Body `12.5px / line-height 1.5`. Badges `9px` uppercase `0.16em` tracking.

---

## 3. Family A — Orbital (agent cards, borderless)

**Used for:** `TaskListCard` (plan), `PermissionCard`, `QuestionCard`.

**Principle:** sits in the chat flow like a message — **no card background, no border, no border-radius**. The only chrome is a small glowing "orb" (the action) and a hairline connector linking step nodes. Deliberately the lightest possible treatment so it reads as part of the conversation, not a UI widget.

### Anatomy
- **Action core:** a `12px` radial-gradient orb (`#aef3ff → var(--glow) → #006b8a`) with a `0 0 12px var(--glow)` flare + inner white highlight. For permission/question the core is `10px`.
- **Header:** core + action badge (`WEBSEARCH` / `WEB_SEARCH` / `ASKING YOU`) + meta (`2 / 5`, `auto 30s`) pushed right. **No "Plan" prefix.**
- **Step list:** each step is a row with a `6px` node (border `1.5px var(--glow)`, `0 0 8px var(--glow)` flare) on a `1px` hairline connector that runs from the core down through every node. The connector is drawn per-node (`node::after`) so it is always perfectly centered.
- **Step text:** sans-serif, `12.5px / 1.5`, **wraps** (never truncated). Pending steps use `text-pending` color. A small mono tool label (`read`, `web_search`) sits under the description.
- **Status:** node border/flare color = status (green/amber/pending). The working node uses amber; done uses green.
- **Actions (permission):** `Allow` / `Deny` buttons (glow / neutral).
- **Options (question):** suggestion pills (neutral border).

### Glow-flare dynamic requirement
Every orb/node flare uses `var(--glow)`, which is bound to the brand glow color from `BrandColorContext` — the **same source that drives the XurOrb**. When the orb color changes (theme switch / user preference), the card nodes change with it. No hardcoded cyan in the components.

---

## 4. Family B — Prism Glass (document cards)

**Used for:** `RichDocument`, `DocumentPanel`, `MermaidDiagram`.

**Principle:** the Refined Prism Glass card — a near-opaque navy glass card with a `2px` left glow accent, a subtle violet "fresnel" edge gradient, and a unified header/body system. One treatment across every document type so the agent's output feels consistent regardless of format.

### Anatomy (shared)
- **Container:** `var(--glass-bg)`, `backdrop-filter: blur(24px)`, `1px` `var(--glass-border)` + `2px` left `var(--glow)` accent, soft inset + drop shadows.
- **Fresnel:** absolute overlay `linear-gradient(90deg, rgba(124,92,255,0.05), transparent 20%, transparent 80%, rgba(124,92,255,0.05))`.
- **Header:** format badge (`MARKDOWN` / `HTML` / `TABLE` / `DIAGRAM` / `TEXT` / `EMAIL` / `VIDEO` / `PICTURE`) + meta (size / source / trust) pushed right.
- **Body:** format-specific content (see below).
- **"Also as" pills:** format alternatives (`markdown` / `table` / `html` / `text` / `mermaid` / `diagram`), current format highlighted.

### The 8 document types
| Type | Badge | Body treatment |
|---|---|---|
| `markdown` | MARKDOWN | Heading + bullet list (glow dot markers) + code block (mono, shimmer text). |
| `html` | HTML | Sanitized rendered HTML inside a bordered box (trusted = raw, else DOMPurify). |
| `table` | TABLE | Styled data table: mono uppercase header row, subtle row dividers. |
| `diagram` | DIAGRAM | Mermaid node-flow rendered as connected node chips (`→` arrows). |
| `text` | TEXT | Plain paragraph, secondary color. |
| `email` | EMAIL | To / From / Subject header block + body. |
| `video` | VIDEO | Thumbnail (gradient placeholder + ▶) + title + duration + source. |
| `picture` | PICTURE | Thumbnail (gradient placeholder) + caption + source line. |

Trust routing is preserved: `trusted` HTML renders raw; web/crawler HTML is DOMPurify-sanitized (existing behavior in `chat-view.tsx`).

---

## 5. Consistency rules (must hold)

- All card colors come from the tokens above — **no off-palette colors** (no separate "frost blue", no "matrix green"; those were rejected directions).
- Agent cards are **borderless**; document cards are **glass**. The two families are intentionally distinct but share the same glow/token system, so they cohere.
- Headers are **action-only** everywhere (no "Plan" / "Card" prefixes).
- Body text **wraps**; truncation is removed from the plan card.
- The node/core glow is **dynamic** (brand color), never hardcoded.

---

## 6. Accessibility

Reuses the existing contrast work in `docs/accessibility-contrast-verification.md`: text on the navy glass meets the required contrast ratios; status colors keep their distinct hues (green/amber/red) plus shape (node fill vs. dim) so they are not color-only signals.
