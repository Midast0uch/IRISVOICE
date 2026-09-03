import "@testing-library/jest-dom"
import { render, screen } from "@testing-library/react"
import OrbBadge from "@/components/iris/OrbBadge"

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

describe("OrbBadge", () => {
  it("renders nothing when not visible", () => {
    const { container } = render(
      <OrbBadge isVisible={false} variant="working" glowColor="#00c8ff" />
    )
    expect(container.firstChild).toBeNull()
  })

  it("shows step counter when working with steps", () => {
    render(
      <OrbBadge
        isVisible
        variant="working"
        currentStep={2}
        totalSteps={5}
        glowColor="#00c8ff"
      />
    )
    expect(screen.getByText("2/5")).toBeInTheDocument()
  })

  it("shows ? for the question variant", () => {
    render(<OrbBadge isVisible variant="question" glowColor="#00c8ff" />)
    expect(screen.getByText("?")).toBeInTheDocument()
  })

  it("is non-interactive (pointer-events: none)", () => {
    const { container } = render(
      <OrbBadge
        isVisible
        variant="working"
        currentStep={1}
        totalSteps={3}
        glowColor="#00c8ff"
      />
    )
    const badge = container.firstChild as HTMLElement
    expect(badge.style.pointerEvents).toBe("none")
  })

  it("uses glowColor in the pip", () => {
    const { container } = render(
      <OrbBadge
        isVisible
        variant="working"
        currentStep={1}
        totalSteps={3}
        glowColor="#00c8ff"
      />
    )
    const pip = container.querySelector("span") as HTMLElement
    expect(pip.getAttribute("style")).toContain("#00c8ff")
  })
})
