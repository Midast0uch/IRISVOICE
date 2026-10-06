import React from "react"
import { render, screen, fireEvent, cleanup, waitFor, act } from "@testing-library/react"
import { ChatHeader, type ChatHeaderProps } from "@/components/chat/ChatHeader"
import { ChatEdge } from "@/components/chat/header/ChatEdge"
import { applyTurnMessage, __resetTurnsForTests } from "@/lib/turns/turnStore"
import * as api from "@/lib/strands/api"
import * as wing from "@/hooks/useDetachedWing"
import { invoke } from "@tauri-apps/api/core"
import { setReducedMotion } from "../chrome/canvasStub"
import { stubCanvas, strand, thread } from "./headerTestKit"

jest.mock("@/lib/strands/api", () => ({
  PRESET_STRAND_TAGS: ["plan", "build", "research", "people", "swarm"],
  fetchThreads: jest.fn(),
  fetchStrands: jest.fn(),
  createStrand: jest.fn(),
  patchStrand: jest.fn(),
  patchThread: jest.fn(),
}))
jest.mock("@tauri-apps/api/core", () => ({ invoke: jest.fn().mockResolvedValue(undefined) }))
jest.mock("@/hooks/useDetachedWing", () => ({ detachWing: jest.fn(), reattachWing: jest.fn() }))

const THREADS = [thread("root", "Router budget", { strand_count: 2 }), thread("other", "Trip to Lisbon")]
const STRANDS = [strand("root", "Router budget"), strand("s-fix", "fix the cap", { tags: ["build"] })]

function props(over: Partial<ChatHeaderProps> = {}): ChatHeaderProps {
  return {
    isDetached: false, glowColor: "#00c8ff", fontColor: "#ffffff", voiceState: "idle", globalError: false,
    chatHeaderRef: React.createRef<HTMLDivElement>(), handleHeaderDragStart: jest.fn(),
    isDashboardOpen: false, onDashboardClose: jest.fn(), onDashboardClick: jest.fn(), onClose: jest.fn(),
    showNotifications: false, openNotifications: jest.fn(), unreadCount: 0, closeDropdowns: jest.fn(),
    activeConversationId: "s-fix", fallbackTitle: "fallback title", onNewThread: jest.fn(), onOpenConversation: jest.fn(),
    ...over,
  }
}
const mount = (over: Partial<ChatHeaderProps> = {}) => { const p = props(over); render(<ChatHeader {...p} />); return p }
const turnStart = (turn: string, conv: string) => applyTurnMessage({
  type: "turn.start",
  payload: { v: 1, turn_id: turn, conversation_id: conv, strand_id: conv, author: "user", to: ["@iris"], refs: [], mode: "personal", prompt: "p", ts: 1 },
})

