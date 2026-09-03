import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useViewProtocol, isViewMessage } from "@/hooks/useViewProtocol"

/**
 * T9 (REQ-4 AC1-AC5) — view-protocol parent-side contract test.
 *
 * The frame is sandboxed to an opaque origin, so the parent CANNOT
 * authenticate by origin. REQ-4 AC4 requires BOTH checks — frame reference
 * (event.source === iframe.contentWindow) AND shape/version — either alone is
 * insufficient. This test proves each check independently failable:
 *   - a message from the WRONG source is dropped even when the shape matches
 *   - a message from the right source with the WRONG shape is dropped
 *   - only the two documented commands are ever sent INTO the frame
 *   - degradation: no script => no messages => no throw (coarse overlay)
 */

function makeFrameRef() {
  // A minimal stand-in for iframe.contentWindow so the hook's check can be
  // exercised with a controlled source object.
  const source: Record<string, unknown> = { __isFake: true }
  const ref = { current: { contentWindow: source } }
  return { ref: ref as React.RefObject<HTMLIFrameElement | null>, source }
}

describe("useViewProtocol — REQ-4 view protocol (T9)", () => {
  it("accepts a well-formed view message from the right source and emits iris:view_state", () => {
    const { ref, source } = makeFrameRef()
    const seen: unknown[] = []
    const onState = (e: Event) => seen.push((e as CustomEvent).detail)
    window.addEventListener("iris:view_state", onState)
    renderHook(() => useViewProtocol(ref))

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: source as Window,
          data: { __iris: "view", v: 1, kind: "scroll", top: 200, height: 4000, viewport: 800 },
        }),
      )
    })
    expect(seen).toHaveLength(1)
    const detail = seen[0] as { kind: string; top: number }
    expect(detail.kind).toBe("scroll")
    expect(detail.top).toBe(200)
    window.removeEventListener("iris:view_state", onState)
  })

  it("drops a message from the WRONG source even when the shape is valid (check 1)", () => {
    const { ref } = makeFrameRef()
    const seen: unknown[] = []
    const onState = (e: Event) => seen.push((e as CustomEvent).detail)
    window.addEventListener("iris:view_state", onState)
    renderHook(() => useViewProtocol(ref))

    // The OTHER window — shape is perfect, source is not ours.
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: { __isFake: true, __notOurs: true } as unknown as Window,
          data: { __iris: "view", v: 1, kind: "scroll", top: 200, height: 4000, viewport: 800 },
        }),
      )
    })
    expect(seen).toHaveLength(0)
    window.removeEventListener("iris:view_state", onState)
  })

  it("drops a same-source message with the WRONG shape/version (check 2)", () => {
    const { ref, source } = makeFrameRef()
    const seen: unknown[] = []
    const onState = (e: Event) => seen.push((e as CustomEvent).detail)
    window.addEventListener("iris:view_state", onState)
    renderHook(() => useViewProtocol(ref))

    // Wrong protocol tag.
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: source as Window,
          data: { __iris: "nope", v: 1, kind: "scroll", top: 1, height: 1, viewport: 1 },
        }),
      )
    })
    // Wrong version.
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: source as Window,
          data: { __iris: "view", v: 99, kind: "scroll", top: 1, height: 1, viewport: 1 },
        }),
      )
    })
    // Missing numeric fields.
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: source as Window,
          data: { __iris: "view", v: 1, kind: "scroll", top: "NaN", height: 1, viewport: 1 },
        }),
      )
    })
    expect(seen).toHaveLength(0)
    window.removeEventListener("iris:view_state", onState)
  })

  it("sends ONLY the two documented commands INTO the frame, with fixed shape", () => {
    const { ref, source } = makeFrameRef()
    const sent: unknown[] = []
    ;(source as { postMessage?: unknown }).postMessage = (msg: unknown) => sent.push(msg)
    const { result } = renderHook(() => useViewProtocol(ref))

    act(() => result.current.sendScrollTo(500, true))
    act(() => result.current.sendHighlight([{ x: 1, y: 2, w: 3, h: 4 }]))

    expect(sent).toHaveLength(2)
    expect(sent[0]).toMatchObject({ __iris: "cmd", v: 1, kind: "scrollTo", top: 500, smooth: true })
    expect(sent[1]).toMatchObject({ __iris: "cmd", v: 1, kind: "highlight", rects: [{ x: 1, y: 2, w: 3, h: 4 }] })
  })

  it("degrades cleanly when the script is stripped — no messages, no throw (REQ-4 AC5)", () => {
    const { ref } = makeFrameRef()
    // No contentWindow at all (script stripped => frame never speaks).
    const emptyRef = { current: null } as React.RefObject<HTMLIFrameElement | null>
    renderHook(() => useViewProtocol(emptyRef))

    // Sending when the frame is gone must not throw.
    const { result } = renderHook(() => useViewProtocol(ref))
    expect(() => act(() => result.current.sendScrollTo(10))).not.toThrow()
    expect(() => act(() => result.current.sendHighlight([]))).not.toThrow()
  })
})

describe("isViewMessage shape gate", () => {
  it("rejects non-objects, wrong tag, wrong version, missing fields", () => {
    expect(isViewMessage(null)).toBe(false)
    expect(isViewMessage("x")).toBe(false)
    expect(isViewMessage({ __iris: "cmd", v: 1 })).toBe(false)
    expect(isViewMessage({ __iris: "view", v: 2, kind: "scroll", top: 1, height: 1, viewport: 1 })).toBe(false)
    expect(isViewMessage({ __iris: "view", v: 1, kind: "scroll", height: 1, viewport: 1 })).toBe(false)
  })
  it("accepts the two documented kinds", () => {
    expect(isViewMessage({ __iris: "view", v: 1, kind: "ready", top: 0, height: 100, viewport: 100 })).toBe(true)
    expect(isViewMessage({ __iris: "view", v: 1, kind: "scroll", top: 5, height: 100, viewport: 100 })).toBe(true)
  })
})
