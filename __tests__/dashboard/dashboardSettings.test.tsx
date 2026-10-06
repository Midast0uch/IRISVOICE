import "@testing-library/jest-dom"
import { mockSendMessage, prepareDashboard, mountDashboard } from "./dashboardKit"
import { screen, fireEvent, cleanup, waitFor, act, within } from "@testing-library/react"

const row = (id: string) => document.querySelector(`[data-section="${id}"]`) as HTMLElement
const find = (v: string) => fireEvent.change(screen.getByLabelText("Find a setting"), { target: { value: v } })

describe("settings rows", () => {
  beforeEach(() => prepareDashboard())
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("a row shows the current values of its section in one line, and open rows show their fields", () => {
    mountDashboard()
    const input = row("input")
    expect(within(input).getByRole("button", { expanded: true }).textContent).toContain("75% · voice activity on")
    // closed row: orb is hollow and no fields
    const wake = row("wake")
    expect(wake.querySelector(".o")!.textContent).toBe("○")
    expect(wake.querySelector(".iris-fields")).toBeNull()
    fireEvent.click(within(wake).getByRole("button"))
    expect(wake.querySelector(".o")!.textContent).toBe("●")
    expect(wake.querySelector(".iris-fields")).not.toBeNull()
  })

  it("changing a field marks its dot, the row count, the rail, the header and the apply bar; Apply sends it", async () => {
    mountDashboard()
    expect(screen.getByTestId("apply-sum").textContent).toBe("All saved")
    // Apply works at any time, as before the redesign (owner 2026-10-06); it only looks quieter at rest.
    expect(screen.getByRole("button", { name: "Apply" })).not.toBeDisabled()
    expect(screen.getByRole("button", { name: "Apply" }).style.opacity).toBe("0.6")

    fireEvent.click(screen.getByRole("switch", { name: "Voice Activity Detection" }))

    const input = row("input")
    expect(within(input).getByTitle("changed, not applied")).toBeInTheDocument()
    expect(input.querySelector(".chg")!.textContent).toBe("1 changed")
    expect(input.querySelector(".iris-srow small")!.textContent).toContain("voice activity off")
    expect(document.querySelector('[data-place="voice"] .n')!.textContent).toBe("1")
    expect(screen.getByTestId("dash-sub").textContent).toContain("1 not applied")
    expect(screen.getByTestId("apply-sum").textContent).toBe("1 change · Input")

    // changing it back is no longer a change
    fireEvent.click(screen.getByRole("switch", { name: "Voice Activity Detection" }))
    expect(screen.getByTestId("apply-sum").textContent).toBe("All saved")
    fireEvent.click(screen.getByRole("switch", { name: "Voice Activity Detection" }))

    fireEvent.click(screen.getByRole("button", { name: "Apply" }))
    expect(mockSendMessage).toHaveBeenCalledWith("confirm_card", expect.objectContaining({ section_id: "input" }))
    await waitFor(() => expect((global as any).fetch).toHaveBeenCalledWith("/api/config/save", expect.objectContaining({ method: "POST" })))
    await waitFor(() => expect(screen.getByTestId("apply-sum").textContent).toBe("All saved"))
    expect(within(row("input")).queryByTitle("changed, not applied")).toBeNull()
    expect(screen.getByTestId("dash-sub").textContent).toBe("settings")
  })

  it("a slider commits once, when the drag ends", () => {
    mountDashboard()
    const slider = screen.getByRole("slider", { name: "Input Volume" })
    fireEvent.pointerDown(slider)
    fireEvent.change(slider, { target: { value: "40" } })
    expect(screen.getByTestId("apply-sum").textContent).toBe("All saved") // shown, not committed
    expect(slider.parentElement!.querySelector(".iris-num")!.textContent).toBe("40%")
    fireEvent.pointerUp(slider)
    expect(screen.getByTestId("apply-sum").textContent).toBe("1 change · Input")
  })

  it("has no Discard button (no revert path exists today)", () => {
    mountDashboard()
    expect(screen.queryByRole("button", { name: /discard/i })).toBeNull()
  })
})

describe("find a setting", () => {
  beforeEach(() => prepareDashboard())
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("shows matching sections opened, grouped by place, across all settings places", () => {
    mountDashboard()
    find("memory")
    const agent = document.querySelector('[data-place-group="agent"]') as HTMLElement
    expect(within(agent).getByText("Agent")).toBeInTheDocument()
    expect(agent.querySelector('[data-section="memory"]')!.className).toContain("open")
    find("power")
    expect(document.querySelector('[data-place-group="system"] [data-section="power"]')).not.toBeNull()
    expect(document.querySelector('[data-place-group="agent"]')).toBeNull()
    // a field label matches too: "Voice Activity" is a field of Input
    find("voice activity")
    expect(document.querySelector('[data-place-group="voice"] [data-section="input"]')).not.toBeNull()
    find("zzzz")
    expect(screen.getByText("No setting matches")).toBeInTheDocument()
    find("")
    expect(document.querySelector("[data-place-group]")).toBeNull()
  })
})

describe("groups that are not lists of plain fields", () => {
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("model routing is a pane with a mono header and a table, not an orb row", () => {
    prepareDashboard("agent")
    mountDashboard()
    const pane = row("model_inference")
    expect(pane.className).toContain("iris-pane")
    expect(pane.querySelector("h4")).not.toBeNull()
    expect(pane.querySelector(".iris-srow")).toBeNull()
    expect(within(pane).getByRole("table", { name: "Model routing" })).toBeInTheDocument()
    expect(within(pane).getByTestId("model-inference-controls")).toBeInTheDocument()
    // plain-field groups of the same place keep the row pattern
    expect(row("memory").className).toContain("iris-sec")
  })

  it("tool permissions (an approved-tools list) is a pane too", () => {
    prepareDashboard("automate")
    mountDashboard()
    const pane = row("tools")
    expect(pane.className).toContain("iris-pane")
    expect(within(pane).getByTestId("permissions-list")).toBeInTheDocument()
  })
})
