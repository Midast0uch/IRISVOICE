import "@testing-library/jest-dom"
import { render, screen } from "@testing-library/react"
import { OrbWorkingIndicator } from "@/components/iris/OrbWorkingIndicator"

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

jest.mock("@/hooks/useReducedMotion", () => ({
  useReducedMotion: () => false,
}))

describe("OrbWorkingIndicator", () => {
  it("renders nothing when not active", () => {
    const { container } = render(
      <OrbWorkingIndicator isActive={false} variant="working" glowColor="#00c8ff" />
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders 5 orbiting particles when active", () => {
    const { container } = render(
      <OrbWorkingIndicator isActive variant="working" glowColor="#00c8ff" />
    )
    // Each particle is a div with a radial-gradient background
    const particles = container.querySelectorAll('[style*="radial-gradient"]')
    expect(particles.length).toBe(5)
  })

  it("is non-interactive (pointer-events: none)", () => {
    const { container } = render(
      <OrbWorkingIndicator isActive variant="working" glowColor="#00c8ff" />
    )
    const wrapper = container.firstChild as HTMLElement
    expect(wrapper.style.pointerEvents).toBe("none")
  })

  it("uses glowColor in the particle gradient", () => {
    const { container } = render(
      <OrbWorkingIndicator isActive variant="working" glowColor="#00c8ff" />
    )
    const particles = container.querySelectorAll('[style*="radial-gradient"]')
    expect(particles[0].getAttribute("style")).toContain("#00c8ff")
  })

  it("renders without error in question variant", () => {
    const { container } = render(
      <OrbWorkingIndicator isActive variant="question" glowColor="#00c8ff" shimmerPrimary="hsl(190, 100%, 60%)" />
    )
    const particles = container.querySelectorAll('[style*="radial-gradient"]')
    expect(particles.length).toBe(5)
  })

  it("renders a static ring under reduced motion", () => {
    jest.resetModules()
    jest.doMock("@/hooks/useReducedMotion", () => ({
      useReducedMotion: () => true,
    }))
    const { OrbWorkingIndicator: Reduced } = require("@/components/iris/OrbWorkingIndicator")
    const { container } = render(
      <Reduced isActive variant="working" glowColor="#00c8ff" />
    )
    // Static ring has a border style, no orbiting particles
    const ring = container.querySelector('[style*="border"]')
    expect(ring).not.toBeNull()
    const particles = container.querySelectorAll('[style*="radial-gradient"]')
    expect(particles.length).toBe(0)
  })
})
