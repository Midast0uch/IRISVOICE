import "@testing-library/jest-dom"
import { render, screen } from "@testing-library/react"
import ContextPill from "@/components/chat/ContextPill"

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
})
