/**
 * CT-5 (specs/reply-surface-contract REQ-5 / T14) + bubble-ordering pin
 * (REQ-3 AC3 / T15) — source-level contracts for chat-view.tsx.
 *
 * CT-5: no content-type icon/badge in the chat bubble branches; the type
 * detection itself is KEPT (drives isDocumentMode and other routing) — only
 * the chrome was removed.
 *
 * Ordering: the prism doc-join block must sit physically ABOVE the assistant
 * bubble's content render, so the card leads and the supportive line follows.
 *
 * Source-level on purpose (same pattern as cardChassis.coverage.test.tsx and
 * TerminalSlideOver.test.tsx): chat-view.tsx's full render needs dozens of
 * harness mocks; the contract here is structural — WHERE the code lives.
 */

import { readFileSync } from "fs"
import path from "path"

const CHAT_VIEW = path.resolve(__dirname, "..", "..", "components", "chat-view.tsx")
// Phase 3 split (owner-approved 2026-10-06): the timeline moved out of chat-view.tsx; the shell and its timeline files are read as one source. Assertions unchanged.
const SRC = [
  CHAT_VIEW,
  path.resolve(__dirname, "..", "..", "components", "chat", "Timeline.tsx"),
  path.resolve(__dirname, "..", "..", "components", "chat", "TurnView.tsx"),
  path.resolve(__dirname, "..", "..", "components", "chat", "TaskCardEntry.tsx"),
]
  .map((f) => readFileSync(f, "utf8"))
  .join("\n")

describe("CT-5 — no content-type badge chrome in chat bubbles", () => {
  it("the badge icon is gone as an element and as a component", () => {
    expect(SRC).not.toMatch(/<ContentTypeIcon/)
    expect(SRC).not.toMatch(/const ContentTypeIcon/)
  })

  it("no {contentType} label span remains in the bubble branches", () => {
    expect(SRC).not.toMatch(/<span className="text-\[9px\] text-white\/50 uppercase tracking-wide">\{contentType\}<\/span>/)
  })

  it("content-type DETECTION is retained (getContentType still drives routing)", () => {
    expect(SRC).toMatch(/getContentType/)
    expect(SRC).toMatch(/detectContentType/)
  })
})

describe("REQ-3 AC3 — card leads, supportive bubble follows (T15)", () => {  const docJoinIdx = SRC.indexOf("Inline RichDocument cards for this turn. T15")
  const bubbleIdx = SRC.indexOf("Message content with smart length handling")

  it("both markers exist in the source", () => {
    expect(docJoinIdx).toBeGreaterThan(-1)
    expect(bubbleIdx).toBeGreaterThan(-1)
  })

  it("the doc-join block is positioned BEFORE the bubble content block", () => {
    expect(docJoinIdx).toBeLessThan(bubbleIdx)
  })

  it("the duplicate-suppression guard exists and requires a strictly longer card body", () => {
    expect(SRC).toMatch(/bubbleDuplicatesCard/)
    expect(SRC).toMatch(/startsWith\(_bubbleText\)/)
    // Guard against the emit-failure case: equality means NO card exists, so
    // the bubble is the only copy and must not be suppressed.
    expect(SRC).toMatch(/\(d\.content \|\| ''\)\.trim\(\)\.length > _bubbleText\.length/)
  })
})

describe("REQ-13 AC5 (T18b) — the partial card channel", () => {
  const RICH_DOC = readFileSync(
    path.resolve(__dirname, "..", "..", "components", "chat", "RichDocument.tsx"),
    "utf8",
  )

  it("handleDocumentRender accepts a partial discriminator and suppresses the Updated badge while set", () => {
    expect(SRC).toMatch(/partial\?: boolean/)
    expect(SRC).toMatch(/updated: detail\.partial \? false : /)
  })

  it("DocRender carries partial and RichDocument receives it", () => {
    expect(SRC).toMatch(/partial=\{doc\.partial\}/)
  })

  it("RichDocument exposes the partial prop and renders partial cards open", () => {
    expect(RICH_DOC).toMatch(/partial\?: boolean/)
    expect(RICH_DOC).toMatch(/defaultCollapsed=\{partial \? false : defaultCollapsed\}/)
  })
})

const ASK_TOOL = readFileSync(
  path.resolve(__dirname, "..", "..", "backend", "agent", "tools", "ask_user_tool.py"),
  "utf8",
)

describe("CT-8 — question cards anchor to their turn (REQ-11, T21)", () => {
  it("QUESTION_ASK payloads carry turn_id in DATA (the WS bridge drops the event-level id)", () => {
    expect(ASK_TOOL).toMatch(/"turn_id": turn_id/)
    expect(SRC).toMatch(/turnId: detail\.turn_id/)
  })

  it("a pending question whose turn owns a message renders inline and is excluded from the bottom block", () => {
    expect(SRC).toMatch(/anchoredQuestionIds/)
    expect(SRC).toMatch(
      /q\.turnId === message\.id \|\| q\.turnId === message\.turn_id/
    )
    expect(SRC).toMatch(/\.filter\(\(q\) => !anchoredQuestionIds\.has\(q\.questionId\)\)/)
  })
})

describe("CT-9 — question cards dismiss reliably (REQ-12, T22)", () => {
  it("onAnswer removes the card optimistically, before the backend round trip", () => {
    const answerIdx = SRC.indexOf("onAnswer={(id, answer, source) =>")
    const removalIdx = SRC.indexOf("removePendingQuestion(id)")
    expect(answerIdx).toBeGreaterThan(-1)
    expect(removalIdx).toBeGreaterThan(answerIdx)
  })

  it("a finalized reply dismisses its turn's pending questions (AC3)", () => {
    expect(SRC).toMatch(/q\.turnId === turnId/)
  })

  it("the backend-resolution handler is idempotent", () => {
    expect(SRC).toMatch(/removePendingQuestionRef\.current\(detail\.question_id\)/)
  })
})

describe("CT-13 — hydrated card body fetches on expand (REQ-17, T27/T28)", () => {
  const RICH_DOC = readFileSync(
    path.resolve(__dirname, "..", "..", "components", "chat", "RichDocument.tsx"),
    "utf8",
  )
  const PANEL = readFileSync(
    path.resolve(__dirname, "..", "..", "components", "chat", "DocumentPanel.tsx"),
    "utf8",
  )
  const WS = readFileSync(
    path.resolve(__dirname, "..", "..", "hooks", "useIRISWebSocket.ts"),
    "utf8",
  )

  it("the gateway's single-document body read is wired end to end", () => {
    expect(SRC).toMatch(/'get_document_body',/)
    expect(WS).toMatch(/case "document_body"/)
  })

  it("body-less but store-backed cards stay in the timeline (fetchable on expand)", () => {
    expect(SRC).toMatch(/\(\(d\.content \|\| ''\)\.trim\(\)\.length > 0 \|\| !!d\.documentId\)/)
    expect(RICH_DOC).toMatch(/hasBody \|\| expandable/)
    expect(SRC).toMatch(/expandable=/)
  })

  it("the panel offers loading / unavailable / retry states", () => {
    expect(PANEL).toMatch(/bodyState\?: "ready" \| "loading" \| "unavailable"/)
    expect(PANEL).toMatch(/onRetry/)
    expect(SRC).toMatch(/retryDocumentBody/)
  })

  it("the body response merges into the existing card only (no new emit, no duplicate)", () => {
    expect(SRC).toMatch(/iris:document_body/)
    expect(SRC).toMatch(/d\.documentId === detail\.document_id/)
  })
})
