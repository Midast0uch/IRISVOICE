import "@testing-library/jest-dom"
import { render, screen, fireEvent } from "@testing-library/react"
import TaskListCard from "@/components/chat/TaskListCard"

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

jest.mock("@/components/Xur", () => ({
  Xur: (props: { size?: number; color?: string; speed?: number }) => (
    <div data-testid="xur" data-color={props.color} data-size={props.size} />
  ),
}))

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00c8ff" },
      shimmer: { primary: "#00c8ff" },
      glass: { blur: 20, opacity: 0.18 },
    }),
  }),
}))

const steps = [
  { id: "s1", description: "Read the file", status: "done", toolName: "file_read" },
  { id: "s2", description: "Write the file", status: "working", toolName: "file_write" },
  { id: "s3", description: "Commit", status: "pending", toolName: "git_commit" },
]

describe("TaskListCard", () => {
  it("renders all steps when not collapsed", () => {
    render(<TaskListCard steps={steps} />)
    expect(screen.getByText("Read the file")).toBeInTheDocument()
    expect(screen.getByText("Write the file")).toBeInTheDocument()
    expect(screen.getByText("Commit")).toBeInTheDocument()
  })

  // CHANGED 2026-08-19 — CALLED OUT DELIBERATELY, not a silent fix.
  // This test pinned the OLD counter semantics (doneCount/total). The card now
  // renders deriveCurrentStep(steps)/total so the card and the orb agree on which
  // step is in flight — a running step is the step you are ON. The fixture is
  // [done, working, pending], so the current step is 2, not 1.
  // The assertion is still an exact string match and the name now describes what
  // it actually checks. The progress BAR still uses doneCount; only the COUNTER moved.
  // UPDATED AGAIN 2026-08-19 — CALLED OUT DELIBERATELY.
  // The T8 chassis owns the bracketed counter, so the card briefly rendered TWO
  // fractions in one header row: the chassis's "[1/3]" (doneCount) beside this
  // inline "2/3" (current step). Two disagreeing 9px mono numbers, unlabelled.
  // Resolved to ONE counter — the chassis bracket, carrying the current step so
  // the card and the orb still agree. The progress BAR keeps doneCount, because
  // a step in flight is not finished work.
  // The assertion is still exact and still pins current-step semantics; only the
  // element carrying it moved. Fixture is [done, working, pending] -> step 2.
  it("shows exactly one counter, bracketed, on the current step / total", () => {
    render(<TaskListCard steps={steps} />)
    expect(screen.getByTestId("chassis-counter")).toHaveTextContent("[2/3]")
    // and no second bare fraction anywhere in the card
    expect(screen.queryByText("2/3")).not.toBeInTheDocument()
    expect(screen.queryByText("1/3")).not.toBeInTheDocument()
  })

  it("collapses by default when many steps", () => {
    const many = Array.from({ length: 6 }, (_, i) => ({
      id: `s${i}`,
      description: `Step ${i}`,
      status: "pending",
    }))
    render(<TaskListCard steps={many} defaultCollapsed />)
    expect(screen.queryByText("Step 0")).not.toBeInTheDocument()
  })

  it("expands on toggle click", () => {
    const many = Array.from({ length: 6 }, (_, i) => ({
      id: `s${i}`,
      description: `Step ${i}`,
      status: "pending",
    }))
    render(<TaskListCard steps={many} defaultCollapsed />)
    fireEvent.click(screen.getByLabelText(/expand plan/i))
    expect(screen.getByText("Step 0")).toBeInTheDocument()
  })

  describe("T1.5 — honest display (REQ-1 AC4, REQ-3 AC3)", () => {
    const t15Steps = [
      { id: "s1", description: "Read config file", status: "done", toolName: "read_file", result_summary: "Config loaded" },
      { id: "s2", description: "Search recent research", status: "working", toolName: "crawler_query", activeDetail: "example.com", activeProgress: "1/5" },
      { id: "s3", description: "Write summary", status: "fail", toolName: "write_file" },
      { id: "s4", description: "Review changes", status: "pending", toolName: "review" },
    ]

    it("working step renders Xur (animated orb) instead of a plain dot", () => {
      const { container } = render(<TaskListCard steps={t15Steps} />)
      // Should have exactly 1 Xur — not 4, not 0.
      const xurs = container.querySelectorAll('[data-testid="xur"]')
      expect(xurs.length).toBe(1)
      // Confirm it's the working step (color matches amber).
      expect(xurs[0].getAttribute("data-color")).toBe("#fbbf24")
    })

    it("failed step renders with red (#f87171) styling", () => {
      const { container } = render(<TaskListCard steps={t15Steps} />)
      // The container must contain the failed-step color (dot border renders f87171).
      expect(container.innerHTML.toLowerCase()).toContain("f87171")
    })

    it("detail renders beside the tool name", () => {
      render(<TaskListCard steps={t15Steps} />)
      // The working step (s2) has activeDetail "example.com" — it should appear near tool name.
      expect(screen.getByText("example.com")).toBeInTheDocument()
      // activeProgress also visible
      expect(screen.getByText("1/5")).toBeInTheDocument()
    })

    it("no bare 'Step N' text — real descriptions used instead", () => {
      render(<TaskListCard steps={t15Steps} />)
      // Each step MUST show its canonical description, not a generic "Step N".
      expect(screen.getByText("Read config file")).toBeInTheDocument()
      expect(screen.getByText("Search recent research")).toBeInTheDocument()
      expect(screen.getByText("Write summary")).toBeInTheDocument()
      expect(screen.getByText("Review changes")).toBeInTheDocument()
    })
  })
})