/**
 * The composer's two signs (docs/design/chatview-2026-10-06, concept 2 rev 4):
 *   @ = who hears this      (only @iris; fills the to-chip)
 *   # = what you point at   (ONE list, two groups: "IRIS made" and "This project")
 *
 * ChatWing is rendered whole so the store, the send path and the composer meet
 * the way they do live (same harness as __tests__/composer/composer.test.tsx).
 */
import "@testing-library/jest-dom"
import React from "react"
import { render, screen, fireEvent, act, within } from "@testing-library/react"
import ChatWing from "@/components/chat-view"
import { CrawlProvider } from "@/hooks/CrawlProvider"
import { useWorkspaceStore } from "@/stores/workspaceStore"
import { __resetTurnsForTests } from "@/lib/turns/turnStore"
import { refTriggerOf, WHO_HEARS } from "@/components/chat/composer/refs"

const CONV = "conv_t"

jest.mock("@/hooks/useLauncherMode", () => ({
  useLauncherMode: () => ({ mode: "developer", isDeveloper: true }),
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
jest.mock("@/components/ModelSwitcher", () => ({ __esModule: true, default: () => <div /> }))
jest.mock("@/components/chat/RichDocument", () => ({ __esModule: true, RichDocument: () => <div /> }))
jest.mock("framer-motion", () => {
  const React = require("react")
  const motion: any = new Proxy({}, {
    get: (_t: any, tag: string) =>
      React.forwardRef((p: any, ref: any) => {
        const { whileHover, whileTap, initial, animate, exit, transition, layout, ...rest } = p
        return React.createElement(tag, { ...rest, ref }, p?.children)
      }),
  })
  return { motion, AnimatePresence: ({ children }: any) => children, useReducedMotion: () => false }
})

beforeAll(() => {
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null)
  if (!window.matchMedia) {
    ;(window as any).matchMedia = (query: string) => ({
      matches: false, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })
  }
  if (typeof (AbortSignal as any).timeout !== "function") {
    ;(AbortSignal as any).timeout = () => new AbortController().signal
  }
})

beforeEach(() => {
  jest.clearAllMocks()
  __resetTurnsForTests()
  useWorkspaceStore.setState({
    tabs: [
      { id: "f1", type: "folder", path: "./IRISVOICE", label: "IRISVOICE", icon: "folder", isVirtual: false },
      { id: "t1", type: "file", path: "backend/router.py", label: "router.py", icon: "file", isVirtual: false },
      // a virtual document and a lens tab are not project files
      { id: "v1", type: "document", path: "/workspace/scratch.md", label: "scratch.md", icon: "doc", isVirtual: true },
    ],
    activeTabId: "t1",
  })
  global.fetch = jest.fn().mockImplementation((url: string) => {
    const ok = (body: unknown) => Promise.resolve({ ok: true, json: async () => body } as Response)
    if (url === "/api/conversations") {
      return ok({ conversations: [{ id: CONV, title: "Router budget", messages: [], updated_at: new Date().toISOString() }] })
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
  await act(async () => { await Promise.resolve() })
  return sendMessage
}

const textarea = () => screen.getByPlaceholderText(/command .*shell/i) as HTMLTextAreaElement
const type = async (value: string, caret?: number) =>
  act(async () => {
    fireEvent.change(textarea(), { target: caret === undefined ? { value } : { value, selectionStart: caret, selectionEnd: caret } })
  })
const key = async (k: string) => act(async () => { fireEvent.keyDown(textarea(), { key: k, shiftKey: false }) })
const pickers = () => ({ ref: screen.queryByTestId("ref-picker"), who: screen.queryByTestId("who-picker") })

describe("@ lists only who hears", () => {
  it("opens one 'Who hears this' list with @iris and no task card, artifact, strand or file", async () => {
    await mount()
    await type("hi @")
    const who = await screen.findByTestId("who-picker")
    expect(who).toHaveAccessibleName("Who hears this")
    expect(within(who).getAllByRole("option")).toHaveLength(WHO_HEARS.length)
    expect(within(who).getByRole("option", { name: /@iris/ })).toBeInTheDocument()
    expect(pickers().ref).toBeNull()
    expect(who).not.toHaveTextContent(/task card|artifact|strand|router\.py/)
  })

  it("picking @iris fills the to-chip, drops the sign from the draft, and the payload says to: [@iris]", async () => {
    const send = await mount()
    await type("hi @")
    await act(async () => { fireEvent.mouseDown(await within(await screen.findByTestId("who-picker")).findByRole("option", { name: /@iris/ })) })
    expect(screen.getByTestId("composer-to")).toHaveTextContent("to @iris")
    expect(screen.queryByTestId("composer-who")).toBeNull() // @iris is the to-chip, not a second chip
    expect(textarea().value).toBe("hi ")
    await type("hi iris")
    await key("Enter")
    expect(send).toHaveBeenCalledWith("text_message", expect.objectContaining({ to: ["@iris"] }))
  })

  it("the old @taskcard path is gone: no card list on @ and no @taskcard token is inserted", async () => {
    const send = await mount()
    await type("@")
    await screen.findByTestId("who-picker")
    expect(screen.queryByText(/Reference a task card/)).toBeNull()
    // the @ list asks for no cards; only the # list does
    expect(send).not.toHaveBeenCalledWith("get_cards", { all: true })
    await key("Enter")
    expect(textarea().value).not.toMatch(/taskcard/)
  })
})

describe("# lists two labelled groups", () => {
  it("shows 'IRIS made' (strands) and 'This project' (the folder and open files; no virtual document)", async () => {
    await mount()
    await type("see #")
    const list = await screen.findByTestId("ref-picker")
    expect(pickers().who).toBeNull()
    await within(list).findByRole("option", { name: /#strand_plan/ })
    expect(within(list).getByTestId("ref-group-iris")).toHaveTextContent("IRIS made")
    const project = within(list).getByTestId("ref-group-project")
    expect(project).toHaveTextContent("This project")
    expect(project).toHaveTextContent("IRISVOICE")
    expect(within(list).getByRole("option", { name: /router\.py/ })).toBeInTheDocument()
    expect(within(list).getAllByRole("option").some((o) => /scratch\.md/.test(o.textContent ?? ""))).toBe(false)
    // IRIS made comes first, then the project
    const opts = within(list).getAllByRole("option").map((o) => o.textContent ?? "")
    expect(opts[0]).toMatch(/#strand_plan/)
    expect(opts[opts.length - 1]).toMatch(/router\.py|IRISVOICE/)
  })

  it("chips differ by kind and the payload carries both addresses (a file as file:<path>)", async () => {
    const send = await mount()
    await type("see #")
    const list = await screen.findByTestId("ref-picker")
    await act(async () => { fireEvent.mouseDown(await within(list).findByRole("option", { name: /#strand_plan/ })) })
    await type("see # ")  // new draft: a lone sign followed by a space is not a list
    await type("see #router")
    await act(async () => { fireEvent.mouseDown(await within(await screen.findByTestId("ref-picker")).findByRole("option", { name: /router\.py/ })) })
    const [iris, file] = screen.getAllByTestId("composer-ref")
    expect(iris).toHaveTextContent("#strand_plan")
    expect(iris).toHaveAttribute("data-kind", "iris")
    expect(iris).not.toHaveClass("path")
    expect(file).toHaveTextContent("backend/router.py")
    expect(file).toHaveAttribute("data-kind", "project")
    expect(file).toHaveClass("path") // dashed path chip; the CSS adds the ▸
    expect(file).toHaveAttribute("title", "file:backend/router.py")
    await type("done")
    await key("Enter")
    expect(send).toHaveBeenCalledWith(
      "text_message",
      expect.objectContaining({ refs: ["#strand_plan", "file:backend/router.py"], to: ["@iris"] }),
    )
  })

  it("a task card picked with # resolves like @taskcard did: referenced_cards carries card_id + conversation_id", async () => {
    const send = await mount()
    await type("#")
    await screen.findByTestId("ref-picker")
    // the first # list asks for the cards of every thread, once
    expect(send).toHaveBeenCalledWith("get_cards", { all: true })
    await act(async () => {
      window.dispatchEvent(new CustomEvent("iris:cards", {
        detail: { cards: [{ card_id: "T-38", conversation_id: "conv_old", plan_title: "router window test", total_steps: 3 }] },
      }))
    })
    const option = await within(screen.getByTestId("ref-picker")).findByRole("option", { name: /#T-38/ })
    expect(option).toHaveTextContent("task card · router window test")
    await act(async () => { fireEvent.mouseDown(option) })
    await type("what did it change")
    await key("Enter")
    expect(send).toHaveBeenCalledWith(
      "text_message",
      expect.objectContaining({
        refs: ["#T-38"],
        referenced_cards: [{ card_id: "T-38", conversation_id: "conv_old" }],
      }),
    )
  })
})

describe("a sign stays text", () => {
  // [draft, caret] : the draft ends (or the caret sits) where a list would open
  const STAYS: Array<[string, string, number | null]> = [
    ["inside inline code", "run `ls #", null],
    ["inside a fenced block", "```\nfoo #", null],
    ["after a letter (an address)", "mail a@", null],
    ["after a letter (C#)", "I like C#", null],
    ["after a digit", "v2#", null],
    ["a line-start # followed by a space (a heading)", "# Title", 1],
  ]
  describe.each(["@", "#"])("sign %s", (sign) => {
    it.each(STAYS.filter(([why]) => !(sign === "@" && /heading|C#/.test(why))))("%s", async (_why, draft, caret) => {
      await mount()
      await type(draft.replace(/[#@]$/, sign), caret ?? undefined)
      expect(pickers()).toEqual({ ref: null, who: null })
      expect(textarea().value).toBe(draft.replace(/[#@]$/, sign))
    })
  })

  it("the same signs open a list at a word start and after a closed code span", async () => {
    await mount()
    await type("run `ls` #")
    expect(await screen.findByTestId("ref-picker")).toBeInTheDocument()
    await type("```\ncode\n``` #")
    expect(await screen.findByTestId("ref-picker")).toBeInTheDocument()
  })

  it.each(["@", "#"])("Esc closes the list and keeps the %s as typed", async (sign) => {
    await mount()
    await type(`see ${sign}`)
    await screen.findByTestId(sign === "@" ? "who-picker" : "ref-picker")
    await key("Escape")
    expect(pickers()).toEqual({ ref: null, who: null })
    expect(textarea().value).toBe(`see ${sign}`)
    expect(screen.queryAllByTestId("composer-ref")).toHaveLength(0)
  })

  it("Arrow, Enter and Tab pick from the list as before (Enter picks, does not send)", async () => {
    const send = await mount()
    await type("#")
    const list = await screen.findByTestId("ref-picker")
    await within(list).findByRole("option", { name: /#strand_plan/ })
    await key("ArrowDown")
    expect(within(list).getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true")
    await key("Tab")
    expect(screen.getAllByTestId("composer-ref")).toHaveLength(1)
    expect(send).not.toHaveBeenCalledWith("text_message", expect.anything())
  })
})

describe("refTriggerOf (the rules, alone)", () => {
  it("returns the sign, its query and where it starts", () => {
    expect(refTriggerOf("see #rou", 8)).toEqual({ sign: "#", query: "rou", at: 4 })
    expect(refTriggerOf("@", 1)).toEqual({ sign: "@", query: "", at: 0 })
    expect(refTriggerOf("(#T-38", 6)).toEqual({ sign: "#", query: "T-38", at: 1 })
  })
  it("uses the caret, not the end of the draft", () => {
    expect(refTriggerOf("see # later", 5)).toEqual({ sign: "#", query: "", at: 4 })
    expect(refTriggerOf("see #x later", 12)).toBeNull()
  })
  it("a heading with text typed after the # is plain text", () => {
    expect(refTriggerOf("# Title", 7)).toBeNull()
    expect(refTriggerOf("# ", 1)).toBeNull()
    expect(refTriggerOf("#", 1)).not.toBeNull() // a lone sign still opens
    expect(refTriggerOf("a\n# x", 3)).toBeNull()
  })
})
