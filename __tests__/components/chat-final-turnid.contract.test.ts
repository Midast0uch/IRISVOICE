/**
 * Regression (found live 2026-09-23): the final `chat_message` frame must
 * forward `turn_id` into the `iris:text_response` CustomEvent.
 *
 * Plain replies stream as `chat_chunk` frames keyed by turn_id — the bubble
 * is created with id === turn_id; chat-view's final handler only REPLACES
 * that streaming bubble when the final response carries the same turn_id.
 * When the hook's dispatch omitted it, the reply landed as a NEW message:
 * one turn, two identical bubbles, every plain turn.
 */

import { readFileSync } from "fs"
import { join } from "path"

const SRC = readFileSync(
  join(__dirname, "../../hooks/useIRISWebSocket.ts"),
  "utf8",
)

describe("chat_message -> iris:text_response carries turn_id", () => {
  it("forwards the frame's turn_id into the dispatched detail", () => {
    expect(SRC).toMatch(
      /dispatchEvent\(new CustomEvent\('iris:text_response', \{\s*\n?\s*detail:\s*\{[^}]*turn_id/
    )
  })

  it("still dedupes replayed finals by turn_id before dispatch", () => {
    expect(SRC).toMatch(/seenTurnIdsRef\.current\.has\(_turnId\)/)
  })
})
