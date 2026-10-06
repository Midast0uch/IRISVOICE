import React from "react"
import { render, screen, fireEvent, cleanup, waitFor, act } from "@testing-library/react"
import { ThreadOrbit, orbitGeometry } from "@/components/chat/header/ThreadOrbit"
import * as api from "@/lib/strands/api"
import { setReducedMotion } from "../chrome/canvasStub"
import { stubCanvas, thread } from "./headerTestKit"

jest.mock("@/lib/strands/api", () => ({
  PRESET_STRAND_TAGS: ["plan", "build", "research", "people", "swarm"],
  fetchThreads: jest.fn(),
  fetchStrands: jest.fn(),
  createStrand: jest.fn(),
  patchStrand: jest.fn(),
  patchThread: jest.fn(),
}))

const PALETTE = ["hsl(190, 100%, 60%)", "hsl(220, 90%, 65%)", "hsl(150, 80%, 55%)"] as const
const THREADS = [
  thread("t1", "Router budget", { strand_count: 4 }),
  thread("t2", "Trip to Lisbon"),
  thread("t3", "Taxes 2026"),
  thread("t4", "Garden irrigation"),
  thread("t5", "Reading list"),
  thread("t6", "Pinned alpha", { pinned: true }),
  thread("t7", "Pinned beta", { pinned: true }),
]

function mount(over: Partial<React.ComponentProps<typeof ThreadOrbit>> = {}) {
  const props = { palette: PALETTE, activeThreadId: "t1", onOpen: jest.fn(), onNew: jest.fn(), onClose: jest.fn(), ...over }
  render(<ThreadOrbit {...props} />)
  return props
}
const label = (id: string) => document.querySelector(`[data-thread-id="${id}"]`) as HTMLElement

describe("ThreadOrbit", () => {
  let fetchSpy: jest.SpyInstance
  beforeEach(() => {
    stubCanvas()
    setReducedMotion(true)
    ;(api.fetchThreads as jest.Mock).mockResolvedValue(THREADS)
    // The orbit must never download conversations: any /api/conversations call fails the test.
    fetchSpy = jest.fn().mockRejectedValue(new Error("no network in this test"))
    ;(global as any).fetch = fetchSpy
  })
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("lists the threads from fetchThreads and never calls the conversation list", async () => {
    mount()
    await waitFor(() => expect(label("t6")).toBeTruthy())
    expect(api.fetchThreads).toHaveBeenCalledTimes(1)
    expect(fetchSpy).not.toHaveBeenCalled() // fetchConversations is GET /api/conversations through fetch
    expect(screen.getByText("Pinned alpha")).toBeTruthy()
    expect(screen.getByText("4 strands", { exact: false })).toBeTruthy()
  })

  it("places pinned threads on the lower loops and recent threads on the upper loops", async () => {
    mount()
    await waitFor(() => expect(label("t6")).toBeTruthy())
    const { cy } = orbitGeometry(480, 640) // no layout in jsdom: the orbit uses its default size
    const top = (id: string) => parseFloat(label(id).style.top)
    expect(label("t6").dataset.loop).toBe("lower")
    expect(label("t7").dataset.loop).toBe("lower")
    expect(top("t6")).toBeGreaterThan(cy)
    expect(top("t7")).toBeGreaterThan(cy)
    const front = document.querySelector('[data-front="true"]') as HTMLElement
    expect(front.dataset.threadId).toBe("t1")
    expect(front.dataset.loop).toBe("upper")
    expect(top("t1")).toBeLessThan(cy)
  })

  it("typing filters the threads", async () => {
    mount()
    await waitFor(() => expect(label("t6")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("Find a thread"), { target: { value: "lisbon" } })
    expect(label("t2")).toBeTruthy()
    expect(label("t1")).toBeNull()
    expect(label("t6")).toBeNull() // pinned threads are filtered too
    fireEvent.change(screen.getByLabelText("Find a thread"), { target: { value: "zzz" } })
    expect(screen.getByText("No thread matches.")).toBeTruthy()
  })

  it("the wheel and the arrow keys turn the orbit; Enter opens the front thread", async () => {
    const { onOpen } = mount()
    await waitFor(() => expect(label("t6")).toBeTruthy())
    const input = screen.getByLabelText("Find a thread")
    const frontId = () => (document.querySelector('[data-front="true"]') as HTMLElement).dataset.threadId
    expect(frontId()).toBe("t1")
    act(() => { document.querySelector(".iris-hd-orbit")!.dispatchEvent(new WheelEvent("wheel", { deltaY: 120, cancelable: true })) })
    expect(frontId()).toBe("t2")
    fireEvent.keyDown(input, { key: "ArrowRight" })
    expect(frontId()).toBe("t3")
    fireEvent.keyDown(input, { key: "ArrowLeft" })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "t2" }))
  })

  it("clicking a thread opens it", async () => {
    const { onOpen } = mount()
    await waitFor(() => expect(label("t6")).toBeTruthy())
    fireEvent.click(label("t3").querySelector(".iris-hd-oopen") as HTMLElement)
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "t3", title: "Taxes 2026" }))
  })

  it("pin and unpin call patchThread", async () => {
    ;(api.patchThread as jest.Mock).mockImplementation(async (id: string, body: { pinned?: boolean }) => ({ ...THREADS.find((t) => t.id === id)!, ...body }))
    mount()
    await waitFor(() => expect(label("t6")).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "Pin Trip to Lisbon" }))
    expect(api.patchThread).toHaveBeenCalledWith("t2", { pinned: true })
    await waitFor(() => expect(label("t2").dataset.loop).toBe("lower"))
    fireEvent.click(screen.getByRole("button", { name: "Unpin Pinned alpha" }))
    expect(api.patchThread).toHaveBeenCalledWith("t6", { pinned: false })
    await waitFor(() => expect(label("t6").dataset.loop).toBe("upper"))
  })

  it("+ New thread calls the new-thread handler; Esc closes without reaching other Escape handlers", async () => {
    const { onNew, onClose } = mount()
    await waitFor(() => expect(label("t6")).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "+ New thread" }))
    expect(onNew).toHaveBeenCalledTimes(1)
    const outer = jest.fn()
    window.addEventListener("keydown", outer) // stands for chat-view's Escape handler (closes the wing)
    fireEvent.keyDown(document.body, { key: "Escape" })
    window.removeEventListener("keydown", outer)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(outer).not.toHaveBeenCalled()
  })

  it("says so when the list cannot load", async () => {
    ;(api.fetchThreads as jest.Mock).mockRejectedValue(new Error("down"))
    jest.spyOn(console, "warn").mockImplementation(() => {})
    mount()
    await waitFor(() => expect(screen.getByText("Could not load your threads.")).toBeTruthy())
  })
})
