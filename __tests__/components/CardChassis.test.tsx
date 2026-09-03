import "@testing-library/jest-dom"
import { render, screen, fireEvent } from "@testing-library/react"
import {
  CardChassis,
  ChassisBadge,
  ChassisChromeLabel,
  ChassisBranchBadge,
  ChassisStepNode,
  VEIN_COLOR_BY_STATE,
  CHASSIS_TYPE_FLOOR_PX,
  CHASSIS_MEANING_FLOOR_PX,
} from "@/components/chat/CardChassis"

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

describe("CardChassis (T8)", () => {
  describe("REQ-1 AC5 — padding and vein cannot be opted out", () => {
    it("renders the accent vein and the padding wrapper with only the required props", () => {
      render(<CardChassis veinColor="#f97316" header={<span>Objective</span>} />)
      expect(screen.getByTestId("chassis-vein")).toBeInTheDocument()
      expect(screen.getByTestId("chassis-padding")).toBeInTheDocument()
    })

    it("keeps the vein even when no counter, subheader, footer or children are supplied", () => {
      // There is no prop that removes the vein or the padding div — a card
      // only ever gets slot content (header/subheader/children/footer), so
      // it has no way to render a sibling that bypasses either.
      const { container } = render(<CardChassis veinColor="#34d399" header={null} />)
      const vein = screen.getByTestId("chassis-vein")
      expect(container.contains(vein)).toBe(true)
      expect(vein).toHaveStyle({ opacity: "0.5" })
    })

    it("drives vein opacity from isActive (REQ-1 AC3)", () => {
      const { rerender } = render(
        <CardChassis veinColor="#fbbf24" isActive header={<span>Objective</span>} />
      )
      expect(screen.getByTestId("chassis-vein")).toHaveStyle({ opacity: "1" })

      rerender(<CardChassis veinColor="#fbbf24" isActive={false} header={<span>Objective</span>} />)
      expect(screen.getByTestId("chassis-vein")).toHaveStyle({ opacity: "0.5" })
    })
  })

  describe("header slot + counter (REQ-1 AC1/AC6)", () => {
    it("renders arbitrary header content", () => {
      render(<CardChassis veinColor="#f97316" header={<span>my objective</span>} />)
      expect(screen.getByText("my objective")).toBeInTheDocument()
    })

    it("renders the bracketed [done/total] counter", () => {
      render(
        <CardChassis veinColor="#f97316" header={<span>obj</span>} counter={{ done: 2, total: 4 }} />
      )
      expect(screen.getByTestId("chassis-counter")).toHaveTextContent("[2/4]")
    })

    it("omits the counter when total is 0 (zero-steps edge case)", () => {
      render(<CardChassis veinColor="#f97316" header={<span>obj</span>} counter={{ done: 0, total: 0 }} />)
      expect(screen.queryByTestId("chassis-counter")).not.toBeInTheDocument()
    })

    it("omits the counter entirely when not supplied", () => {
      render(<CardChassis veinColor="#f97316" header={<span>obj</span>} />)
      expect(screen.queryByTestId("chassis-counter")).not.toBeInTheDocument()
    })
  })

  describe("collapse affordance (REQ-1 AC4)", () => {
    it("shows children by default and hides them on toggle", () => {
      render(
        <CardChassis veinColor="#f97316" header={<span>obj</span>}>
          <div>step body</div>
        </CardChassis>
      )
      expect(screen.getByText("step body")).toBeInTheDocument()
      fireEvent.click(screen.getByLabelText(/collapse card/i))
      expect(screen.queryByText("step body")).not.toBeInTheDocument()
    })

    it("respects defaultCollapsed", () => {
      render(
        <CardChassis veinColor="#f97316" header={<span>obj</span>} defaultCollapsed>
          <div>step body</div>
        </CardChassis>
      )
      expect(screen.queryByText("step body")).not.toBeInTheDocument()
      fireEvent.click(screen.getByLabelText(/expand card/i))
      expect(screen.getByText("step body")).toBeInTheDocument()
    })

    it("does not render a collapse button when there is no body content", () => {
      render(<CardChassis veinColor="#f97316" header={<span>obj</span>} />)
      expect(screen.queryByLabelText(/collapse card/i)).not.toBeInTheDocument()
      expect(screen.queryByLabelText(/expand card/i)).not.toBeInTheDocument()
    })

    it("does not render a collapse button when collapsible=false, but still renders children", () => {
      render(
        <CardChassis veinColor="#f97316" header={<span>obj</span>} collapsible={false}>
          <div>always visible</div>
        </CardChassis>
      )
      expect(screen.getByText("always visible")).toBeInTheDocument()
      expect(screen.queryByLabelText(/collapse card/i)).not.toBeInTheDocument()
    })

    it("supports controlled collapse via collapsed + onCollapsedChange", () => {
      const onCollapsedChange = jest.fn()
      const { rerender } = render(
        <CardChassis
          veinColor="#f97316"
          header={<span>obj</span>}
          collapsed={false}
          onCollapsedChange={onCollapsedChange}
        >
          <div>controlled body</div>
        </CardChassis>
      )
      expect(screen.getByText("controlled body")).toBeInTheDocument()
      fireEvent.click(screen.getByLabelText(/collapse card/i))
      expect(onCollapsedChange).toHaveBeenCalledWith(true)
      // Controlled: body stays visible until the parent flips the prop.
      expect(screen.getByText("controlled body")).toBeInTheDocument()
      rerender(
        <CardChassis
          veinColor="#f97316"
          header={<span>obj</span>}
          collapsed
          onCollapsedChange={onCollapsedChange}
        >
          <div>controlled body</div>
        </CardChassis>
      )
      expect(screen.queryByText("controlled body")).not.toBeInTheDocument()
    })
  })

  describe("subheader and footer slots", () => {
    it("renders subheader and footer when supplied, omits them when not", () => {
      const { rerender } = render(
        <CardChassis
          veinColor="#f97316"
          header={<span>obj</span>}
          subheader={<span>THK whisper</span>}
          footer={<span>footer text</span>}
        />
      )
      expect(screen.getByText("THK whisper")).toBeInTheDocument()
      expect(screen.getByText("footer text")).toBeInTheDocument()

      rerender(<CardChassis veinColor="#f97316" header={<span>obj</span>} />)
      expect(screen.queryByText("THK whisper")).not.toBeInTheDocument()
      expect(screen.queryByText("footer text")).not.toBeInTheDocument()
    })
  })

  describe("vein colour by state (REQ-1 AC2)", () => {
    it("exposes the three task-card execution state colours from the variant", () => {
      expect(VEIN_COLOR_BY_STATE.idle).toBe("#f97316")
      expect(VEIN_COLOR_BY_STATE.thinking).toBe("#fbbf24")
      expect(VEIN_COLOR_BY_STATE.crystallized).toBe("#34d399")
    })
  })

  describe("Decision 15 — type floor", () => {
    it("exports the floor constants", () => {
      expect(CHASSIS_TYPE_FLOOR_PX).toBe(9)
      expect(CHASSIS_MEANING_FLOOR_PX).toBe(10)
    })

    it("ChassisBadge renders at the 10px meaning floor, never 8px", () => {
      const { container } = render(
        <ChassisBadge color="#34d399">done</ChassisBadge>
      )
      expect(container.innerHTML).toContain("text-[10px]")
      expect(container.innerHTML).not.toContain("text-[8px]")
    })

    it("ChassisChromeLabel renders at the 9px floor, never 8px", () => {
      const { container } = render(<ChassisChromeLabel>data/memory.db</ChassisChromeLabel>)
      expect(container.innerHTML).toContain("text-[9px]")
      expect(container.innerHTML).not.toContain("text-[8px]")
    })
  })

  describe("Decision 13 — Diving Deeper branch badge", () => {
    it("renders arbitrary free-text branchLabel, never a hardcoded word", () => {
      render(<ChassisBranchBadge branchLabel="Diving Deeper: auth refactor" />)
      expect(screen.getByText("↳ Diving Deeper: auth refactor")).toBeInTheDocument()
    })

    it("never renders the banned 'Sub-Loop' or 'Detour' copy itself", () => {
      const { container } = render(<ChassisBranchBadge branchLabel="Diving Deeper" />)
      expect(container.textContent).not.toContain("Sub-Loop")
      expect(container.textContent).not.toContain("Detour")
    })

    it("renders at the 10px meaning floor, never the variant's original 8px", () => {
      const { container } = render(<ChassisBranchBadge branchLabel="Diving Deeper" />)
      expect(container.innerHTML).toContain("text-[10px]")
      expect(container.innerHTML).not.toContain("text-[8px]")
    })
  })

  describe("ChassisStepNode — ripple-ring active nodes reproduced from the variant", () => {
    it("running renders the ripple ring + Xur", () => {
      render(<ChassisStepNode status="running" color="#f97316" />)
      expect(screen.getByTestId("chassis-node-running")).toBeInTheDocument()
      expect(screen.getByTestId("xur")).toBeInTheDocument()
    })

    it("crystallized, done and pending each render their own node without Xur", () => {
      const { rerender } = render(<ChassisStepNode status="crystallized" color="#f97316" />)
      expect(screen.getByTestId("chassis-node-crystallized")).toBeInTheDocument()
      expect(screen.queryByTestId("xur")).not.toBeInTheDocument()

      rerender(<ChassisStepNode status="done" color="#f97316" />)
      expect(screen.getByTestId("chassis-node-done")).toBeInTheDocument()

      rerender(<ChassisStepNode status="pending" color="#f97316" />)
      expect(screen.getByTestId("chassis-node-pending")).toBeInTheDocument()
    })
  })
})
