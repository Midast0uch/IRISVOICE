import React from "react"
import "@testing-library/jest-dom"
import { render, screen, fireEvent, cleanup } from "@testing-library/react"
import { DashboardRail, type RailPlace } from "@/components/dashboard/DashboardRail"
import { brandPalette } from "@/lib/brandPalette"
import { installCanvasStub, setHidden, setReducedMotion } from "../chrome/canvasStub"

const PLACES: RailPlace[] = [{ id: "voice", label: "Voice", badge: 2 }, { id: "agent", label: "Agent" }]
const palette = brandPalette()

const mount = (over: Partial<React.ComponentProps<typeof DashboardRail>> = {}) => {
  const onView = jest.fn(), onPlace = jest.fn()
  render(<DashboardRail view="settings" onView={onView} places={PLACES} current="voice" onPlace={onPlace} folded={false} palette={palette} {...over} />)
  return { onView, onPlace }
}

describe("DashboardRail", () => {
  let log: ReturnType<typeof installCanvasStub>
  beforeEach(() => { log = installCanvasStub({ w: 150, h: 600 }); setHidden(false) })
  afterEach(() => { cleanup(); jest.restoreAllMocks() })

  it("switches the view, picks a place and shows a place's badge", () => {
    const { onView, onPlace } = mount()
    expect(screen.getByRole("button", { name: "Settings", pressed: true })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Surfaces" }))
    expect(onView).toHaveBeenCalledWith("surfaces")
    fireEvent.click(screen.getByRole("button", { name: /Agent/ }))
    expect(onPlace).toHaveBeenCalledWith("agent")
    expect(screen.getByRole("button", { name: /Voice/ }).querySelector(".n")!.textContent).toBe("2")
  })

  it("under reduced motion draws ONE still frame and schedules no loop", () => {
    setReducedMotion(true)
    const raf = jest.spyOn(window, "requestAnimationFrame")
    mount()
    expect(raf).not.toHaveBeenCalled()
    expect(log.arcs).toBeGreaterThan(0) // the spine, the orbs and the Xur were drawn
    const drawn = log.arcs
    expect(document.querySelectorAll("canvas")).toHaveLength(1) // one canvas for the whole spine
    fireEvent(document, new Event("visibilitychange"))
    expect(log.arcs).toBe(drawn) // still no further frame
  })

  it("animates by frames while visible, and draws none while the document is hidden", () => {
    setReducedMotion(false)
    const raf = jest.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1)
    mount()
    expect(raf).toHaveBeenCalledTimes(1)
    cleanup(); raf.mockClear()
    setHidden(true)
    mount()
    expect(raf).not.toHaveBeenCalled()
  })

  it("folded = orbs only (the names are hidden by the folded state)", () => {
    mount({ folded: true })
    expect(screen.getByTestId("dash-rail").getAttribute("data-folded")).toBe("true")
  })
})
