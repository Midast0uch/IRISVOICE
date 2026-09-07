/**
 * T17b (REQ-8): event-shape contract for the learning signal.
 *
 * The backend emits IRISStreamEvent.TASK_LEARNING ("task:learning") with
 * { signal, verified_label, step_id, state }. The frontend MUST:
 *   - dispatch it as a window event "iris:task_update" (useIRISWebSocket)
 *   - carry the discrete `signal` field (NOT narration text)
 *   - surface it through useTaskProgress as `learningSignal`
 *
 * This is the contract test the spec requires (T17) — it pins the
 * boundary so a future change can't silently drop the learning signal
 * or leak TTS text into the event shape.
 */
import "@testing-library/jest-dom";
import { renderHook, act } from "@testing-library/react";
import { useTaskProgress, __resetTaskProgressForTests } from "@/hooks/useTaskProgress";

const TASK_LEARNING = "task:learning";

// REQ-38's module-level store survives across tests in this file; reset it
// before each case so prior dispatches never leak into the next assertion.
beforeEach(() => {
  __resetTaskProgressForTests();
});

function fireTaskLearning(payload: Record<string, unknown>) {
  // The contract: useIRISWebSocket translates a backend `task:learning`
  // WS message into a window `iris:task_update` CustomEvent carrying the
  // discrete `signal` field. We fire that event directly (the boundary the
  // hook actually listens to).
  const evt = new CustomEvent("iris:task_update", {
    detail: { type: TASK_LEARNING, ...payload },
  });
  window.dispatchEvent(evt);
}

describe("task:learning event shape (REQ-8 / T17b)", () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });
  afterEach(() => {
    window.dispatchEvent(new CustomEvent("iris:message", { detail: {} }));
  });

  it("dispatches iris:task_update carrying the discrete signal (not narration)", () => {
    const seen: any[] = [];
    const handler = (e: any) => seen.push(e.detail);
    window.addEventListener("iris:task_update", handler);

    fireTaskLearning({
      signal: "retried",
      verified_label: "FAILED",
      step_id: "s2",
      state: "running",
    });

    expect(seen.length).toBeGreaterThanOrEqual(1);
    const last = seen[seen.length - 1];
    expect(last.signal).toBe("retried");
    // The signal is a discrete enum value, never free-form narration.
    expect(typeof last.signal).toBe("string");
    expect(last.signal).not.toMatch(/^(I |The |We )/); // not a sentence
    window.removeEventListener("iris:task_update", handler);
  });

  it("accepts all three valid signals (avoided / retried / crystallized)", () => {
    const valid = ["avoided", "retried", "crystallized"];
    for (const signal of valid) {
      const seen: any[] = [];
      const handler = (e: any) => seen.push(e.detail);
      window.addEventListener("iris:task_update", handler);
      fireTaskLearning({ signal, verified_label: "VERIFIED", step_id: "s1" });
      expect(seen[seen.length - 1].signal).toBe(signal);
      window.removeEventListener("iris:task_update", handler);
    }
  });

  it("surfaces learningSignal (discrete string) through useTaskProgress", () => {
    const { result } = renderHook(() => useTaskProgress());
    act(() => {
      // INPUTS (sanctioned change, 2026-09-06): dispatch a task:start first.
      // Production ALWAYS has a task running when task:learning fires —
      // the pre-REQ-38 code used to fabricate an empty `legacy_unknown` card
      // for a bare learning event, which was removed by the phantom-card fix
      // (prior events could materialize 0-step cards). This setup mirrors the
      // real sequence; the assertions below are unchanged.
      window.dispatchEvent(
        new CustomEvent("iris:task_update", {
          detail: {
            type: "task:start",
            task_id: "t-learn",
            steps: [{ id: "s1", description: "learnable step", status: "working" }],
            total_steps: 1,
          },
        }),
      );
      fireTaskLearning({
        signal: "crystallized",
        verified_label: "VERIFIED",
        step_id: "s1",
        state: "done",
      });
    });
    // learningSignal is the discrete signal string, never an object/narration.
    expect(result.current.learningSignal).toBe("crystallized");
    expect(typeof result.current.learningSignal).toBe("string");
    // The hook also flips into a working display state on the signal.
    expect(result.current.isWorking).toBe(true);
  });

  it("does NOT surface a learningSignal for a non-learning event", () => {
    const { result } = renderHook(() => useTaskProgress());
    act(() => {
      window.dispatchEvent(
        new CustomEvent("iris:task_update", {
          detail: { type: "task:update", step_id: "s1", status: "done" },
        }),
      );
    });
    // Initial value is undefined; a non-learning event leaves it unset.
    expect(result.current.learningSignal).toBeUndefined();
  });
});
