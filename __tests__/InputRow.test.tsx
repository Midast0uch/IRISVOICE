/**
 * Phase 5 (specs/phase-5-switcher) — Wave 1, T1.3.
 *
 * REQ-1: the Send pill is gone; `Enter` sends; `Shift+Enter` does not; and
 * every one of the three conditions the button's `disabled` used to carry
 * (`!inputText.trim() || isTyping || voiceState === 'listening'`) still
 * blocks a send from `Enter` — because the guard moved into
 * `handleSendMessage` itself (D-1), not because the button still exists.
 *
 * ⚠️ The guard assertions are the point of this file — parametrized over all
 * three conditions. Dropping one is a test modification (CLAUDE.md, "THE TEST
 * RULE — ABSOLUTE").
 *
 * NOTE on querying: the input row's ancestors are `motion.div`s. The
 * `framer-motion` mock below returns a fresh forwardRef wrapper every time
 * `motion.<tag>` is accessed (a Proxy `get` trap), so its component "type"
 * differs between renders and React remounts the subtree — including the
 * textarea — whenever anything upstream re-renders (e.g. an effect-driven
 * fetch resolving). Every interaction below re-queries the live element via
 * `getTextarea()` immediately before firing an event rather than holding a
 * DOM reference captured earlier, which can go stale (detached) across an
 * intervening `act()`.
 */
import "@testing-library/jest-dom"
import { render, screen, fireEvent, act } from "@testing-library/react"
import React from "react"
import ChatWing from "@/components/chat-view"
import { CrawlProvider } from "@/hooks/CrawlProvider"

// jsdom has no matchMedia — useReducedMotion (pulled in by chat-view) needs it.
beforeAll(() => {
  if (!window.matchMedia) {
    ;(window as any).matchMedia = (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })
  }
})

// Controllable per-test; default is the "everything idle, nothing typed" case.
const mockNav = {
  voiceState: "idle" as
    | "idle"
    | "listening"
    | "processing_conversation"
    | "processing_tool"
    | "speaking"
    | "error",
  isChatTyping: false,
  audioLevel: 0,
  setCurrentConversationId: jest.fn(),
  clearChat: jest.fn(),
  activeTheme: { primary: "#00d4ff", glow: "#00d4ff", font: "#ffffff" },
  fieldErrors: {},
}
jest.mock("@/contexts/NavigationContext", () => ({
  useNavigation: () => mockNav,
}))

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00d4ff" },
      text: { primary: "#ffffff" },
    }),
  }),
}))

// ModelSwitcher has its own dedicated test file (__tests__/ModelSwitcher.test.tsx).
// Stubbed here so this file only exercises the input row's send path, per
// design.md's testing strategy (separate files, separate concerns).
jest.mock("@/components/ModelSwitcher", () => ({
  __esModule: true,
  default: () => <div data-testid="model-switcher-stub" />,
}))

// RichDocument pulls in react-markdown, which ships an ESM-only transitive
// dependency (`devlop`) outside this project's `transformIgnorePatterns`
// (jest.config.frontend.cjs — owned by another concurrent agent, not
// touched here). Stubbing the module means Jest never has to transform the
// real file or its dependency graph; unrelated to the send path this file
// tests.
jest.mock("@/components/chat/RichDocument", () => ({
  __esModule: true,
  RichDocument: () => <div data-testid="rich-document-stub" />,
}))

jest.mock("framer-motion", () => {
  const React = require("react")
  const motion: any = new Proxy(
    {},
    {
      get: (_t: any, tag: string) =>
        React.forwardRef((p: any, ref: any) =>
          React.createElement(tag, { ...p, ref }, p?.children)
        ),
    }
  )
  return { motion, AnimatePresence: ({ children }: any) => children }
})

function getTextarea(): HTMLTextAreaElement {
  return screen.getByPlaceholderText(/type command or drop file|listening/i) as HTMLTextAreaElement
}

// ChatWing calls useCrawlContext() (chat-view.tsx:468), which throws outside a
// <CrawlProvider> (hooks/CrawlProvider.tsx:68). The real provider is used —
// not a mock — because with no session id in sessionStorage its mount effect
// (hooks/CrawlProvider.tsx:47-55) finds nothing to restore and returns without
// fetching, and its inner useCrawl -> useCrawlSSE only opens an EventSource
// when the (unused here) primary WS is reported down, so mounting it does no
// network/websocket I/O in this test file.

