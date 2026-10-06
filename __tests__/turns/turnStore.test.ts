/**
 * Contract: the frontend turn store (execution audit Phase 3).
 *
 * Fixtures are the exact messages the real backend emitter sends
 * (scripts/gen_turn_replay_fixtures.py). Each test replays one through the
 * store and asserts what the chat view will read.
 */
import fs from "fs"
import path from "path"
import {
  EMPTY_TURNS,
  MAX_TURNS,
  partsOf,
  reduceTurnMessage,
  selectConversationTurns,
  type TurnsState,
} from "@/lib/turns/turnStore"
import type { TurnMessage } from "@/lib/turns/protocol"

const FIX = path.join(__dirname, "..", "fixtures", "turns")

function load(name: string): TurnMessage[] {
  return JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8")).messages
}

function replay(messages: TurnMessage[], state: TurnsState = EMPTY_TURNS): TurnsState {
  return messages.reduce(reduceTurnMessage, state)
}

describe("turn store — replay of emitted turns", () => {
  it("files a personal research turn: text, reasoning, card, interaction, todo, final text and speak", () => {
    const s = replay(load("personal_research"))
    const [turn] = selectConversationTurns(s, "conv-personal")
    expect(turn.status).toBe("ok")
    expect(turn.mode).toBe("personal")
    expect(turn.clientRef).toBe("msg-user-1")
    expect(turn.text).toBe("**WhisperX** is the best fit. It is the fastest on your GPU and has word timing.")
    expect(turn.speak).toBe("WhisperX is the best fit.")
    expect(turn.reasoning).toContain("Three engines")
    expect(partsOf(turn, "card")).toHaveLength(1)
    expect(partsOf(turn, "card")[0].data.title).toBe("STT engine comparison")
    expect(partsOf(turn, "interaction").map((p) => p.event)).toEqual(["permission:request", "permission:granted"])
    expect(partsOf(turn, "todo").map((p) => p.event)).toEqual(["task:start", "task:done"])
    expect(turn.expectedParts).toBe(turn.parts.length)
  })

  it("files a developer turn with tool calls, a failed tool, a recovered error and the final text", () => {
    const s = replay(load("developer_fix"))
    const [turn] = selectConversationTurns(s, "conv-dev")
    expect(turn.mode).toBe("developer")
    expect(turn.status).toBe("ok")
    const results = partsOf(turn, "tool_result")
    expect(results.map((r) => r.ok)).toEqual([true, false, true, true])
    const errors = partsOf(turn, "error")
    expect(errors).toHaveLength(1)
    expect(errors[0].recoverable).toBe(true)
    expect(turn.text).toContain("12 router tests pass")
  })

  it("an error turn ends with status error and keeps the error part (the chat must show it)", () => {
    const s = replay(load("error_turn"))
    const [turn] = selectConversationTurns(s, "conv-personal")
    expect(turn.status).toBe("error")
    expect(turn.error).toContain("API returned 429")
    expect(partsOf(turn, "error")[0].message).toContain("API returned 429")
  })

  it("a cancelled turn ends cancelled and keeps the text it streamed", () => {
    const s = replay(load("cancelled_turn"))
    const [turn] = selectConversationTurns(s, "conv-dev")
    expect(turn.status).toBe("cancelled")
    expect(turn.text).toBe("Starting with the planner")
  })

  it("orders parts by seq when the socket reorders them, even across the end", () => {
    const s = replay(load("reordered_delivery"))
    const [turn] = selectConversationTurns(s, "conv-personal")
    expect(turn.parts.map((p) => p.seq)).toEqual([1, 2, 3, 4])
    // turn.end carried no final text, so the text is the deltas in seq order —
    // including the delta that arrived AFTER the end
    expect(turn.text).toBe("Hello, world.")
    expect(turn.status).toBe("ok")
    expect(turn.sawStart).toBe(true)
    expect(turn.prompt).toBe("say hello")
  })
})

describe("turn store — rules", () => {
  const start = (id: string, conv: string): TurnMessage => ({
    type: "turn.start",
    payload: { v: 1, turn_id: id, conversation_id: conv, strand_id: conv, author: "user", to: ["@iris"], refs: [], mode: "personal", prompt: "p", ts: 1 },
  })
  const text = (id: string, conv: string, seq: number, delta: string): TurnMessage => ({
    type: "turn.part",
    payload: { v: 1, turn_id: id, conversation_id: conv, seq, ts: 1, part: { type: "text", delta } },
  })
  const end = (id: string, conv: string, status: "ok" | "error" | "cancelled", parts: number, t = ""): TurnMessage => ({
    type: "turn.end",
    payload: { v: 1, turn_id: id, conversation_id: conv, status, parts, text: t, speak: "", ts: 2 },
  })

  it("files a turn under the conversation the EVENT names, not any other", () => {
    const s = replay([start("t1", "conv-B"), text("t1", "conv-B", 1, "hi"), end("t1", "conv-B", "ok", 1)])
    expect(selectConversationTurns(s, "conv-A")).toEqual([])
    expect(selectConversationTurns(s, "conv-B")).toHaveLength(1)
  })

  it("accepts exactly one end: a replayed or second end changes nothing", () => {
    const s1 = replay([start("t1", "c"), text("t1", "c", 1, "x"), end("t1", "c", "ok", 1, "x")])
    const s2 = reduceTurnMessage(s1, end("t1", "c", "error", 1, "late"))
    expect(s2).toBe(s1)
    expect(s2.byId.t1.status).toBe("ok")
  })

  it("ignores a replayed part (same seq) from the reconnect buffer", () => {
    const s1 = replay([start("t1", "c"), text("t1", "c", 1, "a"), text("t1", "c", 2, "b")])
    const s2 = reduceTurnMessage(s1, text("t1", "c", 2, "b"))
    expect(s2).toBe(s1)
    expect(s2.byId.t1.text).toBe("ab")
  })

  it("keeps a streaming reply whole, however long (no 500-char clamp in the store)", () => {
    const long = "x".repeat(5000)
    const s = replay([start("t1", "c"), text("t1", "c", 1, long), text("t1", "c", 2, "END")])
    expect(s.byId.t1.text).toHaveLength(5003)
    expect(s.byId.t1.status).toBe("running")
  })

  it("the final text on turn.end replaces the streamed deltas", () => {
    const s = replay([start("t1", "c"), text("t1", "c", 1, '{"speak":'), end("t1", "c", "ok", 1, "Clean answer")])
    expect(s.byId.t1.text).toBe("Clean answer")
  })

  it("drops a part numbered past the count turn.end reported, and counts it", () => {
    const s = replay([start("t1", "c"), end("t1", "c", "ok", 0), text("t1", "c", 1, "late")])
    expect(s.byId.t1.parts).toHaveLength(0)
    expect(s.dropped).toBe(1)
  })

  it("counts a malformed message instead of crashing", () => {
    const s = reduceTurnMessage(EMPTY_TURNS, { type: "turn.part", payload: {} } as unknown as TurnMessage)
    expect(s.dropped).toBe(1)
  })

  it("stays bounded: evicts the oldest ended turns past MAX_TURNS, never a running one", () => {
    let s: TurnsState = reduceTurnMessage(EMPTY_TURNS, start("running", "c"))
    for (let i = 0; i < MAX_TURNS + 20; i++) {
      s = replay([start(`t${i}`, "c"), end(`t${i}`, "c", "ok", 0)], s)
    }
    expect(Object.keys(s.byId).length).toBeLessThanOrEqual(MAX_TURNS)
    expect(s.byId.running).toBeDefined()
    expect(s.byId.t0).toBeUndefined()
  })
})
