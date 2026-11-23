import "@testing-library/jest-dom"
import { render, screen } from "@testing-library/react"
import ContextPill, { bandOf } from "@/components/chat/ContextPill"

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: { color: "#00c8ff" } }),
  }),
}))

describe("ContextPill", () => {
  it("formats token counts as k with one decimal (REQ-11 AC1)", () => {
    render(<ContextPill usedTokens={12400} maxTokens={128000} phase="idle" />)
    expect(screen.getByText("12.4k / 128.0k")).toBeInTheDocument()
  })

  it("reflects the REAL maxTokens from props, not a hardcoded 128k (REQ-11 AC1)", () => {
    render(<ContextPill usedTokens={50000} maxTokens={200000} phase="idle" />)
    expect(screen.getByText("50.0k / 200.0k")).toBeInTheDocument()
  })

  it("shows a 1M window as 1.0M, not 1000.0k (mercury-3, 2026-10-26)", () => {
    render(<ContextPill usedTokens={2600} maxTokens={1000000} phase="idle" />)
    expect(screen.getByText("2.6k / 1.0M")).toBeInTheDocument()
  })

  it("shows a 2-3 letter phase code, not a full word (REQ-11 AC2)", () => {
    render(<ContextPill usedTokens={1000} maxTokens={128000} phase="listening" />)
    expect(screen.getByText("LSN")).toBeInTheDocument()
    expect(screen.queryByText("LISTENING")).not.toBeInTheDocument()
  })

  it("maps processing_conversation to WRK code (REQ-11 AC2)", () => {
    render(<ContextPill usedTokens={1000} maxTokens={128000} phase="processing_conversation" />)
    expect(screen.getByText("WRK")).toBeInTheDocument()
  })

  it("truncates a long currentAction in the visible label (REQ-11 AC3)", () => {
    const longAction = "Reading example.com and following every link it can find (2/5)"
    render(
      <ContextPill
        usedTokens={1000}
        maxTokens={128000}
        phase="processing_tool"
        currentAction={longAction}
      />
    )
    // Visible label is truncated to ACTION_CAP (24) + ellipsis.
    const visible = screen.getByText(longAction.slice(0, 24) + "…")
    expect(visible).toBeInTheDocument()
    // Full text is preserved in the title tooltip only.
    expect(screen.getByTitle(new RegExp(longAction.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument()
  })

  it("falls back to phase code when no currentAction (REQ-11 AC3)", () => {
    render(<ContextPill usedTokens={1000} maxTokens={128000} phase="speaking" />)
    expect(screen.getByText("SPK")).toBeInTheDocument()
  })

  it("uses green under 60%", () => {
    const { container } = render(
      <ContextPill usedTokens={1000} maxTokens={128000} phase="idle" />
    )
    const bar = container.querySelector(".h-full") as HTMLElement
    expect(bar.style.background).toMatch(/34d399|52, ?211, ?153/i)
  })

  it("uses red over 85%", () => {
    const { container } = render(
      <ContextPill usedTokens={120000} maxTokens={128000} phase="idle" />
    )
    const bar = container.querySelector(".h-full") as HTMLElement
    expect(bar.style.background).toMatch(/f87171|248, ?113, ?113/i)
  })

  describe("the rubber band (CLM, 2026-11-23)", () => {
    const wire = (over: Record<string, number> = {}) =>
      bandOf({ now_tokens: 2000, now_window: 8000, limit_tokens: 3200, peak_tokens: 3600, aside: 2, aside_tokens: 2100, views: 1, ...over })
    const bar = (c: HTMLElement) => c.querySelector(".h-full") as HTMLElement
    const pulled = () => Number(screen.getByTestId("band-loop").getAttribute("data-reach"))

    it("shows the running node against its own window, not the turn's largest call", () => {
      render(<ContextPill usedTokens={23000} maxTokens={260000} phase="processing_tool" band={wire()} />)
      expect(screen.getByText("2.0k / 8.0k")).toBeInTheDocument()
      expect(screen.getByTestId("band-aside")).toHaveTextContent("2")
    })

    it("stretches and gives way", () => {
      const p = { usedTokens: 1, maxTokens: 8000, phase: "processing_tool" }
      const { container, rerender } = render(<ContextPill {...p} band={wire({ now_tokens: 800, peak_tokens: 800 })} />)
      const slack = pulled()
      rerender(<ContextPill {...p} band={wire({ now_tokens: 3100, peak_tokens: 3100 })} />)
      const taut = pulled()
      expect(taut).toBeGreaterThan(slack)
      expect(screen.queryByTestId("band-peak")).toBeNull()
      expect(bar(container).style.background).toMatch(/fbbf24|251, ?191, ?36/i) // near the place it lets go: amber, not red
      rerender(<ContextPill {...p} band={wire({ now_tokens: 1200, peak_tokens: 3100 })} />)
      expect(pulled()).toBeLessThan(taut)
      expect(Number(screen.getByTestId("band-peak").getAttribute("data-at"))).toBeCloseTo(taut, 3) // it remembers how far
      expect(Number(screen.getByTestId("band-limit").getAttribute("data-at"))).toBeCloseTo(Math.sqrt(0.4), 3)
    })

    it("a small view on a 128k window is still seen to move", () => {
      const p = { usedTokens: 1, maxTokens: 128000, phase: "processing_tool" }
      const { rerender } = render(<ContextPill {...p} band={wire({ now_window: 128000, now_tokens: 1500 })} />)
      const at1 = pulled()
      rerender(<ContextPill {...p} band={wire({ now_window: 128000, now_tokens: 10000 })} />)
      expect((pulled() - at1) * 39).toBeGreaterThan(5) // px of the 39px span
    })

    it("has no tick and no set-aside count when CLM does not set results aside", () => {
      render(<ContextPill usedTokens={1} maxTokens={8000} phase="idle" band={wire({ limit_tokens: 0, aside: 0, aside_tokens: 0 })} />)
      expect(screen.queryByTestId("band-limit")).toBeNull()
      expect(screen.queryByTestId("band-aside")).toBeNull()
      expect(screen.queryByTitle(/lets go|set aside/)).toBeNull()
    })

    it("is the plain meter for a payload without a band", () => {
      expect(bandOf({ used_tokens: 5, max_tokens: 10 })).toBeUndefined()
    })

    it("shows — for a thread with no call measured yet", () => {
      render(<ContextPill usedTokens={0} maxTokens={8000} phase="idle" />)
      expect(screen.getByText("— / 8.0k")).toBeInTheDocument()
    })
  })
})