beforeEach(() => {
  mockNav.voiceState = "idle"
  mockNav.isChatTyping = false
  jest.clearAllMocks()
  global.fetch = jest.fn().mockImplementation((url: string) => {
    if (typeof url === "string" && url === "/api/conversations") {
      return Promise.resolve({ ok: true, json: async () => ({ conversations: [] }) } as Response)
    }
    if (typeof url === "string" && url.startsWith("/api/conversations")) {
      return Promise.resolve({ ok: true, json: async () => ({ id: "thread_1" }) } as Response)
    }
    return Promise.resolve({ ok: true, json: async () => ({}) } as Response)
  }) as any
})

describe("Chat input row — Send pill removed, Enter carries the guards (REQ-1)", () => {
  it("AC1: no Send button is rendered in the input row", async () => {
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} />
        </CrawlProvider>
      )
    })
    expect(screen.queryByTitle("Send message")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /send message/i })).not.toBeInTheDocument()
  })

  it("AC2: Enter sends when nothing blocks it — input clears", async () => {
    const sendMessage = jest.fn()
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
        </CrawlProvider>
      )
    })
    await act(async () => {
      fireEvent.change(getTextarea(), { target: { value: "hello iris" } })
    })
    expect(getTextarea().value).toBe("hello iris")
    await act(async () => {
      fireEvent.keyDown(getTextarea(), { key: "Enter", shiftKey: false })
    })
    // handleSendMessage clears inputText synchronously, before any network
    // await — proof the send path ran (REQ-1 AC2).
    expect(getTextarea().value).toBe("")
    expect(sendMessage).toHaveBeenCalledWith(
      "text_message",
      expect.objectContaining({ text: "hello iris" })
    )
  })

  it("AC2: Shift+Enter does not send", async () => {
    const sendMessage = jest.fn()
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
        </CrawlProvider>
      )
    })
    await act(async () => {
      fireEvent.change(getTextarea(), { target: { value: "line one" } })
    })
    await act(async () => {
      fireEvent.keyDown(getTextarea(), { key: "Enter", shiftKey: true })
    })
    // Shift+Enter must NOT trigger handleSendMessage — input is untouched.
    expect(getTextarea().value).toBe("line one")
    expect(sendMessage).not.toHaveBeenCalledWith("text_message", expect.anything())
  })

  describe("AC3: each removed disabled condition still blocks a send from Enter", () => {
    it("blocks when input is empty", async () => {
      const sendMessage = jest.fn()
      await act(async () => {
        render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
        </CrawlProvider>
      )
      })
      expect(getTextarea().value).toBe("")
      await act(async () => {
        fireEvent.keyDown(getTextarea(), { key: "Enter", shiftKey: false })
      })
      expect(sendMessage).not.toHaveBeenCalledWith("text_message", expect.anything())
    })

    it("sends while isTyping (isChatTyping true) — queued, not blocked", async () => {
      // Amended per specs/long-horizon-der-execution + live finding: the old
      // `isTyping` block swallowed sends during long websearch turns (user
      // could not send anything for 23 minutes). The backend per-session
      // message lock QUEUES messages in order, so a send during a running
      // turn is safe and must be allowed.
      mockNav.isChatTyping = true
      const sendMessage = jest.fn()
      await act(async () => {
        render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
        </CrawlProvider>
      )
      })
      await act(async () => {
        fireEvent.change(getTextarea(), { target: { value: "queued message" } })
      })
      await act(async () => {
        fireEvent.keyDown(getTextarea(), { key: "Enter", shiftKey: false })
      })
      // Send went through — text cleared, WS told to send.
      expect(getTextarea().value).toBe("")
      expect(sendMessage).toHaveBeenCalledWith(
        "text_message",
        expect.objectContaining({ text: "queued message" })
      )
    })

    it("blocks while voiceState === 'listening'", async () => {
      mockNav.voiceState = "listening"
      const sendMessage = jest.fn()
      await act(async () => {
        render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
        </CrawlProvider>
      )
      })
      // Programmatically set a value even though the textarea is disabled
      // while listening — proves the BLOCK comes from the guard inside
      // handleSendMessage, not merely from the field being unfocusable.
      await act(async () => {
        fireEvent.change(getTextarea(), { target: { value: "should not send" } })
      })
      await act(async () => {
        fireEvent.keyDown(getTextarea(), { key: "Enter", shiftKey: false })
      })
      expect(sendMessage).not.toHaveBeenCalledWith("text_message", expect.anything())
    })
  })

  it("AC4: the other row controls (web toggle, upload, model switcher) remain present and enabled", async () => {
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} />
        </CrawlProvider>
      )
    })
    expect(screen.getByTitle(/web mode/i)).toBeInTheDocument()
    expect(screen.getByTitle(/upload file/i)).toBeEnabled()
    expect(screen.getByTestId("model-switcher-stub")).toBeInTheDocument()
  })
})
