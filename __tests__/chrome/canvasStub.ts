// jsdom has no canvas. This stub records what the chrome components draw.
export interface CanvasLog {
  fillStyles: unknown[]
  strokeWidths: number[]
  strokeCount: number
  arcs: number
}

export function installCanvasStub(size = { w: 400, h: 24 }): CanvasLog {
  const log: CanvasLog = { fillStyles: [], strokeWidths: [], strokeCount: 0, arcs: 0 }
  let lineWidth = 1
  const ctx: Record<string, unknown> = {
    setTransform() {}, scale() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, fill() {},
    arc() { log.arcs++ },
    stroke() { log.strokeCount++; log.strokeWidths.push(lineWidth) },
    createLinearGradient() { return { addColorStop() {} } },
    set fillStyle(v: unknown) { log.fillStyles.push(v) },
    get fillStyle() { return log.fillStyles[log.fillStyles.length - 1] },
    set strokeStyle(_v: unknown) {}, get strokeStyle() { return '' },
    set lineWidth(v: number) { lineWidth = v }, get lineWidth() { return lineWidth },
    globalAlpha: 1,
  }
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((() => ctx) as never)
  Object.defineProperty(HTMLCanvasElement.prototype, 'clientWidth', { configurable: true, get: () => size.w })
  Object.defineProperty(HTMLCanvasElement.prototype, 'clientHeight', { configurable: true, get: () => size.h })
  return log
}

export function setReducedMotion(reduce: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: reduce && q.includes('prefers-reduced-motion'),
    media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    onchange: null, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

export function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
}
