/**
 * Wave 0 baseline (T0d) — the `vision_status` WS message shape as consumed
 * by useIRISWebSocket.ts TODAY (specs/vision-browser-stage REQ-5 / T5+T10).
 *
 * Pins: the handler keys off `payload.status`, carries vram_usage_mb /
 * load_progress_percent / error_message / last_used, and derives
 * is_available from status === 'enabled'. T5 adds {state, reason?, trigger?}
 * ADDITIVELY — this test is edited EXACTLY ONCE by T10 to assert the new
 * fields flow through, and that edit must be called out.
 *
 * The handler lives inside the useIRISWebSocket closure, so this test pins
 * the CONTRACT (field names + derivation rules) via a mirror of the merge
 * logic applied to representative payloads. If the real handler diverges
 * from this mirror, the mirror is wrong — fix the mirror, not the contract.
 */

import { describe, expect, it } from "@jest/globals";

type VisionStatusShape = {
  status: string;
  vram_usage_mb: number | null;
  load_progress_percent: number | null;
  error_message: string | null;
  last_used: string | null;
  is_available: boolean;
};

/** Mirror of the vision_status case's merge rules (useIRISWebSocket.ts). */
function applyVisionStatus(
  prev: VisionStatusShape,
  payload: Record<string, unknown>
): VisionStatusShape {
  if (!payload.status) return prev;
  return {
    ...prev,
    status: payload.status as string,
    vram_usage_mb:
      typeof payload.vram_usage_mb === "number" ? payload.vram_usage_mb : null,
    load_progress_percent:
      typeof payload.load_progress_percent === "number"
        ? payload.load_progress_percent
        : null,
    error_message:
      typeof payload.error_message === "string" ? payload.error_message : null,
    last_used: typeof payload.last_used === "string" ? payload.last_used : null,
    is_available: payload.status === "enabled",
  };
}

const INITIAL: VisionStatusShape = {
  status: "disabled",
  vram_usage_mb: null,
  load_progress_percent: null,
  error_message: null,
  last_used: null,
  is_available: false,
};

describe("vision_status message shape (T0d baseline)", () => {
  it("keys off payload.status and ignores status-less payloads", () => {
    const prev = { ...INITIAL };
    expect(applyVisionStatus(prev, {})).toEqual(prev);
    expect(applyVisionStatus(prev, { vram_usage_mb: 123 })).toEqual(prev);
  });

  it("derives is_available ONLY from status === 'enabled'", () => {
    expect(applyVisionStatus(INITIAL, { status: "enabled" }).is_available).toBe(true);
    expect(applyVisionStatus(INITIAL, { status: "loading" }).is_available).toBe(false);
    expect(applyVisionStatus(INITIAL, { status: "error" }).is_available).toBe(false);
  });

  it("carries numeric/string fields with typed fallbacks", () => {
    const out = applyVisionStatus(INITIAL, {
      status: "loading",
      vram_usage_mb: 2480,
      load_progress_percent: 42,
      last_used: "2026-08-23T10:00:00Z",
    });
    expect(out.vram_usage_mb).toBe(2480);
    expect(out.load_progress_percent).toBe(42);
    expect(out.last_used).toBe("2026-08-23T10:00:00Z");
    expect(out.error_message).toBeNull();
  });

  it("error_message survives only as a string", () => {
    const out = applyVisionStatus(INITIAL, {
      status: "error",
      error_message: "no VL model fits free VRAM",
    });
    expect(out.status).toBe("error");
    expect(out.error_message).toBe("no VL model fits free VRAM");
    // A non-string reason must NOT be smuggled in (typed fallback).
    const bad = applyVisionStatus(INITIAL, { status: "error", error_message: 42 });
    expect(bad.error_message).toBeNull();
  });

  it("BASELINE: no lifecycle fields exist yet (added additively by T5/T10)", () => {
    // Documents today's absence so the additive extension is provable.
    const out = applyVisionStatus(INITIAL, { status: "enabled" });
    expect((out as Record<string, unknown>).state).toBeUndefined();
    expect((out as Record<string, unknown>).reason).toBeUndefined();
    expect((out as Record<string, unknown>).trigger).toBeUndefined();
  });
});
