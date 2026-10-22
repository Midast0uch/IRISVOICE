/**
 * A card action that opens a surface (open_models_screen, open_inference_console) asks for the dashboard
 * spotlight ONLY when the dashboard is not spotlit yet. onRequestSpotlight is a TOGGLE: calling it while the
 * dashboard is already spotlit turns the spotlight OFF.
 *
 * Found 2026-10-21: the check compared spotlightState with 'DASHBOARD_SPOTLIGHT', but SpotlightState's VALUE is
 * 'dashboardSpotlight' (hooks/useUILayoutState.ts), so the check was always true and the toggle always ran.
 */
import "@testing-library/jest-dom"
import { prepareDashboard, mountDashboard } from "./dashboardKit"
import { act, cleanup } from "@testing-library/react"
import { SpotlightState } from "@/hooks/useUILayoutState"

const fire = (action: string) =>
  act(() => { window.dispatchEvent(new CustomEvent("iris:card_action", { detail: { action } })) })

const ACTIONS = ["open_models_screen", "open_inference_console"]

describe("a card action asks for the spotlight only when the dashboard is not spotlit", () => {
  beforeEach(() => prepareDashboard())
  afterEach(() => { cleanup(); jest.clearAllMocks() })

  it.each(ACTIONS)("%s with the dashboard already spotlit leaves the spotlight on", (action) => {
    const onRequestSpotlight = jest.fn()
    mountDashboard({ spotlightState: SpotlightState.DASHBOARD_SPOTLIGHT, onRequestSpotlight })
    fire(action)
    expect(onRequestSpotlight).not.toHaveBeenCalled()
  })

  it.each(ACTIONS)("%s in the balanced layout asks for the spotlight once", (action) => {
    const onRequestSpotlight = jest.fn()
    mountDashboard({ spotlightState: SpotlightState.BALANCED, onRequestSpotlight })
    fire(action)
    expect(onRequestSpotlight).toHaveBeenCalledTimes(1)
  })
})
