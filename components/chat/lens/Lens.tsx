"use client"

/**
 * The lens: an overlay INSIDE the wing, over the timeline. It holds one artifact or
 * one edit review. Header: back, title, Pop out (artifacts), To dashboard.
 * Look: iris-strands.html (`.lens`, `openLens`, `openDiff`).
 */
import React from "react"

const HAIR = "rgba(160,190,255,.09)"

export function LensButton({ children, onClick, label }: { children: React.ReactNode; onClick: () => void; label?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="rounded-md px-2 py-1.5 text-[11.5px] leading-none whitespace-nowrap"
      style={{ background: "#0e1122", border: `1px solid ${HAIR}`, color: "#e6e9f2", cursor: "pointer" }}
    >
      {children}
    </button>
  )
}

export interface LensProps {
  title: string
  onClose: () => void
  /** Present for an artifact: opens it the way it opens outside the wing. */
  onPopOut?: () => void
  onToDashboard: () => void
  /** Short status ("Opened in the dashboard workspace."). */
  status?: string | null
  children: React.ReactNode
}

export function Lens({ title, onClose, onPopOut, onToDashboard, status, children }: LensProps) {
  return (
    <div
      className="iris-lens absolute flex flex-col"
      style={{ inset: 0, zIndex: 15, background: "#04050c" }}
      role="dialog"
      aria-label={title}
      data-lens
    >
      <div className="flex min-w-0 flex-none flex-wrap items-center gap-1.5 px-2.5 py-2" style={{ borderBottom: `1px solid ${HAIR}` }}>
        <LensButton onClick={onClose} label="Back to the chat">◂ back</LensButton>
        <b className="min-w-0 flex-1 truncate text-[13px]" style={{ minWidth: 120, color: "#e6e9f2" }} title={title}>{title}</b>
        {status && (
          <span role="status" className="text-[11px]" style={{ color: "#5fcf98" }}>{status}</span>
        )}
        {onPopOut && <LensButton onClick={onPopOut} label="Pop out">Pop out</LensButton>}
        <LensButton onClick={onToDashboard} label="To dashboard">To dashboard</LensButton>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3.5" data-lens-body>
        {children}
      </div>
    </div>
  )
}

export default Lens
