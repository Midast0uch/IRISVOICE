/**
 * A turn's end settles what the chat still shows as working.
 *
 * Live 2026-10-06: a card's task:done never arrived (withheld, a cancel, a
 * backend restart), the card stayed isWorking, and the composer turned every
 * later message into a steer. turn.end is the one end the backend guarantees,
 * so it settles the card of its turn; and when the backend process changed
 * (initial_state.boot_id), the turns it lost end as errors.
 *
 * Guards: fail on the old code (no iris:turn_end listener; no endsForLostTurns).
 */
import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress, __resetTaskProgressForTests } from "@/hooks/useTaskProgress"
import { EMPTY_TURNS, endsForLostTurns, reduceTurnMessage } from "@/lib/turns/turnStore"
import type { TurnMessage } from "@/lib/turns/protocol"

const fire = (name: string, detail: Record<string, unknown>) =>
  act(() => { window.dispatchEvent(new CustomEvent(name, { detail })) })

beforeEach(() => __resetTaskProgressForTests())

describe("turn.end settles the card of its turn", () => {
  function startCard() {
    fire("iris:conversation_switched", { conversation_id: "conv-1" })
    fire("iris:task_update", {
      type: "task:start", task_id: "turn-1", turn_id: "turn-1", card_id: "card-1", card_relation: "new",
      conversation_id: "conv-1", steps: [{ id: "s1", description: "read a file", status: "working" }], total_steps: 1,
    })
  }

  it("ok: the working card settles; nothing is left working", () => {
    const { result } = renderHook(() => useTaskProgress())
    startCard()
    expect(result.current.cards[0].isWorking).toBe(true)
    fire("iris:turn_end", { turn_id: "turn-1", conversation_id: "conv-1", status: "ok" })
    expect(result.current.cards[0].isWorking).toBe(false)
    expect(result.current.cards.some((c) => c.isWorking)).toBe(false)
  })

  it("an end for ANOTHER turn leaves the card alone", () => {
    const { result } = renderHook(() => useTaskProgress())
    startCard()
    fire("iris:turn_end", { turn_id: "turn-other", conversation_id: "conv-1", status: "ok" })
    expect(result.current.cards[0].isWorking).toBe(true)
  })
})

describe("a restarted backend: running turns end as errors", () => {
  it("endsForLostTurns ends every running turn with an error, keeping its text", () => {
    const start = (id: string): TurnMessage => ({
      type: "turn.start",
      payload: { v: 1, turn_id: id, conversation_id: "conv-1", strand_id: "conv-1", author: "user", to: ["@iris"], refs: [], mode: "developer", prompt: "p", ts: 1 },
    }) as TurnMessage
    let s = reduceTurnMessage(EMPTY_TURNS, start("a"))
    s = reduceTurnMessage(s, {
      type: "turn.part", payload: { v: 1, turn_id: "a", conversation_id: "conv-1", seq: 1, ts: 2, part: { type: "text", delta: "Half an answer" } },
    } as TurnMessage)
    s = reduceTurnMessage(s, start("b"))
    s = reduceTurnMessage(s, {
      type: "turn.end", payload: { v: 1, turn_id: "b", conversation_id: "conv-1", status: "ok", parts: 0, text: "done", speak: "", ts: 3 },
    } as TurnMessage)

    const ends = endsForLostTurns(s, "IRIS restarted during this turn")
    expect(ends).toHaveLength(1) // only the running one
    for (const e of ends) s = reduceTurnMessage(s, e)
    expect(s.byId.a.status).toBe("error")
    expect(s.byId.a.error).toBe("IRIS restarted during this turn")
    expect(s.byId.a.text).toBe("Half an answer")
    expect(s.byId.b.status).toBe("ok")
  })
})

describe("the fold line takes its word from the turn's end", () => {
  // Live 2026-10-06: a stopped turn folded to "✓ DONE" and a turn lost to a
  // restart to "✓ DONE · 1 tried again". Fails on the old code.
  const { buildMatrix, foldLine } = require("@/components/chat/matrix/matrixModel")
  const m = buildMatrix({ objective: "o", steps: [{ id: "a", verb: "read", target: "x", status: "done" }] })

  it("a failed turn folds to FAILED even when its rows finished", () => {
    expect(foldLine(m, false, "0:06", true).word).toBe("FAILED")
  })

  it("a stopped turn (turn status cancelled) folds to STOPPED", () => {
    const { render } = require("@testing-library/react")
    const { TaskCardEntry } = require("@/components/chat/TaskCardEntry")
    const card = {
      cardId: "c1", turnId: "t1", conversationId: "conv-1", isWorking: false, settled: true,
      steps: [{ id: "s1", description: "write", status: "done", toolName: "write_file" }],
      currentStep: 1, totalSteps: 1, durationSec: 6,
    }
    const turn = { id: "t1", status: "cancelled", parts: [], text: "", reasoning: "" }
    const { container } = render(<TaskCardEntry card={card} isDeveloper glowColor="#5cd6ff" matrixElapsedSec={0} turn={turn} />)
    expect(container.querySelector('[data-matrix="folded"]')).toHaveTextContent("STOPPED")
  })
})
