/**
 * BASELINE — Wave 0, specs/task-card-v2-liquid-ink.
 * Pinned behavior as of 2026-08-19 (single-question props, one question
 * visible per card).
 *
 * INVERTED BY T10, 2026-08-19 — SANCTIONED EDIT. `QuestionCard` now renders a
 * REQ-5 question SET: every question in `questions` gets its own header,
 * options and answer control, and a second pending question is no longer
 * invisible — it renders alongside the first, independently answerable. The
 * legacy single-question props (`questionId`/`text`/`options`/`allowOther`)
 * still work as a back-compat fallback (REQ-5 AC6) when `questions` is
 * absent, which is what today's chat-view.tsx still passes.
 */
import "@testing-library/jest-dom"
import { render, screen, fireEvent } from "@testing-library/react"
import { QuestionCard } from "@/components/chat/QuestionCard"

// Mirrors TaskListCard.test.tsx's provider mock: stub the whole hook so the
// component never touches the real context.
jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00c8ff" },
      shimmer: { primary: "#00c8ff" },
      glass: { blur: 20, opacity: 0.18 },
    }),
  }),
}))

jest.mock("framer-motion", () => {
  const React = require("react")
  const motion = new Proxy(
    {},
    {
      get: (_t: unknown, tag: string) =>
        React.forwardRef((props: Record<string, unknown>, ref: unknown) => {
          const { children, ...rest } = props || {}
          return React.createElement(tag, { ...rest, ref }, children)
        }),
    }
  )
  return {
    motion,
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  }
})

