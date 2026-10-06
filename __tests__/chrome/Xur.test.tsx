import React from 'react'
import { render, cleanup } from '@testing-library/react'
import { Xur } from '@/components/Xur'
import { makePaletteSampler } from '@/lib/brandPalette'
import { installCanvasStub, type CanvasLog } from './canvasStub'

const PALETTE = ['hsl(190, 100%, 60%)', 'hsl(220, 90%, 65%)', 'hsl(150, 80%, 55%)'] as const

describe('Xur', () => {
  let log: CanvasLog
  beforeEach(() => {
    log = installCanvasStub({ w: 32, h: 32 })
    // speed 0 draws one frame and stops: run it synchronously
    jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => { cb(1000); return 1 })
  })
  afterEach(() => { cleanup(); jest.restoreAllMocks() })

  it('without a palette draws every particle in the one colour (unchanged)', () => {
    render(<Xur size={32} color="#fbbf24" speed={0} />)
    expect(new Set(log.fillStyles)).toEqual(new Set(['#fbbf24']))
    expect(log.arcs).toBe(69) // 68 trail particles + the lead dot
  })

  it('with a palette interpolates head -> body -> tail along the trail', () => {
    render(<Xur size={32} color="#fbbf24" speed={0} palette={PALETTE} />)
    const sample = makePaletteSampler(PALETTE)
    const used = log.fillStyles as string[]
    expect(new Set(used).size).toBeGreaterThan(3)
    expect(used).not.toContain('#fbbf24')
    expect(used[0]).toBe(sample(0))                     // particle 0 is the head colour
    expect(used[used.length - 1]).toBe(sample(0))       // the lead dot is the head colour too
    expect(used[34]).toBe(sample(34 / 68))              // the body sits mid-trail
    expect(used[67]).toBe(sample(67 / 68))              // the last particle is almost the tail
    expect(log.arcs).toBe(69)
  })
})
