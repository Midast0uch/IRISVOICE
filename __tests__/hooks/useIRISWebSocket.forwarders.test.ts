/**
 * Guard: one window event = one socket send, however many hook instances are mounted.
 *
 * useIRISWebSocket is mounted several times in the live app (3 on 2026-10-12) and
 * every instance shares ONE module-level WebSocket. The takeover forwarders
 * (window event -> WS message) must live at module level with a refcount. If each
 * instance keeps its own listeners, a single user click is sent once per instance.
 *
 * The fake socket below replaces global WebSocket for this file only. Module state
 * (_sharedWs, refcounts) persists across cases, so each case unmounts everything
 * and runs the deferred socket close (2 s) under fake timers.
 */
import { renderHook, act } from "@testing-library/react";
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket";

const FORWARDED_TYPES = ["takeover_input", "takeover_frame_ack", "browser_viewport"];

// One send spy for every socket the hook opens in this file.
const sendSpy = jest.fn();

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.OPEN;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    sendSpy(data);
  }

  close() {
    // No onclose: the test does not want a reconnect timer.
    this.readyState = FakeWebSocket.CLOSED;
  }
}

const RealWebSocket = (globalThis as any).WebSocket;

// Messages the socket received from the forwarders, parsed. Other sends (burst
// messages on open, set_web_mode on connect) are dropped by the type filter.
function forwardedSends(): Array<{ type: string; payload: Record<string, unknown> }> {
  return sendSpy.mock.calls
    .map(([raw]) => JSON.parse(raw as string))
    .filter((m) => FORWARDED_TYPES.includes(m.type));
}

function countByType(type: string): number {
  return forwardedSends().filter((m) => m.type === type).length;
}

// Opens the shared socket the way the browser does, then drops the burst sends
// so only the event under test is counted.
function openSharedSocket() {
  const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  act(() => {
    ws.onopen?.({});
  });
  sendSpy.mockClear();
}

function dispatchForwardedEvents() {
  act(() => {
    window.dispatchEvent(
      new CustomEvent("iris:takeover_frame_ack", { detail: { run_id: "r1", frame_seq: 1 } }),
    );
    window.dispatchEvent(
      new CustomEvent("iris:takeover_input", {
        detail: { run_id: "r1", kind: "click", x: 0.5, y: 0.5 },
      }),
    );
  });
}

let mounted: Array<() => void> = [];

function mountInstance() {
  const { unmount } = renderHook(() => useIRISWebSocket());
  mounted.push(unmount);
  return unmount;
}

beforeAll(() => {
  (globalThis as any).WebSocket = FakeWebSocket;
});

afterAll(() => {
  (globalThis as any).WebSocket = RealWebSocket;
});

beforeEach(() => {
  jest.useFakeTimers();
  FakeWebSocket.instances = [];
  sendSpy.mockClear();
  mounted = [];
});

afterEach(() => {
  act(() => {
    for (const unmount of mounted) unmount();
  });
  mounted = [];
  // Runs the deferred socket close so the next case opens a fresh socket.
  act(() => {
    jest.advanceTimersByTime(3000);
  });
  jest.useRealTimers();
});

describe("takeover forwarders: one window event = one socket send", () => {
  it("sends each forwarded event exactly once with three mounted instances", () => {
    mountInstance();
    mountInstance();
    mountInstance();
    expect(FakeWebSocket.instances).toHaveLength(1);

    openSharedSocket();
    dispatchForwardedEvents();

    expect(countByType("takeover_frame_ack")).toBe(1);
    expect(countByType("takeover_input")).toBe(1);
    expect(forwardedSends()).toEqual([
      { type: "takeover_frame_ack", payload: { run_id: "r1", frame_seq: 1 }, seq: expect.any(Number) },
      { type: "takeover_input", payload: { run_id: "r1", kind: "click", x: 0.5, y: 0.5 }, seq: expect.any(Number) },
    ]);
  });

  it("sends nothing after all three instances unmount", () => {
    const unmounts = [mountInstance(), mountInstance(), mountInstance()];
    openSharedSocket();

    act(() => {
      for (const unmount of unmounts) unmount();
    });
    mounted = [];
    sendSpy.mockClear();

    dispatchForwardedEvents();

    expect(forwardedSends()).toHaveLength(0);
  });

  it("still sends exactly once after two of three instances unmount", () => {
    const unmounts = [mountInstance(), mountInstance(), mountInstance()];
    openSharedSocket();

    act(() => {
      unmounts[0]();
      unmounts[1]();
    });
    mounted = [unmounts[2]];
    sendSpy.mockClear();

    dispatchForwardedEvents();

    expect(countByType("takeover_frame_ack")).toBe(1);
    expect(countByType("takeover_input")).toBe(1);
  });
});
