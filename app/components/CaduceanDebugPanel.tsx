"use client";

/**
 * CaduceanDebugPanel — Dev-only floating panel showing live Caducean state.
 *
 * v2: Shows the bias-free DirectionSignal plus the full state snapshot
 * (x, y, xi, u, a, b, s, c_eff). Includes sliders for a, b, s that
 * call caducean_set_params to dynamically tune the Duffing potential.
 *
 * This is a DEV-ONLY panel. In production, hide via the showDebugPanel
 * flag (default: process.env.NODE_ENV !== 'production').
 *
 * Visual: fixed bottom-right, semi-transparent dark background, monospace
 * font, updates at 500ms via useCaducean.
 */

import { useState } from "react";
import {
  useCaducean,
  useCaduceanHealth,
  useCaduceanParams,
  type CaduceanState,
} from "../hooks/useCaducean";

// ── Props ──────────────────────────────────────────────────────────

export interface CaduceanDebugPanelProps {
  sessionId: string | null;
  /** When true, the panel renders. Default: NODE_ENV !== 'production'. */
  showDebugPanel?: boolean;
  /** Initial position. Default: bottom-right. */
  initialPosition?: { x: number; y: number };
}

// ── Sub-components ─────────────────────────────────────────────────

function StateRow({ label, value, unit = "" }: { label: string; value: string | number; unit?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 11 }}>
      <span style={{ color: "#9ca3af" }}>{label}</span>
      <span style={{ color: "#e5e7eb", fontVariantNumeric: "tabular-nums" }}>
        {value}
        {unit}
      </span>
    </div>
  );
}

function Indicator({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 6px",
        background: color,
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 600,
        color: "#000",
      }}
    >
      {label}: {value}
    </div>
  );
}

