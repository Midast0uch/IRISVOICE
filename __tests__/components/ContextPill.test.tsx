import "@testing-library/jest-dom"
import { render, screen } from "@testing-library/react"
import ContextPill from "@/components/chat/ContextPill"

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: { color: "#00c8ff" } }),
  }),
}))

describe("ContextPill", () => {
  it("formats token counts as k", () => {
    render(<ContextPill usedTokens={12400} maxTokens={128000} phase="working" />)
    expect(screen.getByText("12.4k / 128k")).toBeInTheDocument()
  })

  it("shows phase label uppercased", () => {
    render(<ContextPill usedTokens={1000} maxTokens={128000} phase="listening" />)
    expect(screen.getByText("LISTENING")).toBeInTheDocument()
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