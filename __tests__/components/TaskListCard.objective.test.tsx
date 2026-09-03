/**
 * pin_07b780e7ce21 — objective-title dominance (Liquid Ink fidelity).
 *
 * Guards the NEW header path introduced with the backend
 * `_effective_plan_title` guarantee (agent_kernel.py): every live task:start
 * now carries a real plan_title, and TaskListCard must render it as the
 * DOMINANT header element using the variant's exact tokens
 * (VariantLiquidInk.tsx line 84: text-[12px] font-mono font-semibold,
 * white/95, tracking-tight, truncate) beside a SHORT mode badge.
 *
 * Also pins the honest-display constraint discovered during this work: with
 * NO planTitle the header must NOT echo steps[0].description (that
 * duplicated the step row's text — caught by TaskListCard.test.tsx); the
 * legacy single-badge fallback renders instead.
 */
import "@testing-library/jest-dom"
import { render, screen } from "@testing-library/react"
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

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: { color: "#00c8ff" } }),
  }),
}))

// Test INFRA (session 245): the card header now renders the animated Xur
// marker (Liquid Ink fidelity pass). Same jsdom mock as the sibling files.
jest.mock("@/components/Xur", () => ({
  Xur: (props: { size?: number; color?: string; speed?: number }) => (
    <div data-testid="xur" data-color={props.color} data-size={props.size} />
  ),
}))

const steps = [
  { id: "s1", description: "Search the web for results", status: "working", toolName: "search" },
  { id: "s2", description: "Summarize findings", status: "pending" },
]

describe("TaskListCard objective-title dominance (pin_07b780e7ce21)", () => {
  it("renders planTitle as the DOMINANT header element with the variant LiquidInk tokens", () => {
    render(
      <TaskListCard
        steps={steps}
        planTitle="Search web for AI news"
        mode="websearch"
      />
    )
    const title = screen.getByText("Search web for AI news")
    expect(title).toBeInTheDocument()
    // Variant token table: 12px mono semibold, tracking-tight, truncating.
    expect(title.className).toContain("text-[12px]")
    expect(title.className).toContain("font-semibold")
    expect(title.className).toContain("tracking-tight")
    expect(title.className).toContain("truncate")
    // Full text survives on the tooltip (graceful clipping contract).
    expect(title).toHaveAttribute("title", "Search web for AI news")
    // RE-INVERTED 2026-08-21, session 245, CALLED OUT DELIBERATELY: the
    // user-approved Liquid Ink fidelity pass REMOVED the mode badge from the
    // objective header entirely (variant anatomy: marker -> objective, nothing
    // in front). WHAT THIS ASSERTION STILL PINS: the objective is the
    // dominant header element and no mode badge precedes it.
    expect(screen.queryByText("WEBSEARCH")).not.toBeInTheDocument()
  })

  it("does NOT duplicate steps[0].description in the header when planTitle is absent", () => {
    render(<TaskListCard steps={steps} />)
    // The step row renders the description exactly once.
    expect(screen.getAllByText("Search the web for results")).toHaveLength(1)
    // RE-INVERTED 2026-08-21, session 245 (Liquid Ink fidelity pass),
    // CALLED OUT DELIBERATELY: the legacy fallback stuffed
    // steps[0].description into the shrink-0 badge (the original mid-glyph
    // clipping bug). With no planTitle AND no mode the header now renders
    // NO title at all — honest blank beats a duplicated, clipped string.
    // WHAT THIS ASSERTION STILL PINS: the step text appears exactly once,
    // and never again as a header badge.
    expect(screen.queryByText("SEARCH THE WEB FOR RESULTS")).not.toBeInTheDocument()
  })

  it("renders a SHORT mode badge when planTitle is absent but a mode exists", () => {
    render(<TaskListCard steps={steps} mode="websearch" />)
    // Legacy payloads without plan_title keep the short mode label.
    expect(screen.getByText("WEBSEARCH")).toBeInTheDocument()
    // Still no duplicated step text.
    expect(screen.queryByText("SEARCH THE WEB FOR RESULTS")).not.toBeInTheDocument()
  })
})
