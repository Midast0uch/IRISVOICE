import React from "react"
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react"
import { StrandMap } from "@/components/chat/header/StrandMap"
import * as api from "@/lib/strands/api"
import { setReducedMotion } from "../chrome/canvasStub"
import { stubCanvas, strand } from "./headerTestKit"

jest.mock("@/lib/strands/api", () => ({
  PRESET_STRAND_TAGS: ["plan", "build", "research", "people", "swarm"],
  fetchThreads: jest.fn(),
  fetchStrands: jest.fn(),
  createStrand: jest.fn(),
  patchStrand: jest.fn(),
  patchThread: jest.fn(),
}))

const PALETTE = ["hsl(190, 100%, 60%)", "hsl(220, 90%, 65%)", "hsl(150, 80%, 55%)"] as const
const STRANDS = [
  strand("root", "IRISVOICE router", { tags: ["plan"] }),
  strand("s-fix", "fix the cap", { tags: ["build", "research"] }),
  strand("s-help", "check callers", { tags: ["swarm"], reports_to: "s-fix" }),
]

function mount(over: Partial<React.ComponentProps<typeof StrandMap>> = {}) {
  const props = {
    threadId: "root", palette: PALETTE, activeId: "s-fix", running: new Set<string>(),
    onSwitch: jest.fn(), onCreated: jest.fn(), onClose: jest.fn(), top: 52, ...over,
  }
  render(<StrandMap {...props} />)
  return props
}
const lbl = (id: string) => document.querySelector(`[data-strand-id="${id}"]`) as HTMLElement

describe("StrandMap", () => {
  beforeEach(() => {
    stubCanvas()
    setReducedMotion(true)
    ;(api.fetchStrands as jest.Mock).mockResolvedValue(STRANDS)
  })
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("lists the strands of the thread with their tags, and marks the open one", async () => {
    mount()
    await waitFor(() => expect(lbl("s-fix")).toBeTruthy())
    expect(api.fetchStrands).toHaveBeenCalledWith("root")
    expect(lbl("s-fix").textContent).toContain("build · research")
    expect(lbl("s-fix").getAttribute("aria-current")).toBe("true")
    expect(lbl("root").getAttribute("aria-current")).toBeNull()
    expect(lbl("root").textContent).toContain("main") // the root strand carries the thread's own title
  })

  it("a helper strand shows who it reports to; a working strand shows a dot", async () => {
    mount({ running: new Set(["s-help"]) })
    await waitFor(() => expect(lbl("s-help")).toBeTruthy())
    expect(lbl("s-help").textContent).toContain("reports to “fix the cap”")
    expect(lbl("s-help").querySelector('[aria-label="working"]')).toBeTruthy()
    expect(lbl("s-fix").querySelector('[aria-label="working"]')).toBeNull()
  })

  it("clicking a strand calls the switch handler with its conversation id", async () => {
    const { onSwitch } = mount()
    await waitFor(() => expect(lbl("s-help")).toBeTruthy())
    fireEvent.click(lbl("s-help"))
    expect(onSwitch).toHaveBeenCalledWith("s-help")
  })

  it("creates a strand with the preset tags and a custom tag through createStrand", async () => {
    const made = strand("s-new", "tax questions", { tags: ["research", "people", "taxes"] })
    ;(api.createStrand as jest.Mock).mockResolvedValue(made)
    const { onCreated } = mount()
    await waitFor(() => expect(lbl("s-fix")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("New strand name"), { target: { value: "  tax questions " } })
    fireEvent.click(screen.getByRole("button", { name: "research" }))
    fireEvent.click(screen.getByRole("button", { name: "people" }))
    const own = screen.getByLabelText("Your own tag")
    fireEvent.change(own, { target: { value: " Taxes " } })
    fireEvent.keyDown(own, { key: "Enter" })
    expect(screen.getByRole("button", { name: "taxes" }).getAttribute("aria-pressed")).toBe("true")
    fireEvent.click(screen.getByRole("button", { name: "Add" }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(made))
    expect(api.createStrand).toHaveBeenCalledWith("root", { name: "tax questions", tags: ["research", "people", "taxes"] })
  })

  it("a tag toggled twice is off again", async () => {
    ;(api.createStrand as jest.Mock).mockResolvedValue(strand("s-new", "new strand"))
    mount()
    await waitFor(() => expect(lbl("s-fix")).toBeTruthy())
    const plan = screen.getByRole("button", { name: "plan" })
    fireEvent.click(plan); fireEvent.click(plan)
    expect(plan.getAttribute("aria-pressed")).toBe("false")
    fireEvent.click(screen.getByRole("button", { name: "Add" }))
    await waitFor(() => expect(api.createStrand).toHaveBeenCalledWith("root", { name: "new strand", tags: [] }))
  })

  it("shows an error and keeps the form when createStrand fails", async () => {
    ;(api.createStrand as jest.Mock).mockRejectedValue(new Error("422"))
    jest.spyOn(console, "warn").mockImplementation(() => {})
    const { onCreated } = mount()
    await waitFor(() => expect(lbl("s-fix")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("New strand name"), { target: { value: "x" } })
    fireEvent.click(screen.getByRole("button", { name: "Add" }))
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Could not make the strand"))
    expect(onCreated).not.toHaveBeenCalled()
    expect((screen.getByLabelText("New strand name") as HTMLInputElement).value).toBe("x")
  })
})
