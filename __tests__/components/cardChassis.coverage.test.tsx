/**
 * CT-10 — CHASSIS COVERAGE GUARD (REQ-2 AC8, design.md Testing Strategy).
 *
 * This exists because THIS SPEC HAD THE BUG ITSELF: its first draft restyled
 * four cards and missed `DocumentPanel` (the EXPANDED form of RichDocument,
 * `chat-view.tsx:3606`) — so expanding a document jumped style
 * mid-interaction. Landed WITH T8, not last, per tasks.md's explicit note:
 * "any card left behind fails immediately rather than at review."
 *
 * STATIC SOURCE INSPECTION, not rendering. Every card here pulls in its own
 * heavy deps (BrandColorContext, dompurify, react-markdown, ...) — grep'ing
 * the source for the chassis import is a lighter, more stable signal than
 * mounting five unrelated components just to prove "does this file use
 * CardChassis", and it survives internal refactors of those files.
 *
 * TWO ALLOWLISTS, kept deliberately disjoint (see "unclassified surface"
 * test below):
 *   - CARD_PATH_SURFACES: MUST render through CardChassis (REQ-2 AC1/AC3).
 *   - NON_CARD_ALLOWLIST: the MESSAGE path (REQ-2 AC7) — plan/system/error
 *     messages, message body, pills, chips, diagrams nested in RichDocument.
 *     MUST NEVER touch CardChassis; carding them would merge the two paths
 *     the design deliberately keeps apart.
 *
 * HOW THIS STAYS HONEST WITHOUT EVER BEING EDITED AGAIN (T9-T11a have not
 * landed as of T8):
 *   - The per-surface `it.each` rows below are RED today for all five
 *     CARD_PATH_SURFACES, by design — nobody has migrated a card yet. As
 *     each of T9/T10/T11/T11a lands and that file gains
 *     `import { CardChassis } from "@/components/chat/CardChassis"`, its OWN
 *     row flips green on the next run. No line in this file changes.
 *   - The MESSAGE-PATH guard and the "no unclassified surface" guard are
 *     real, always-on assertions that pass today and would fail the moment
 *     someone cards a message-path surface or drops a brand-new file into
 *     `components/chat/` without triaging it into one of the two lists
 *     above — that triage IS what makes a new card-path surface visible
 *     (it lands in CARD_PATH_SURFACES) and, until migrated, red.
 *   - This is intentionally NOT `expect(true).toBe(true)`: the assertions
 *     read real files on disk and can genuinely fail in both directions.
 */

import fs from "fs"
import path from "path"

const REPO_ROOT = path.resolve(__dirname, "..", "..")
const CHAT_DIR = path.join(REPO_ROOT, "components", "chat")
const CHASSIS_IMPORT_PATTERN = /CardChassis/

function readSource(relPath: string): string {
  return fs.readFileSync(path.join(REPO_ROOT, relPath), "utf8")
}

// ── The allowlist (REQ-2 AC8) ───────────────────────────────────────────────

/** CARD-PATH surfaces — every one of these MUST render through CardChassis.
 *  This literal list is the "explicit allowlist" the spec's own audit built
 *  after missing DocumentPanel on the first pass; extending it is how a
 *  future card type gets checked at all. */
const CARD_PATH_SURFACES: Array<{ name: string; file: string; owner: string }> = [
  { name: "TaskListCard", file: "components/chat/TaskListCard.tsx", owner: "T9" },
  { name: "QuestionCard", file: "components/chat/QuestionCard.tsx", owner: "T10" },
  { name: "PermissionCard", file: "components/chat/PermissionCard.tsx", owner: "T11" },
  { name: "RichDocument", file: "components/chat/RichDocument.tsx", owner: "T11" },
  {
    name: "DocumentPanel",
    file: "components/chat/DocumentPanel.tsx",
    owner: "T11a — MISSED IN THE FIRST DRAFT; this is the row that catches it",
  },
]

/** MESSAGE-PATH / non-card surfaces (REQ-2 AC7) — `Message.sender` is
 *  `"user" | "assistant" | "error" | "system"` (chat-view.tsx), plan events
 *  are system messages (`planEventMessage.ts`), and pills/chips/diagrams are
 *  chrome, not cards. None of these may ever import CardChassis. */
const NON_CARD_ALLOWLIST: string[] = [
  "components/chat/planEventMessage.ts",
  "components/chat/MarkdownMessage.tsx",
  "components/chat/ContextPill.tsx",
  "components/chat/SuggestionPills.tsx",
  "components/chat/ConversationChips.tsx",
  "components/chat/MermaidDiagram.tsx",
]

/** The chassis implementation itself — neither a card surface (nothing to
 *  migrate) nor a message-path exemption (it obviously references its own
 *  name). Excluded from both lists so the "unclassified surface" scan below
 *  doesn't flag it. */
const CHASSIS_INFRA_FILES = ["components/chat/CardChassis.tsx"]

describe("CT-10 — chassis coverage guard (REQ-2 AC8)", () => {
  describe("card-path surfaces render through CardChassis", () => {
    it.each(CARD_PATH_SURFACES)(
      "$name ($file) imports CardChassis — owned by $owner",
      ({ file }) => {
        const source = readSource(file)
        expect(source).toMatch(CHASSIS_IMPORT_PATTERN)
      }
    )
  })

  describe("message path stays plain (REQ-2 AC7) — MUST fail if this ever changes", () => {
    it.each(NON_CARD_ALLOWLIST.map((file) => ({ file })))(
      "$file never references CardChassis",
      ({ file }) => {
        const source = readSource(file)
        expect(source).not.toMatch(CHASSIS_IMPORT_PATTERN)
      }
    )

    it("chat-view.tsx keeps the two-path Message.sender contract intact", () => {
      // Pins the exact union from requirements.md's "THE TWO PATHS" note.
      // Widening this (e.g. adding a "card" sender) would be the concrete
      // sign of merging the message path into the card path — REQ-2 AC7
      // forbids exactly that.
      const source = readSource("components/chat-view.tsx")
      expect(source).toMatch(/sender:\s*"user"\s*\|\s*"assistant"\s*\|\s*"error"\s*\|\s*"system"/)
    })

    it("plan/system/error message renderers in chat-view.tsx do not construct a CardChassis element", () => {
      const source = readSource("components/chat-view.tsx")
      // formatPlanEventMessage() output is pushed as a message (sender:
      // "system"); assert the message-construction sites that use it stay
      // free of any chassis element construction nearby.
      expect(source).toMatch(/formatPlanEventMessage/)
      expect(source).not.toMatch(/<CardChassis[\s/>]/)
    })
  })

  describe("no unclassified surface can hide in components/chat/", () => {
    const known = new Set<string>([
      ...CARD_PATH_SURFACES.map((s) => path.basename(s.file)),
      ...NON_CARD_ALLOWLIST.map((f) => path.basename(f)),
      ...CHASSIS_INFRA_FILES.map((f) => path.basename(f)),
    ])

    it("every non-test file in components/chat/ is triaged into a known list", () => {
      const entries = fs
        .readdirSync(CHAT_DIR)
        .filter((f) => (f.endsWith(".ts") || f.endsWith(".tsx")) && !f.includes(".test."))

      const unclassified = entries.filter((f) => !known.has(f))

      // A brand-new file landing here with neither classification is exactly
      // the failure mode this guard exists to catch: it forces a human to
      // decide "card path" (add to CARD_PATH_SURFACES, and it is red until
      // migrated) or "message path" (add to NON_CARD_ALLOWLIST, and it must
      // never import CardChassis) before it can exist unexamined.
      expect(unclassified).toEqual([])
    })
  })
})
