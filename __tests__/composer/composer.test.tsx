/**
 * The composer per the approved design (docs/design/chatview-2026-10-06):
 * project bar above the box in both modes, the tray with the to-chip and #
 * reference chips, Enter steers while a turn runs, the send button becomes
 * Stop, and there is no mic button (voice stays wake-word).
 *
 * ChatWing is rendered whole, in both modes, with a conversation on screen so
 * the turn store, the send path and the composer meet the way they do live.
 */
import "@testing-library/jest-dom"
import React from "react"
import { render, screen, fireEvent, act, waitFor, within } from "@testing-library/react"
import ChatWing from "@/components/chat-view"
import { CrawlProvider } from "@/hooks/CrawlProvider"
import { useWorkspaceStore } from "@/stores/workspaceStore"
import { applyTurnMessage, __resetTurnsForTests } from "@/lib/turns/turnStore"

const CONV = "conv_t"

const mockMode = { value: "personal" as "personal" | "developer" }
jest.mock("@/hooks/useLauncherMode", () => ({
  useLauncherMode: () => ({ mode: mockMode.value, isDeveloper: mockMode.value === "developer" }),
}))

const mockNav = {
  voiceState: "idle" as const,
  isChatTyping: false,
  audioLevel: 0,
  setCurrentConversationId: jest.fn(),
  clearChat: jest.fn(),
  activeTheme: { primary: "#00d4ff", glow: "#00d4ff", font: "#ffffff" },
  fieldErrors: {},
}
jest.mock("@/contexts/NavigationContext", () => ({ useNavigation: () => mockNav }))
jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({ getThemeConfig: () => ({ glow: { color: "#00d4ff" }, text: { primary: "#ffffff" } }) }),
}))
jest.mock("@/components/ModelSwitcher", () => ({ __esModule: true, default: () => <div data-testid="model-switcher-stub" /> }))
jest.mock("@/components/chat/RichDocument", () => ({ __esModule: true, RichDocument: () => <div /> }))
jest.mock("framer-motion", () => {
  const React = require("react")
  const motion: any = new Proxy({}, {
    get: (_t: any, tag: string) =>
      React.forwardRef((p: any, ref: any) => {
        // Drop motion-only props so React does not warn about unknown DOM attributes.
        const { whileHover, whileTap, initial, animate, exit, transition, layout, ...rest } = p
        return React.createElement(tag, { ...rest, ref }, p?.children)
      }),
  })
  return { motion, AnimatePresence: ({ children }: any) => children, useReducedMotion: () => false }
})

beforeAll(() => {
  // jsdom has no canvas (the spine draws on one).
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null)
  if (!window.matchMedia) {
    ;(window as any).matchMedia = (query: string) => ({
      matches: false, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })
  }
  // jsdom's AbortSignal has no timeout(); the app calls it on every fetch.
  if (typeof (AbortSignal as any).timeout !== "function") {
    ;(AbortSignal as any).timeout = () => new AbortController().signal
  }
})

beforeEach(() => {
  mockMode.value = "personal"
  jest.clearAllMocks()
  __resetTurnsForTests()
  useWorkspaceStore.setState({ tabs: [], activeTabId: null })
  global.fetch = jest.fn().mockImplementation((url: string) => {
    const ok = (body: unknown) => Promise.resolve({ ok: true, json: async () => body } as Response)
    if (url === "/api/conversations") {
      return ok({
        conversations: [{ id: CONV, title: "Router budget", messages: [], updated_at: new Date().toISOString() }],
      })
    }
    if (url === `/api/threads/${CONV}/strands`) {
      return ok([{ id: "strand_plan", title: "Plan the budget", tags: ["plan"], reports_to: null, updated_at: "", message_count: 2 }])
    }
    return ok({})
  }) as any
})

async function mount(sendMessage = jest.fn()) {
  await act(async () => {
    render(
      <CrawlProvider>
        <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
      </CrawlProvider>,
    )
  })
  // The conversation loads, then becomes the active one.
  await act(async () => { await Promise.resolve() })
  return sendMessage
}

const textarea = () =>
  screen.getByPlaceholderText(/type command|drop file|command .*shell|listening/i) as HTMLTextAreaElement
const type = async (value: string) => act(async () => { fireEvent.change(textarea(), { target: { value } }) })
const enter = async () => act(async () => { fireEvent.keyDown(textarea(), { key: "Enter", shiftKey: false }) })

function startTurn(turnId = "t1") {
  act(() => {
    applyTurnMessage({
      type: "turn.start",
      payload: { v: 1, turn_id: turnId, conversation_id: CONV, strand_id: CONV, author: "user", to: ["@iris"], refs: [], mode: "personal", prompt: "go", ts: Date.now() / 1000 },
    })
  })
}
function endTurn(turnId = "t1", status: "ok" | "cancelled" = "cancelled") {
  act(() => {
    applyTurnMessage({
      type: "turn.end",
      payload: { v: 1, turn_id: turnId, conversation_id: CONV, status, parts: 0, ts: Date.now() / 1000 } as any,
    })
  })
}

