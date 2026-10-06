import React from 'react'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { EdgeLight } from '@/components/chrome/EdgeLight'
import { installCanvasStub, setReducedMotion, setHidden, type CanvasLog } from './canvasStub'

const PALETTE = ['hsl(190, 100%, 60%)', 'hsl(220, 90%, 65%)', 'hsl(150, 80%, 55%)'] as const

function mount(over: Partial<React.ComponentProps<typeof EdgeLight>> = {}) {
  const onAperture = jest.fn()
  const utils = render(
    <div style={{ position: 'relative' }}>
      <EdgeLight
        glowColor="#00c8ff"
        palette={PALETTE}
        spotlit={false}
        onAperture={onAperture}
        apertureTitle="Maximize dashboard"
        isActive={false}
        {...over}
      />
    </div>,
  )
  return { onAperture, ...utils }
}

describe('EdgeLight', () => {
  let log: CanvasLog
  let raf: jest.SpyInstance
  beforeEach(() => {
    log = installCanvasStub()
    setHidden(false)
    setReducedMotion(false)
    raf = jest.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1)
    jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
  })
  afterEach(() => { cleanup(); jest.restoreAllMocks() })

  it('aperture click calls onAperture', () => {
    const { onAperture } = mount()
    fireEvent.click(screen.getByRole('button', { name: 'Maximize dashboard' }))
    expect(onAperture).toHaveBeenCalledTimes(1)
  })

  it('aperture has a title, an aria-label and the pressed state of isActive', () => {
    const { rerender } = mount()
    const btn = screen.getByTitle('Maximize dashboard')
    expect(btn.getAttribute('aria-label')).toBe('Maximize dashboard')
    expect(btn.getAttribute('aria-pressed')).toBe('false')
    rerender(
      <EdgeLight glowColor="#00c8ff" palette={PALETTE} spotlit onAperture={() => {}} apertureTitle="Restore balanced view" isActive />,
    )
    const on = screen.getByTitle('Restore balanced view')
    expect(on.getAttribute('aria-pressed')).toBe('true')
  })

  it('reports the spotlit state', () => {
    mount({ spotlit: false })
    expect(screen.getByTestId('edge-light').getAttribute('data-spotlit')).toBe('false')
    cleanup()
    mount({ spotlit: true })
    expect(screen.getByTestId('edge-light').getAttribute('data-spotlit')).toBe('true')
  })

  it('draws the steady glow near the aperture only when spotlit', () => {
    mount({ spotlit: false })
    ;(raf.mock.calls[0][0] as FrameRequestCallback)(1000)
    expect(log.strokeWidths).not.toContain(1.2)
    cleanup()
    log = installCanvasStub()
    mount({ spotlit: true })
    ;(raf.mock.calls[raf.mock.calls.length - 1][0] as FrameRequestCallback)(1000)
    expect(log.strokeWidths.filter((w) => w === 1.2).length).toBe(2)
  })

  it('animates with requestAnimationFrame and paints the spotlight glow in a frame', () => {
    mount({ spotlit: true })
    expect(raf).toHaveBeenCalled()
    const frame = raf.mock.calls[0][0] as FrameRequestCallback
    frame(1000)
    expect(log.strokeWidths.filter((w) => w === 1.2).length).toBe(2)
    // first frame emits a light: two pulse strokes (one each way)
    expect(log.strokeWidths.filter((w) => w === 1.3).length).toBe(2)
  })

  it('paints no travelling light when idle without a frame, and none in reduced motion', () => {
    setReducedMotion(true)
    mount({ spotlit: true })
    expect(raf).not.toHaveBeenCalled()
    // one static frame: line + spotlight glow, no pulses
    expect(log.strokeWidths).toContain(1.2)
    expect(log.strokeWidths).not.toContain(1.3)
  })

  it('does not schedule frames while the document is hidden', () => {
    setHidden(true)
    mount()
    expect(raf).not.toHaveBeenCalled()
  })

  it('exposes the working state', () => {
    mount({ working: true, workingColor: '#f2c14e' })
    expect(screen.getByTestId('edge-light').getAttribute('data-working')).toBe('true')
  })
})
