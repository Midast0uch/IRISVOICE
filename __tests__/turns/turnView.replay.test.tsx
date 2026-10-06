/**
 * Phase 3 DONE line: "An error shows in the chat. Replay tests of recorded
 * turns pass in both modes."
 *
 * Each fixture is what the real backend emitter sends for one turn
 * (scripts/gen_turn_replay_fixtures.py). It is replayed through the turn
 * store, placed into the conversation with mergeLiveTurns (the chat view's
 * timeline step), and rendered with TurnParts in personal AND developer mode.
 */
import fs from "fs"
import path from "path"
import React from "react"
import { render, screen } from "@testing-library/react"
import "@testing-library/jest-dom"
import {
  EMPTY_TURNS,
  reduceTurnMessage,
  selectConversationTurns,
  type TurnRecord,
  type TurnsState,
} from "@/lib/turns/turnStore"
import { mergeLiveTurns, type MergeableMessage } from "@/lib/turns/mergeTurns"
import { TurnParts, latestSentence } from "@/components/chat/turn/TurnParts"
import type { TurnMessage } from "@/lib/turns/protocol"

const FIX = path.join(__dirname, "..", "fixtures", "turns")
const load = (name: string): TurnMessage[] => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8")).messages
const replay = (msgs: TurnMessage[], s: TurnsState = EMPTY_TURNS) => msgs.reduce(reduceTurnMessage, s)
const only = (s: TurnsState, conv: string): TurnRecord => selectConversationTurns(s, conv)[0]

const MODES: Array<[string, boolean]> = [
  ["personal", false],
  ["developer", true],
]

describe.each(MODES)("TurnParts replay — %s mode", (_mode, isDeveloper) => {
  it("an error turn shows its error in the chat, with Retry", () => {
    const turn = only(replay(load("error_turn")), "conv-personal")
    const onRetry = jest.fn()
    render(<TurnParts turn={turn} isDeveloper={isDeveloper} glowColor="#00d4ff" onRetry={onRetry} />)
    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent("API returned 429")
    screen.getByRole("button", { name: "Retry" }).click()
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("a recovered node error is visible and says IRIS tried again (no Retry)", () => {
    const turn = only(replay(load("developer_fix")), "conv-dev")
    render(<TurnParts turn={turn} isDeveloper={isDeveloper} glowColor="#00d4ff" onRetry={() => {}} />)
    expect(screen.getByRole("alert")).toHaveTextContent("tried again")
    expect(screen.getByRole("alert")).toHaveTextContent("_RESERVE is not defined")
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
  })

  it("a cancelled turn says it stopped", () => {
    const turn = only(replay(load("cancelled_turn")), "conv-dev")
    render(<TurnParts turn={turn} isDeveloper={isDeveloper} glowColor="#00d4ff" />)
    expect(screen.getByText(/Stopped/)).toBeInTheDocument()
  })

  it("a running turn shows the latest reasoning sentence; a finished one does not", () => {
    const msgs = load("personal_research")
    const running = only(replay(msgs.slice(0, 3)), "conv-personal") // start, reasoning, todo
    const { unmount } = render(<TurnParts turn={running} isDeveloper={isDeveloper} glowColor="#00d4ff" />)
    expect(screen.getByText(/Three engines, three independent searches/)).toBeInTheDocument()
    unmount()
    const done = only(replay(msgs), "conv-personal")
    render(<TurnParts turn={done} isDeveloper={isDeveloper} glowColor="#00d4ff" />)
    expect(screen.queryByText(/Three engines/)).toBeNull()
    expect(screen.queryByRole("alert")).toBeNull()
  })
})

describe("timeline placement of live turns", () => {
  const user = (id: string, t: number): MergeableMessage => ({ id, text: "q", sender: "user", timestamp: new Date(t) })
  const ph = (t: TurnRecord): MergeableMessage => ({ id: t.id, text: t.text, sender: "assistant", timestamp: new Date(t.startedAt), turn_id: t.id })

  it("puts a streaming turn right under the prompt it answers (client_ref)", () => {
    const turn = only(replay(load("personal_research").slice(0, 3)), "conv-personal")
    const msgs = [user("msg-user-0", 1), user("msg-user-1", 2), user("msg-user-2", 3)]
    const merged = mergeLiveTurns(msgs, [turn], ph)
    expect(merged.map((m) => m.id)).toEqual(["msg-user-0", "msg-user-1", "turn-res-1", "msg-user-2"])
  })

  it("does not add a placeholder once the final message (id === turn id) exists", () => {
    const turn = only(replay(load("personal_research")), "conv-personal")
    const msgs = [user("msg-user-1", 1), { id: "turn-res-1", text: "final", sender: "assistant", timestamp: new Date(2) }]
    expect(mergeLiveTurns(msgs, [turn], ph)).toBe(msgs)
  })

  it("an error turn with no final message still gets its place in the thread", () => {
    const turn = only(replay(load("error_turn")), "conv-personal")
    const merged = mergeLiveTurns([], [turn], ph)
    expect(merged.map((m) => m.id)).toEqual(["turn-err-1"])
  })
})

describe("latestSentence", () => {
  it("returns the last sentence only", () => {
    expect(latestSentence("One. Two? Three")).toBe("Three")
    expect(latestSentence("  ")).toBe("")
  })
})