function ParamSlider({
  label,
  value,
  min,
  max,
  step,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled: boolean;
  onChange: (v: number) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
        <span style={{ color: "#9ca3af" }}>{label}</span>
        <span style={{ color: "#fbbf24", fontVariantNumeric: "tabular-nums" }}>
          {value.toFixed(3)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: "100%" }}
      />
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────

export function CaduceanDebugPanel({
  sessionId,
  showDebugPanel,
  initialPosition,
}: CaduceanDebugPanelProps) {
  const visible =
    showDebugPanel ?? (typeof process !== "undefined" && process.env.NODE_ENV !== "production");
  if (!visible) return null;

  const { state, error, isLoading, direction } = useCaducean(sessionId, { pollMs: 500 });
  const { health } = useCaduceanHealth();
  const { setParams, isPending: isParamsPending, error: paramsError } = useCaduceanParams();
  const [collapsed, setCollapsed] = useState(false);

  // Position is fixed bottom-right by default.
  const baseStyle: React.CSSProperties = {
    position: "fixed",
    bottom: 16,
    right: 16,
    width: 320,
    maxHeight: collapsed ? 36 : 480,
    background: "rgba(15, 15, 20, 0.92)",
    color: "#e5e7eb",
    border: "1px solid #374151",
    borderRadius: 8,
    padding: collapsed ? 0 : 12,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: 11,
    backdropFilter: "blur(8px)",
    boxShadow: "0 8px 32px rgba(0, 0, 0, 0.4)",
    zIndex: 9999,
    overflow: "hidden",
    transition: "max-height 0.2s ease",
    ...(initialPosition
      ? {
          left: initialPosition.x,
          top: initialPosition.y,
          bottom: "auto",
          right: "auto",
        }
      : {}),
  };

  const engineLive = health?.engine_live ?? state?.engine_live ?? false;
  const engineColor = engineLive ? "#22c55e" : "#ef4444";
  // Map target_u (±1) to a display label. TOPO_VIOLATION is a separate
  // signal from `recommend()` (code 3), not from target_u. We don't show
  // it on the directional indicator here; if needed, expose it via
  // a dedicated hook call (deferred to v3 for cleaner separation).
  const recCode: 0 | 1 | 2 =
    direction?.target_u === 1 ? 0 : direction?.target_u === -1 ? 1 : 2;
  const recColor =
    recCode === 0 ? "#22c55e" : recCode === 1 ? "#3b82f6" : "#9ca3af";
  const recLabel = ["EXPAND", "COMPRESS", "MAINTAIN"][recCode] ?? "UNKNOWN";

  return (
    <div data-testid="caducean-debug-panel" style={baseStyle}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          cursor: "pointer",
          padding: collapsed ? "8px 12px" : "0 0 8px 0",
        }}
        onClick={() => setCollapsed(!collapsed)}
      >
        <span style={{ fontSize: 12, fontWeight: 700, color: "#fbbf24" }}>
          🔬 Caducean v2 {collapsed ? "" : state?.session_id ? `(${state.session_id.slice(0, 12)}...)` : ""}
        </span>
        <span style={{ fontSize: 10, color: "#9ca3af" }}>
          {collapsed ? "▴" : "▾"}
        </span>
      </div>

      {collapsed ? null : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {/* Status indicators */}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <Indicator
              label="ENGINE"
              value={engineLive ? "LIVE" : "OFFLINE"}
              color={engineColor}
            />
            <Indicator
              label="REC"
              value={recLabel}
              color={recColor}
            />
            {isLoading && <Indicator label="SYNC" value="…" color="#fbbf24" />}
          </div>

          {error && (
            <div
              style={{
                background: "rgba(239, 68, 68, 0.2)",
                border: "1px solid #ef4444",
                borderRadius: 4,
                padding: 6,
                fontSize: 10,
                color: "#fca5a5",
              }}
            >
              {error}
            </div>
          )}

          {/* State */}
          {state && <StateView state={state} direction={direction ?? null} />}

          {/* Param sliders */}
          {state && sessionId && (
            <div style={{ borderTop: "1px solid #374151", paddingTop: 8 }}>
              <div style={{ fontSize: 10, color: "#9ca3af", marginBottom: 4 }}>
                Duffing parameters (clamped in C++)
              </div>
              <ParamSlider
                label="a (potential steepness)"
                value={state.a}
                min={1.0}
                max={4.0}
                step={0.05}
                disabled={isParamsPending || !engineLive}
                onChange={(v) => setParams({ sessionId, a: v, b: state.b, s: state.s })}
              />
              <ParamSlider
                label="b (wall depth)"
                value={state.b}
                min={1.0}
                max={4.0}
                step={0.05}
                disabled={isParamsPending || !engineLive}
                onChange={(v) => setParams({ sessionId, a: state.a, b: v, s: state.s })}
              />
              <ParamSlider
                label="s (walk speed)"
                value={state.s}
                min={0.1}
                max={0.8}
                step={0.01}
                disabled={isParamsPending || !engineLive}
                onChange={(v) => setParams({ sessionId, a: state.a, b: state.b, s: v })}
              />
              {paramsError && (
                <div style={{ fontSize: 10, color: "#fca5a5", marginTop: 4 }}>
                  {paramsError}
                </div>
              )}
            </div>
          )}

          {!state && !error && (
            <div style={{ color: "#9ca3af", fontSize: 11, textAlign: "center", padding: 12 }}>
              Waiting for state…
            </div>
          )}

          {!sessionId && (
            <div style={{ color: "#9ca3af", fontSize: 11, textAlign: "center", padding: 12 }}>
              No session_id provided
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StateView({
  state,
  direction,
}: {
  state: CaduceanState;
  direction: { target_u: number; force_magnitude: number; u_current: number; phase: number; balance: number } | null;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <StateRow label="x (EXPAND count)" value={state.x} />
      <StateRow label="y (COMPRESS count)" value={state.y} />
      <StateRow label="xi (phase)" value={state.xi.toFixed(4)} unit=" rad" />
      <StateRow label="u (velocity)" value={state.u.toFixed(4)} />
      <StateRow label="c_eff" value={state.c_eff.toFixed(4)} />
      <StateRow label="a, b, s" value={`${state.a.toFixed(2)} / ${state.b.toFixed(2)} / ${state.s.toFixed(2)}`} />
      {direction && (
        <>
          <div style={{ borderTop: "1px solid #374151", marginTop: 4, paddingTop: 4 }}>
            <div style={{ fontSize: 10, color: "#fbbf24", marginBottom: 2 }}>DirectionSignal</div>
          </div>
          <StateRow label="target_u" value={direction.target_u} />
          <StateRow label="force_magnitude" value={direction.force_magnitude.toFixed(4)} />
          <StateRow label="balance" value={direction.balance.toFixed(4)} />
        </>
      )}
    </div>
  );
}
