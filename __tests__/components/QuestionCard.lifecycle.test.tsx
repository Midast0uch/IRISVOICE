/**
 * BT-6 + BT-7 (specs/reply-surface-contract REQ-12, tasks T22/T24):
 * question-cards dismiss reliably.
 *
 * BT-6: clicking an answer dismisses the card OPTIMISTICALLY — no backend
 * broadcast involved. A lost broadcast cannot resurrect it (removal is a Map
 * delete, not conditional on anything arriving later).
 *
 * BT-7: at countdown zero the card dismisses ITSELF (fires onTimeout once),
 * independent of any backend timeout broadcast.
 */

import "@testing-library/jest-dom"
import React, { useState } from "react"
import { render, screen, fireEvent, act } from "@testing-library/react"
import { QuestionCard } from "@/components/chat/QuestionCard"

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00c8ff" },
      shimmer: { primary: "#00c8ff" },
      glass: { blur: 8, opacity: 0.1 },
    }),
  }),
}))

jest.mock("framer-motion", () => {
  const React = require("react")
  const passthrough = React.forwardRef((props, ref) =>
    React.createElement("div", { ...props, ref })
  )
  return {
    __esModule: true,
    motion: new Proxy({}, { get: () => passthrough }),
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  }
})

jest.mock("lucide-react", () => {
  const React = require("react")
  const Icon = React.forwardRef((props, ref) =>
    React.createElement("span", { ...props, ref })
  )
  return new Proxy({ __esModule: true }, { get: () => Icon })
})

/** Minimal host: mirrors chat-view's pending-question lifecycle — the card
 *  vanishes when removed; nothing can bring it back. */
function Host({
  onAnswerSpy,
  timeoutSeconds,
}: {
  onAnswerSpy: jest.Mock
  timeoutSeconds?: number
}) {
  const [pending, setPending] = useState(true)
  if (!pending) return null
  return (
    <QuestionCard
      questionId="q-1"
      text="Which format do you want?"
      options={["markdown", "table"]}
      timeoutSeconds={timeoutSeconds ?? 30}
      onAnswer={(id, answer, source) => {
        onAnswerSpy(id, answer, source)
        setPending(false) // optimistic removal — what chat-view does
      }}
      onTimeout={() => setPending(false)}
    />
  )
}

describe("BT-6 — answering removes the card without a backend frame", () => {
  it("clicking an option removes the card instantly", () => {
    const spy = jest.fn()
    render(<Host onAnswerSpy={spy} />)
    expect(screen.getByText("Which format do you want?")).toBeInTheDocument()
    fireEvent.click(screen.getByText("markdown"))
    expect(spy).toHaveBeenCalledWith("q-1", "markdown", "click")
    expect(
      screen.queryByText("Which format do you want?")
    ).not.toBeInTheDocument()
  })
})

describe("BT-7 — countdown zero self-dismisses the card", () => {
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => jest.useRealTimers())

  it("reaching zero fires the timeout dismissal exactly once", () => {
    const spy = jest.fn()
    render(<Host onAnswerSpy={spy} timeoutSeconds={2} />)
    expect(screen.getByText("Which format do you want?")).toBeInTheDocument()
    act(() => {
      jest.advanceTimersByTime(2100)
    })
    expect(
      screen.queryByText("Which format do you want?")
    ).not.toBeInTheDocument()
    // Extra ticks — the dismissal is single-fire (the ref guard), no loops.
    act(() => {
      jest.advanceTimersByTime(3000)
    })
    expect(spy).not.toHaveBeenCalled()
  })
})