describe.each(["personal", "developer"] as const)("composer (%s mode)", (mode) => {
  beforeEach(() => { mockMode.value = mode })

  it("shows the project bar above the message box", async () => {
    useWorkspaceStore.setState({
      tabs: [
        { id: "f1", type: "folder", path: "./IRISVOICE", label: "IRISVOICE", icon: "folder", isVirtual: false },
        { id: "t1", type: "file", path: "backend/router.py", label: "router.py", icon: "file", isVirtual: false },
      ],
      activeTabId: "t1",
    })
    await mount()
    const bar = screen.getByTestId("project-bar")
    expect(within(bar).getByTestId("project-folder")).toHaveTextContent("IRISVOICE")
    const tab = within(bar).getByRole("tab", { name: "router.py" })
    expect(tab).toHaveAttribute("aria-current", "true")
    expect(within(bar).getByTitle("Add a folder or repo")).toBeInTheDocument()
    // above the box
    expect(bar.compareDocumentPosition(textarea()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("the tray shows the to-chip and the send payload carries to: [@iris]", async () => {
    const send = await mount()
    expect(screen.getByTestId("composer-to")).toHaveTextContent("to @iris")
    await type("hello iris")
    await enter()
    expect(send).toHaveBeenCalledWith("text_message", expect.objectContaining({ text: "hello iris", to: ["@iris"], refs: [] }))
  })

  it("# opens a picker of addresses; the payload carries refs (addresses only)", async () => {
    const send = await mount()
    expect(screen.getByTestId("composer-tray")).toHaveTextContent("# adds a reference · @ picks who hears")
    await type("see #")
    const picker = await screen.findByTestId("ref-picker")
    const option = await within(picker).findByRole("option", { name: /#strand_plan/ })
    expect(option).toHaveTextContent("strand · Plan the budget")
    await act(async () => { fireEvent.mouseDown(option) })
    // the chip shows the address, the "#" query leaves the draft, the hint changes
    expect(screen.getByTestId("composer-ref")).toHaveTextContent("#strand_plan")
    expect(textarea().value).toBe("see ")
    expect(screen.getByTestId("composer-tray")).toHaveTextContent("IRIS gets these addresses")
    await type("see this")
    await enter()
    expect(send).toHaveBeenCalledWith("text_message", expect.objectContaining({ refs: ["#strand_plan"], to: ["@iris"] }))
    // the tray is empty again after the send
    expect(screen.queryByTestId("composer-ref")).toBeNull()
  })

  it("a ref chip is removable", async () => {
    await mount()
    await type("#")
    const picker = await screen.findByTestId("ref-picker")
    await act(async () => { fireEvent.mouseDown(await within(picker).findByRole("option", { name: /#strand_plan/ })) })
    await act(async () => { fireEvent.click(screen.getByLabelText("Remove #strand_plan")) })
    expect(screen.queryByTestId("composer-ref")).toBeNull()
  })

  it("Enter while a turn runs sends a steer, not a prompt, and shows the steer line", async () => {
    const send = await mount()
    startTurn()
    await type("use the smaller window")
    await enter()
    expect(send).toHaveBeenCalledWith("steer", expect.objectContaining({ text: "use the smaller window", conversation_id: CONV }))
    expect(send).not.toHaveBeenCalledWith("text_message", expect.anything())
    const line = await screen.findByTestId("steer-note")
    expect(line).toHaveTextContent(
      mode === "developer"
        ? "↳ you steered: use the smaller window · noted"
        : "↳ you said: use the smaller window · IRIS noted it",
    )
  })

  it("the send button becomes Stop IRIS while a turn runs; it sends stop; the turn ends cancelled", async () => {
    const send = await mount()
    expect(screen.getByTitle("Send message")).toBeInTheDocument()
    startTurn()
    const stop = screen.getByRole("button", { name: "Stop IRIS" })
    expect(stop).toHaveAttribute("title", "Stop IRIS")
    expect(stop).toBeEnabled() // even with an empty box
    expect(screen.queryByTitle("Send message")).toBeNull()
    await act(async () => { fireEvent.click(stop) })
    expect(send).toHaveBeenCalledWith("stop", expect.objectContaining({ conversation_id: CONV }))
    expect(send).not.toHaveBeenCalledWith("text_message", expect.anything())
    // the backend answers with turn.end cancelled: the button reads Send again
    endTurn("t1", "cancelled")
    await waitFor(() => expect(screen.getByTitle("Send message")).toBeInTheDocument())
    expect(screen.queryByRole("button", { name: "Stop IRIS" })).toBeNull()
  })

  it("has no mic button (voice stays wake-word)", async () => {
    await mount()
    expect(screen.queryByRole("button", { name: /mic|microphone|voice|dictat|listen/i })).toBeNull()
    expect(screen.queryByTitle(/mic|microphone|voice input|dictat/i)).toBeNull()
  })
})
