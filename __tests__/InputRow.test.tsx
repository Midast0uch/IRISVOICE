/**
 * Phase 5 (specs/phase-5-switcher) — Wave 1, T1.3.
 *
 * REQ-1: `Enter` sends; `Shift+Enter` does not; and the conditions the Send
 * pill's `disabled` used to carry still block a send from `Enter` — because
 * the guard moved into `handleSendMessage` itself (D-1), not because a button
 * happens to exist. The original three were `!inputText.trim() || isTyping ||
 * voiceState === 'listening'`; `isTyping` was later retired from the guard
 * (long-horizon-der-execution: the backend per-session lock queues messages,
 * so a send during a running turn is safe and must be allowed). Two remain.
 *
 * ⚠️ The guard assertions are the point of this file. Dropping one is a test
 * modification (CLAUDE.md, "THE TEST RULE — ABSOLUTE").
 *
 * 2026-09-04 — REQ-1 AC1 (the visibility half) is SUPERSEDED by
 * specs/chatview-dev-cleanup REQ-7, user-signed: a Send control is back,
 * scoped to personal mode. AC1 below was rewritten from "absent" to
 * "present" as a deliberate, recorded decision — and the two REQ-7 blocks at
 * the bottom ADD guard coverage this file never had. The load-bearing half of
 * REQ-1 (AC3: guards live in the send path) is unchanged and still enforced.
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
  it("AC1: an explicit Send control is rendered in the input row", async () => {
    // SUPERSEDED 2026-09-04 by specs/chatview-dev-cleanup REQ-7, signed off by
    // the user. This assertion used to be `expect(...).not.toBeInTheDocument()`:
    // phase-5 REQ-1 deleted the Send pill to free row space. REQ-7 reinstates
    // it, scoped to personal mode only, after a measured width budget showed
    // the textarea (flex-1, no min-width) absorbs the 40px at every wing width.
    //
    // The half of REQ-1 that was actually load-bearing survives untouched:
    // AC3 — the button's disabled conditions living inside handleSendMessage
    // rather than on the button — is still locked by the AC3 block below and by
    // the REQ-7 guard block. Only the visibility half is reversed, and it is
    // reversed deliberately, not by weakening an assertion to make code pass.
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} />
        </CrawlProvider>
      )
    })
    expect(screen.getByTitle("Send message")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /send message/i })).toBeInTheDocument()
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

// specs/chatview-dev-cleanup REQ-7 — ADDED 2026-09-04 when the Send control
// was reinstated. These assert the control is DISABLED under exactly the two
// conditions handleSendMessage guards on (:1844). isChatTyping is deliberately
// absent: the backend per-session lock queues messages, so a send during a
// running turn is allowed (long-horizon-der-execution).
describe("Chat input row — Send control guards (REQ-7 AC2)", () => {
  function getSendButton(): HTMLElement {
    return screen.getByTitle("Send message")
  }

  it("is disabled while the input is empty", async () => {
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} />
        </CrawlProvider>
      )
    })
    expect(getTextarea().value).toBe("")
    expect(getSendButton()).toBeDisabled()
  })

  it("is disabled while voiceState === 'listening'", async () => {
    mockNav.voiceState = "listening"
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} />
        </CrawlProvider>
      )
    })
    expect(getSendButton()).toBeDisabled()
  })

  it("is enabled once text is present and the mic is idle", async () => {
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} />
        </CrawlProvider>
      )
    })
    expect(getSendButton()).toBeDisabled()
    await act(async () => {
      fireEvent.change(getTextarea(), { target: { value: "hello iris" } })
    })
    expect(getSendButton()).toBeEnabled()
  })

  it("stays enabled while isChatTyping — sends queue, they do not block", async () => {
    mockNav.isChatTyping = true
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} />
        </CrawlProvider>
      )
    })
    await act(async () => {
      fireEvent.change(getTextarea(), { target: { value: "queued via button" } })
    })
    expect(getSendButton()).toBeEnabled()
  })
})

// REQ-7 AC3: the control must run handleSendMessage itself. If it grew its own
// send path the two would drift, and phase-5's real lesson — that the guards
// belong in the path, not on the button — would be undone by the back door.
describe("Chat input row — Send control runs the send path (REQ-7 AC3)", () => {
  it("activating the control sends and clears, exactly as Enter does", async () => {
    const sendMessage = jest.fn()
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
        </CrawlProvider>
      )
    })
    await act(async () => {
      fireEvent.change(getTextarea(), { target: { value: "via button" } })
    })
    await act(async () => {
      fireEvent.click(screen.getByTitle("Send message"))
    })
    expect(getTextarea().value).toBe("")
    expect(sendMessage).toHaveBeenCalledWith(
      "text_message",
      expect.objectContaining({ text: "via button" })
    )
  })

  it("a disabled control cannot be clicked into sending", async () => {
    const sendMessage = jest.fn()
    await act(async () => {
      render(
        <CrawlProvider>
          <ChatWing isOpen onClose={() => {}} onDashboardClick={() => {}} sendMessage={sendMessage} />
        </CrawlProvider>
      )
    })
    expect(screen.getByTitle("Send message")).toBeDisabled()
    await act(async () => {
      fireEvent.click(screen.getByTitle("Send message"))
    })
    expect(sendMessage).not.toHaveBeenCalledWith("text_message", expect.anything())
  })
})
