import "@testing-library/jest-dom"
import { prepareDashboard, mountDashboard } from "./dashboardKit"
import { screen, fireEvent, cleanup, waitFor, act, within } from "@testing-library/react"
import { invoke } from "@tauri-apps/api/core"
import * as wing from "@/hooks/useDetachedWing"

jest.mock("@tauri-apps/api/core", () => ({ invoke: jest.fn().mockResolvedValue(undefined) }))

const settledPlaces = () => Array.from(document.querySelectorAll("[data-place]")).map((b) => b.getAttribute("data-place"))
const more = () => screen.getByRole("button", { name: "More" })

describe("dashboard header: one ◉ menu, no row of icon buttons", () => {
  beforeEach(() => prepareDashboard())
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("has no standalone chat, detach, launcher or alerts button in the header", () => {
    mountDashboard({ onClose: jest.fn(), onOpenChat: jest.fn(), spotlightState: "dashboardSpotlight", unreadCount: 2 })
    const header = screen.getByTestId("dash-header")
    for (const t of ["Open Chat", "Move the dashboard to its own window", "Open IRIS Launcher", "Close Dashboard", "Notifications"]) {
      expect(within(header).queryByTitle(t)).toBeNull()
    }
    // the header holds the Xur button and the ◉ button only
    expect(within(header).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Show or hide place names", "More"])
  })

  it("◉ lists Chat, Detach, Alerts, launcher and Close, each with today's handler", async () => {
    ;(wing.detachWing as jest.Mock).mockResolvedValue(true)
    const onClose = jest.fn(), onOpenChat = jest.fn(), onNotificationsClick = jest.fn()
    mountDashboard({ onClose, onOpenChat, onNotificationsClick, spotlightState: "dashboardSpotlight", unreadCount: 3 })
    const open = () => fireEvent.click(more())
    open()
    expect(screen.getByRole("menu").getAttribute("data-wing-menu")).toBe("Dashboard")
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual([
      expect.stringContaining("Chat"), expect.stringContaining("Detach"), expect.stringContaining("Alerts"),
      expect.stringContaining("IRIS launcher"), expect.stringContaining("Close"),
    ])
    expect(screen.getByRole("menuitem", { name: /Alerts/ }).textContent).toContain("3")

    fireEvent.click(screen.getByRole("menuitem", { name: /Chat/ }))
    expect(onOpenChat).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole("menu")).toBeNull()

    open(); fireEvent.click(screen.getByRole("menuitem", { name: /Alerts/ }))
    expect(onNotificationsClick).toHaveBeenCalledTimes(1)

    open(); fireEvent.click(screen.getByRole("menuitem", { name: /IRIS launcher/ }))
    expect(invoke).toHaveBeenCalledWith("launch_launcher")

    open(); fireEvent.click(screen.getByRole("menuitem", { name: /Detach/ }))
    await waitFor(() => expect(wing.detachWing).toHaveBeenCalledWith("dashboard"))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1)) // detaching closes the wing here

    onClose.mockClear()
    open(); fireEvent.click(screen.getByRole("menuitem", { name: /Close/ }))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it("offers Chat only where Open Chat showed, and Close only with a close handler; reattach when detached", async () => {
    mountDashboard({ isDetached: true })
    fireEvent.click(more())
    const names = screen.getAllByRole("menuitem").map((m) => m.textContent)
    expect(names.some((n) => n?.includes("Chat"))).toBe(false)
    expect(names.some((n) => n?.includes("Close"))).toBe(false)
    fireEvent.click(screen.getByRole("menuitem", { name: /Put the dashboard back/ }))
    await waitFor(() => expect(wing.reattachWing).toHaveBeenCalledWith("dashboard"))
  })

  it("Esc closes the menu and goes no further", () => {
    mountDashboard({ onClose: jest.fn() })
    fireEvent.click(more())
    const outer = jest.fn()
    window.addEventListener("keydown", outer)
    fireEvent.keyDown(document.body, { key: "Escape" })
    window.removeEventListener("keydown", outer)
    expect(screen.queryByRole("menu")).toBeNull()
    expect(outer).not.toHaveBeenCalled()
  })

  it("shows the place as the title and 'settings' as the sub line", () => {
    mountDashboard()
    const header = screen.getByTestId("dash-header")
    expect(within(header).getByText("Voice")).toBeInTheDocument()
    expect(screen.getByTestId("dash-sub").textContent).toBe("settings")
  })
})

describe("the rail: a spine with two views", () => {
  beforeEach(() => prepareDashboard())
  afterEach(() => { cleanup(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it("Settings lists the six tabs; the Inference console is not one", () => {
    mountDashboard()
    expect(screen.getByRole("button", { name: "Settings", pressed: true })).toBeInTheDocument()
    expect(settledPlaces()).toEqual(["voice", "agent", "automate", "system", "customize", "monitor"])
    expect(screen.queryByText(/inference console/i)).toBeNull()
  })

  it("Surfaces lists the hub, browser, models and marketplace and opens the hub", async () => {
    mountDashboard()
    fireEvent.click(screen.getByRole("button", { name: "Surfaces" }))
    expect(settledPlaces()).toEqual(["hub", "browser", "models", "marketplace"])
    expect(await screen.findByTestId("hub-surface")).toBeInTheDocument()
    expect(screen.getByTestId("dash-sub").textContent).toBe("surface")
    fireEvent.click(document.querySelector('[data-place="models"]') as HTMLElement)
    expect(await screen.findByTestId("models-surface")).toBeInTheDocument()
    // back to Settings: the tab it was on
    fireEvent.click(screen.getByRole("button", { name: "Settings" }))
    expect(settledPlaces()[0]).toBe("voice")
    expect(document.querySelector('[data-place="voice"]')!.getAttribute("aria-current")).toBe("true")
    expect(screen.queryByTestId("models-surface")).toBeNull()
  })

  it("open_inference_console still routes, to the Monitor tab", () => {
    mountDashboard()
    act(() => { window.dispatchEvent(new CustomEvent("iris:card_action", { detail: { action: "open_inference_console" } })) })
    expect(document.querySelector('[data-place="monitor"]')!.getAttribute("aria-current")).toBe("true")
    expect(screen.getByTestId("monitor-page")).toBeInTheDocument()
    expect(screen.getByTestId("dash-sub").textContent).toBe("settings · live")
  })

  it("the Xur button folds the rail to orbs and unfolds it", () => {
    mountDashboard()
    const rail = screen.getByTestId("dash-rail")
    expect(rail.getAttribute("data-folded")).toBe("false")
    fireEvent.click(screen.getByRole("button", { name: "Show or hide place names" }))
    expect(rail.getAttribute("data-folded")).toBe("true")
    fireEvent.click(screen.getByRole("button", { name: "Show or hide place names" }))
    expect(rail.getAttribute("data-folded")).toBe("false")
  })
})