describe("QuestionCard — REQ-5 question set model (T10)", () => {
  // RE-INVERTED 2026-08-21 (pre-existing-debt cleanup, pin_c01534199cdb item A2)
  // — SANCTIONED EDIT, CALLED OUT: QuestionCard's onAnswer now carries a
  // THIRD argument, `source` ("click" | "text"), reporting answer provenance
  // (the terminal funnel already sends source:'cli' on question_response).
  // The signature is (questionId, answer, source?) — consumers that ignore
  // the third arg are unaffected. WHAT THESE ASSERTIONS CHECK IS UNCHANGED:
  // EXACT arity and values, so the provenance channel itself stays pinned.
  it("1. legacy single-question props still render one question (REQ-5 AC6 back-compat)", () => {
    render(
      <QuestionCard
        questionId="q1"
        text="Which file should I edit?"
        options={["main.py", "utils.py"]}
        onAnswer={jest.fn()}
      />
    )

    expect(screen.getByText("Which file should I edit?")).toBeInTheDocument()
    expect(screen.getAllByText("Which file should I edit?")).toHaveLength(1)
    expect(screen.getByRole("button", { name: "main.py" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "utils.py" })).toBeInTheDocument()
  })

  it("2. a second pending question in a SET is VISIBLE — every question renders (REQ-5 AC1/AC2, inverts the old baseline)", () => {
    render(
      <QuestionCard
        setId="qs1"
        questions={[
          { questionId: "q1", text: "Which file should I edit?", options: ["main.py"] },
          { questionId: "q2", text: "Should I also update the tests?", options: ["yes", "no"] },
        ]}
        onAnswer={jest.fn()}
      />
    )

    expect(screen.getByText("Which file should I edit?")).toBeInTheDocument()
    expect(screen.getByText("Should I also update the tests?")).toBeInTheDocument()
  })

  it("3. onAnswer fires with (questionId, trimmed answer) on a single-select option click", () => {
    const onAnswer = jest.fn()
    render(
      <QuestionCard
        setId="qs1"
        questions={[{ questionId: "q1", text: "Pick one", options: ["  yes  ", "no"] }]}
        onAnswer={onAnswer}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: /yes/ }))

    expect(onAnswer).toHaveBeenCalledTimes(1)
    expect(onAnswer).toHaveBeenCalledWith("q1", "yes", "click")
  })

  it("3b. onAnswer fires with the trimmed custom answer when allowOther is used", () => {
    const onAnswer = jest.fn()
    render(
      <QuestionCard
        setId="qs1"
        questions={[{ questionId: "q1", text: "Anything else?", allowOther: true }]}
        onAnswer={onAnswer}
      />
    )

    const input = screen.getByPlaceholderText("Type your answer…")
    fireEvent.change(input, { target: { value: "  a custom reply  " } })
    fireEvent.click(screen.getByRole("button", { name: /send/i }))

    expect(onAnswer).toHaveBeenCalledWith("q1", "a custom reply", "text")
  })

  it("4. a multiSelect question answers with a LIST of option strings; a single-select question stays a string (REQ-5 AC3)", () => {
    const onAnswer = jest.fn()
    render(
      <QuestionCard
        setId="qs1"
        questions={[
          { questionId: "q1", text: "Pick a language", options: ["TypeScript", "Python"] },
          {
            questionId: "q2",
            text: "Pick any tools you use",
            options: ["git", "docker", "vscode"],
            multiSelect: true,
          },
        ]}
        onAnswer={onAnswer}
      />
    )

    // Single-select: one click resolves immediately with a plain string.
    fireEvent.click(screen.getByRole("button", { name: "TypeScript" }))
    expect(onAnswer).toHaveBeenCalledWith("q1", "TypeScript", "click")

    // Multi-select: clicking options only toggles a selection; the answer is
    // committed on the explicit Submit control, as a list.
    fireEvent.click(screen.getByRole("button", { name: "git" }))
    fireEvent.click(screen.getByRole("button", { name: "docker" }))
    expect(onAnswer).not.toHaveBeenCalledWith("q2", expect.anything(), expect.anything())
    fireEvent.click(screen.getByRole("button", { name: /submit/i }))
    expect(onAnswer).toHaveBeenCalledWith("q2", ["git", "docker"], "click")
  })

  it("5. one question answered, others pending — the answered question locks and shows its answer; the pending one stays live (REQ-5 edge case)", () => {
    const onAnswer = jest.fn()
    render(
      <QuestionCard
        setId="qs1"
        questions={[
          { questionId: "q1", text: "Which file should I edit?", options: ["main.py", "utils.py"] },
          { questionId: "q2", text: "Should I also update the tests?", options: ["yes", "no"] },
        ]}
        onAnswer={onAnswer}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "main.py" }))

    // q1 is locked and shows its answer; its option buttons are gone.
    expect(screen.queryByRole("button", { name: "main.py" })).not.toBeInTheDocument()
    expect(screen.getByText("main.py")).toBeInTheDocument()
    // q2 is still live — its options remain clickable.
    expect(screen.getByRole("button", { name: "yes" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "no" })).toBeInTheDocument()
  })

  it("6. per-question header renders when present, distinguishing questions in a set (REQ-5 AC4)", () => {
    render(
      <QuestionCard
        setId="qs1"
        questions={[
          { questionId: "q1", text: "Which file?", options: ["a.py"], header: "File choice" },
          { questionId: "q2", text: "Which branch?", options: ["main"], header: "Branch choice" },
        ]}
        onAnswer={jest.fn()}
      />
    )

    expect(screen.getByText("File choice")).toBeInTheDocument()
    expect(screen.getByText("Branch choice")).toBeInTheDocument()
  })

  it("7. empty options with allowOther is free-text only, still valid (REQ-5 edge case)", () => {
    const onAnswer = jest.fn()
    render(
      <QuestionCard
        setId="qs1"
        questions={[{ questionId: "q1", text: "Anything to add?", options: [], allowOther: true }]}
        onAnswer={onAnswer}
      />
    )

    expect(screen.queryAllByRole("button", { name: /submit/i })).toHaveLength(0)
    const input = screen.getByPlaceholderText("Type your answer…")
    fireEvent.change(input, { target: { value: "extra context" } })
    fireEvent.click(screen.getByRole("button", { name: /send/i }))
    expect(onAnswer).toHaveBeenCalledWith("q1", "extra context", "text")
  })
})
