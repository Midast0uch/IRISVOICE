/**
 * Execution audit Phase 3 DONE: "replay tests of RECORDED turns pass in both
 * modes". These fixtures are real turns recorded live on 2026-10-06 with
 * IRIS_TURN_RECORD_DIR (scripts/gen_turn_replay_fixtures.py --from-jsonl), not
 * scripted ones: a personal answer, a personal Stop, a developer answer with a
 * tool call, a developer Stop, and a developer turn cut off by a backend restart.
 */
import fs from "fs"
import path from "path"
import { EMPTY_TURNS, endsForLostTurns, partsOf, reduceTurnMessage, type TurnsState } from "@/lib/turns/turnStore"
import type { TurnMessage } from "@/lib/turns/protocol"

const FIX = path.join(__dirname, "..", "fixtures", "turns")
const load = (name: string): TurnMessage[] =>
  JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8")).messages
const replay = (msgs: TurnMessage[]): TurnsState => msgs.reduce(reduceTurnMessage, EMPTY_TURNS)
const only = (s: TurnsState) => {
  const turns = Object.values(s.byId)
  expect(turns).toHaveLength(1)
  return turns[0]
}
const ends = (msgs: TurnMessage[]) => msgs.filter((m) => m.type === "turn.end").length

describe("recorded turns replay through the store (both modes)", () => {
  it("personal answer: one end, ok, the final text, every part arrived", () => {
    const msgs = load("recorded_personal_ok")
    expect(ends(msgs)).toBe(1)
    const t = only(replay(msgs))
    expect(t.mode).toBe("personal")
    expect(t.status).toBe("ok")
    expect(t.text).toContain("Tokyo")
    expect(t.parts).toHaveLength(t.expectedParts ?? -1)
  })

  it("personal Stop: one end, cancelled", () => {
    const msgs = load("recorded_personal_cancelled")
    expect(ends(msgs)).toBe(1)
    const t = only(replay(msgs))
    expect(t.mode).toBe("personal")
    expect(t.status).toBe("cancelled")
  })

  it("developer answer: one end, ok, its tool call and result, the answer", () => {
    const msgs = load("recorded_developer_ok")
    expect(ends(msgs)).toBe(1)
    const t = only(replay(msgs))
    expect(t.mode).toBe("developer")
    expect(t.status).toBe("ok")
    expect(partsOf(t, "tool_call").length).toBeGreaterThan(0)
    expect(partsOf(t, "tool_result").every((r) => r.ok)).toBe(true)
    expect(t.text).toMatch(/18 lines/)
    expect(t.parts).toHaveLength(t.expectedParts ?? -1)
  })

  it("developer Stop: one end, cancelled, the work it did stays filed", () => {
    const msgs = load("recorded_developer_cancelled")
    expect(ends(msgs)).toBe(1)
    const t = only(replay(msgs))
    expect(t.mode).toBe("developer")
    expect(t.status).toBe("cancelled")
    expect(partsOf(t, "todo").length).toBeGreaterThan(0)
  })

  it("developer turn cut off by a backend restart: no end recorded; the page ends it as an error", () => {
    const msgs = load("recorded_developer_lost")
    expect(ends(msgs)).toBe(0)
    let s = replay(msgs)
    expect(only(s).status).toBe("running")
    for (const e of endsForLostTurns(s, "IRIS restarted during this turn")) s = reduceTurnMessage(s, e)
    const t = only(s)
    expect(t.status).toBe("error")
    expect(t.error).toBe("IRIS restarted during this turn")
    expect(partsOf(t, "tool_call").length).toBeGreaterThan(0)
  })
})
