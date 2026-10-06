import React from 'react'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { DashboardWing } from '@/components/dashboard-wing'
import { SpotlightState } from '@/hooks/useUILayoutState'
import { installCanvasStub, setHidden, setReducedMotion } from './canvasStub'

jest.mock('@/components/dark-glass-dashboard', () => ({
  DarkGlassDashboard: () => <div data-testid="dashboard-content" />,
}))
jest.mock('@/contexts/NavigationContext', () => ({ useNavigation: () => ({ voiceState: 'idle' }) }))
jest.mock('@/hooks/useLauncherMode', () => ({ useLauncherMode: () => ({ isDeveloper: false }) }))
jest.mock('@/contexts/BrandColorContext', () => {
  const actual = jest.requireActual('@/contexts/BrandColorContext')
  const cfg = actual.PRISM_THEMES.aether
  return { ...actual, useBrandColor: () => ({ getThemeConfig: () => cfg }) }
})

describe('DashboardWing edge chrome', () => {
  beforeEach(() => {
    installCanvasStub({ w: 400, h: 600 })
    setHidden(false)
    setReducedMotion(true) // one static frame: no loop to leak out of the test
  })
  afterEach(() => { cleanup(); jest.restoreAllMocks() })

  it('renders the EdgeLight aperture and wires it to onSpotlightToggle', () => {
    const onSpotlightToggle = jest.fn()
    render(<DashboardWing isOpen onClose={() => {}} onSpotlightToggle={onSpotlightToggle} />)
    expect(screen.getByTestId('dashboard-content')).toBeTruthy()
    expect(screen.getByTestId('edge-light')).toBeTruthy()
    expect(screen.getByTestId('edge-trail')).toBeTruthy()
    fireEvent.click(screen.getByTitle('Maximize dashboard'))
    expect(onSpotlightToggle).toHaveBeenCalledTimes(1)
  })

  it('shows the restore title and the lit edge in dashboard spotlight', () => {
    render(
      <DashboardWing isOpen onClose={() => {}} onSpotlightToggle={() => {}} spotlightState={SpotlightState.DASHBOARD_SPOTLIGHT} />,
    )
    expect(screen.getByTitle('Restore balanced view').getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByTestId('edge-light').getAttribute('data-spotlit')).toBe('true')
  })

  it('keeps today\'s dimmed, click-through look when the chat is spotlit', () => {
    const { container } = render(
      <DashboardWing isOpen onClose={() => {}} onSpotlightToggle={() => {}} spotlightState={SpotlightState.CHAT_SPOTLIGHT} />,
    )
    const outer = container.firstElementChild as HTMLElement
    expect(outer.style.filter).toBe('saturate(0.6) blur(2px)')
    expect(outer.style.pointerEvents).toBe('none')
  })

  it('has no aperture without a toggle handler', () => {
    render(<DashboardWing isOpen onClose={() => {}} />)
    expect(screen.queryByTestId('edge-light')).toBeNull()
  })
})