describe("ChatHeader", () => {
  beforeEach(() => {
    stubCanvas()
    setReducedMotion(true)
    __resetTurnsForTests()
    ;(api.fetchThreads as jest.Mock).mockResolvedValue(THREADS)
    ;(api.fetchStrands as jest.Mock).mockImplementation(async (id: string) => (id === "root" ? STRANDS : [strand(id, "x")]))
    ;(global as any).fetch = jest.fn().mockRejectedValue(new Error("no network in this test"))
  })
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("shows the thread name and the current strand, resolving a strand to its thread", async () => {
    mount()
    expect(screen.getByRole("button", { name: "fallback title" })).toBeTruthy() // until the list answers
    await waitFor(() => expect(screen.getByRole("button", { name: "Router budget" })).toBeTruthy())
    const strandBtn = screen.getByRole("button", { name: "Switch strand" })
    expect(strandBtn.textContent).toContain("fix the cap")
    expect(strandBtn.textContent).toContain("build")
    expect(strandBtn.textContent).toContain("2 strands")
    expect(screen.getByRole("button", { name: "Open your threads" })).toBeTruthy()
  })

  it("a new thread (no active conversation) is titled New thread, has no strand, disables ⌖ and settles", async () => {
    mount({ activeConversationId: null, fallbackTitle: undefined })
    await waitFor(() => expect(api.fetchThreads).toHaveBeenCalledTimes(1))
    expect(screen.getByRole("button", { name: "New thread" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Switch strand" })).toBeNull()
    expect((screen.getByRole("button", { name: "Strands of this thread" }) as HTMLButtonElement).disabled).toBe(true)
    expect(api.fetchStrands).not.toHaveBeenCalled()
  })

  it("shows the root strand as main", async () => {
    mount({ activeConversationId: "root" })
    await waitFor(() => expect(screen.getByRole("button", { name: "Switch strand" }).textContent).toContain("main"))
  })

  it("renames the thread in place: Enter saves through patchThread", async () => {
    ;(api.patchThread as jest.Mock).mockResolvedValue({ ...THREADS[0], title: "Router plan" })
    mount()
    await waitFor(() => screen.getByRole("button", { name: "Router budget" }))
    fireEvent.click(screen.getByRole("button", { name: "Router budget" }))
    const input = screen.getByLabelText("Thread name") as HTMLInputElement
    expect(input.value).toBe("Router budget")
    fireEvent.change(input, { target: { value: "  Router plan " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(api.patchThread).toHaveBeenCalledWith("root", { title: "Router plan" })
    await waitFor(() => expect(screen.getByRole("button", { name: "Router plan" })).toBeTruthy())
  })

  it("Esc cancels a rename without saving and without reaching other Escape handlers", async () => {
    mount()
    await waitFor(() => screen.getByRole("button", { name: "Router budget" }))
    fireEvent.click(screen.getByRole("button", { name: "Router budget" }))
    const input = screen.getByLabelText("Thread name")
    fireEvent.change(input, { target: { value: "Something else" } })
    const outer = jest.fn()
    window.addEventListener("keydown", outer)
    fireEvent.keyDown(input, { key: "Escape" })
    window.removeEventListener("keydown", outer)
    expect(outer).not.toHaveBeenCalled()
    expect(api.patchThread).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "Router budget" })).toBeTruthy()
  })

  it("the Xur opens the thread orbit; opening a thread there calls the open handler", async () => {
    const p = mount()
    await waitFor(() => screen.getByRole("button", { name: "Router budget" }))
    fireEvent.click(screen.getByRole("button", { name: "Open your threads" }))
    await waitFor(() => expect(document.querySelector('[data-thread-id="other"]')).toBeTruthy())
    fireEvent.click(document.querySelector('[data-thread-id="other"] .iris-hd-oopen') as HTMLElement)
    expect(p.onOpenConversation).toHaveBeenCalledWith("other")
    expect(document.querySelector(".iris-hd-orbit")).toBeNull()
  })

  it("the orbit's + New thread calls the new-thread handler", async () => {
    const p = mount()
    fireEvent.click(screen.getByRole("button", { name: "Open your threads" }))
    fireEvent.click(await screen.findByRole("button", { name: "+ New thread" }))
    expect(p.onNewThread).toHaveBeenCalledTimes(1)
  })

  it("⌖ opens the strand map; a click on a strand calls the switch handler", async () => {
    const p = mount()
    await waitFor(() => expect((screen.getByRole("button", { name: "Strands of this thread" }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole("button", { name: "Strands of this thread" }))
    const other = await waitFor(() => {
      const el = document.querySelector('[data-strand-id="root"]') as HTMLElement
      expect(el).toBeTruthy()
      return el
    })
    fireEvent.click(other)
    expect(p.onOpenConversation).toHaveBeenCalledWith("root")
    expect(document.querySelector(".iris-hd-map")).toBeNull()
  })

  it("a new strand is made in the open thread, then opened", async () => {
    const made = strand("s-new", "tax questions", { tags: ["research"] })
    ;(api.createStrand as jest.Mock).mockResolvedValue(made)
    const p = mount()
    await waitFor(() => expect((screen.getByRole("button", { name: "Strands of this thread" }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole("button", { name: "Strands of this thread" }))
    await waitFor(() => expect(document.querySelector('[data-strand-id="s-fix"]')).toBeTruthy())
    fireEvent.change(screen.getByLabelText("New strand name"), { target: { value: "tax questions" } })
    fireEvent.click(screen.getByRole("button", { name: "research" }))
    fireEvent.click(screen.getByRole("button", { name: "Add" }))
    await waitFor(() => expect(p.onOpenConversation).toHaveBeenCalledWith("s-new"))
    expect(api.createStrand).toHaveBeenCalledWith("root", { name: "tax questions", tags: ["research"] })
  })

  it("⌖ shows a dot only when a turn runs in ANOTHER strand of this thread", async () => {
    mount()
    await waitFor(() => expect(screen.getByRole("button", { name: "Router budget" })).toBeTruthy())
    expect(screen.queryByTestId("strand-activity")).toBeNull()
    act(() => { turnStart("t-here", "s-fix") }) // the strand on screen: no dot
    expect(screen.queryByTestId("strand-activity")).toBeNull()
    act(() => { turnStart("t-there", "root") })
    await waitFor(() => expect(screen.getByTestId("strand-activity")).toBeTruthy())
  })

  describe("the ◉ menu holds every control the old header had", () => {
    const open = () => fireEvent.click(screen.getByRole("button", { name: "More" }))

    it("lists dashboard, detach, alerts, launcher and close", () => {
      mount()
      open()
      const names = screen.getAllByRole("menuitem").map((m) => m.textContent)
      expect(names).toEqual([expect.stringContaining("Dashboard"), expect.stringContaining("Detach"), expect.stringContaining("Alerts"), expect.stringContaining("Launcher"), expect.stringContaining("Close")])
    })

    it("Dashboard opens it, or closes it when open (same handlers as before)", () => {
      const p = mount(); open()
      fireEvent.click(screen.getByRole("menuitem", { name: /Dashboard/ }))
      expect(p.onDashboardClick).toHaveBeenCalledTimes(1)
      expect(p.closeDropdowns).toHaveBeenCalled()
      cleanup()
      const q = mount({ isDashboardOpen: true }); open()
      fireEvent.click(screen.getByRole("menuitem", { name: /Dashboard/ }))
      expect(q.onDashboardClose).toHaveBeenCalledTimes(1)
      expect(q.onDashboardClick).not.toHaveBeenCalled()
    })

    it("Detach calls detachWing and closes the wing; reattach when detached", async () => {
      ;(wing.detachWing as jest.Mock).mockResolvedValue(true)
      const p = mount(); open()
      fireEvent.click(screen.getByRole("menuitem", { name: /Detach/ }))
      await waitFor(() => expect(p.onClose).toHaveBeenCalledTimes(1))
      expect(wing.detachWing).toHaveBeenCalledWith("chat")
      cleanup()
      mount({ isDetached: true }); open()
      fireEvent.click(screen.getByRole("menuitem", { name: /Put the chat back/ }))
      await waitFor(() => expect(wing.reattachWing).toHaveBeenCalledWith("chat"))
    })

    it("Detach is not offered in the remote view", () => {
      mount({ isRemoteView: true }); open()
      expect(screen.queryByRole("menuitem", { name: /Detach/ })).toBeNull()
    })

    it("Alerts opens the notifications panel, or closes it when open; the unread count shows", () => {
      const p = mount({ unreadCount: 3 }); open()
      const item = screen.getByRole("menuitem", { name: /Alerts/ })
      expect(item.textContent).toContain("3")
      fireEvent.click(item)
      expect(p.openNotifications).toHaveBeenCalledTimes(1)
      cleanup()
      const q = mount({ showNotifications: true }); open()
      fireEvent.click(screen.getByRole("menuitem", { name: /Alerts/ }))
      expect(q.closeDropdowns).toHaveBeenCalled()
      expect(q.openNotifications).not.toHaveBeenCalled()
    })

    it("Close closes the chat", () => {
      const p = mount(); open()
      fireEvent.click(screen.getByRole("menuitem", { name: /Close/ }))
      expect(p.onClose).toHaveBeenCalledTimes(1)
    })

    it("Launcher invokes the launcher command, and the menu closes on a choice", async () => {
      mount(); open()
      fireEvent.click(screen.getByRole("menuitem", { name: /Launcher/ }))
      expect(invoke).toHaveBeenCalledWith("launch_launcher")
      expect(screen.queryByRole("menu")).toBeNull()
    })

    it("Esc closes the menu without closing the chat", () => {
      mount(); open()
      const outer = jest.fn()
      window.addEventListener("keydown", outer)
      fireEvent.keyDown(document.body, { key: "Escape" })
      window.removeEventListener("keydown", outer)
      expect(screen.queryByRole("menu")).toBeNull()
      expect(outer).not.toHaveBeenCalled()
    })
  })
})

describe("ChatEdge (the aperture in the wing's top edge)", () => {
  beforeEach(() => { stubCanvas(); setReducedMotion(true); __resetTurnsForTests() })
  afterEach(() => { cleanup(); jest.restoreAllMocks() })
  const edge = (over: Partial<React.ComponentProps<typeof ChatEdge>> = {}) => {
    const onSpotlightToggle = jest.fn()
    render(<ChatEdge glowColor="#00c8ff" isFlat transform="none" isInChatSpotlight={false} onSpotlightToggle={onSpotlightToggle} activeConversationId="c1" {...over} />)
    return onSpotlightToggle
  }

  it("the aperture calls the spotlight handler, with today's titles", () => {
    const toggle = edge()
    fireEvent.click(screen.getByTitle("Maximize chat"))
    expect(toggle).toHaveBeenCalledTimes(1)
    cleanup()
    edge({ isInChatSpotlight: true })
    expect(screen.getByTitle("Restore balanced view")).toBeTruthy()
    expect(document.querySelector('[data-testid="edge-light"]')!.getAttribute("data-spotlit")).toBe("true")
  })

  it("is working while a turn runs in this conversation, not in another", () => {
    edge()
    expect(document.querySelector('[data-testid="edge-light"]')!.getAttribute("data-working")).toBe("false")
    act(() => { turnStart("t-other", "c2") })
    expect(document.querySelector('[data-testid="edge-light"]')!.getAttribute("data-working")).toBe("false")
    act(() => { turnStart("t-here", "c1") })
    expect(document.querySelector('[data-testid="edge-light"]')!.getAttribute("data-working")).toBe("true")
  })
})
