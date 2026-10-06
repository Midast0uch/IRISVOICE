import React from "react"
import "@testing-library/jest-dom"
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react"
import { WingMenu, type WingMenuItem } from "@/components/chrome/WingMenu"
import { ChatHeader, type ChatHeaderProps } from "@/components/chat/ChatHeader"
import * as api from "@/lib/strands/api"
import { setReducedMotion } from "../chrome/canvasStub"
import { stubCanvas } from "../header/headerTestKit"

jest.mock("@/lib/strands/api", () => ({
  PRESET_STRAND_TAGS: ["plan"], fetchThreads: jest.fn(), fetchStrands: jest.fn(), createStrand: jest.fn(), patchStrand: jest.fn(), patchThread: jest.fn(),
}))
jest.mock("@tauri-apps/api/core", () => ({ invoke: jest.fn().mockResolvedValue(undefined) }))
jest.mock("@/hooks/useDetachedWing", () => ({ detachWing: jest.fn(), reattachWing: jest.fn() }))

describe("WingMenu", () => {
  afterEach(cleanup)
  const Host = ({ items, open = true }: { items: WingMenuItem[]; open?: boolean }) => {
    const [o, setO] = React.useState(open)
    return <div style={{ position: "relative" }}><WingMenu open={o} onToggle={() => setO((v) => !v)} onClose={() => setO(false)} heading="Test" ariaLabel="Test controls" items={items} dotColor="#fa0" /></div>
  }

  it("renders each item with glyph, label, key text; runs its handler; closes on a choice", () => {
    const run = jest.fn()
    render(<Host items={[{ id: "a", label: "Alpha", glyph: "▦", hint: "Esc", run }, { id: "b", label: "Beta", glyph: "◧", run: jest.fn() }]} />)
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["▦AlphaEsc", "◧Beta"])
    fireEvent.click(screen.getByRole("menuitem", { name: /Alpha/ }))
    expect(run).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole("menu")).toBeNull()
  })

  it("shows an unread dot on an item and on the ◉ button while an item has one", () => {
    render(<Host items={[{ id: "a", label: "Alerts", glyph: "◔", dot: true, run: jest.fn() }]} />)
    expect(screen.getByRole("img", { name: "Unread alerts" })).toBeInTheDocument()
    expect(document.querySelector(".iris-mdot")).not.toBeNull()
    cleanup()
    render(<Host items={[{ id: "a", label: "Alerts", glyph: "◔", run: jest.fn() }]} />)
    expect(screen.queryByRole("img", { name: "Unread alerts" })).toBeNull()
  })

  it("a press outside closes it", () => {
    render(<Host items={[{ id: "a", label: "Alpha", glyph: "▦", run: jest.fn() }]} />)
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole("menu")).toBeNull()
  })
})

describe("the chat header uses the same WingMenu", () => {
  beforeEach(() => {
    stubCanvas(); setReducedMotion(true)
    ;(api.fetchThreads as jest.Mock).mockResolvedValue([])
    ;(api.fetchStrands as jest.Mock).mockResolvedValue([])
    ;(global as any).fetch = jest.fn().mockRejectedValue(new Error("no network"))
  })
  afterEach(() => { cleanup(); jest.clearAllMocks() })

  it("opens the Chat menu with Dashboard, Detach, Alerts, Launcher and Close", async () => {
    const p: ChatHeaderProps = {
      isDetached: false, glowColor: "#00c8ff", fontColor: "#fff", voiceState: "idle", globalError: false,
      chatHeaderRef: React.createRef<HTMLDivElement>(), handleHeaderDragStart: jest.fn(),
      isDashboardOpen: false, onDashboardClick: jest.fn(), onClose: jest.fn(),
      showNotifications: false, openNotifications: jest.fn(), unreadCount: 2, closeDropdowns: jest.fn(),
      activeConversationId: null, onNewThread: jest.fn(), onOpenConversation: jest.fn(),
    }
    render(<ChatHeader {...p} />)
    await waitFor(() => expect(api.fetchThreads).toHaveBeenCalled())
    fireEvent.click(screen.getByRole("button", { name: "More" }))
    expect(screen.getByRole("menu").getAttribute("data-wing-menu")).toBe("Chat")
    expect(screen.getAllByRole("menuitem")).toHaveLength(5)
    fireEvent.click(screen.getByRole("menuitem", { name: /Dashboard/ }))
    expect(p.onDashboardClick).toHaveBeenCalledTimes(1)
  })
})
