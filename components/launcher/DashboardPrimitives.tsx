"use client"

import React from "react"

export function SectionHeader({ title, subtitle, description, action, children }: { title: string; subtitle?: string; description?: string; action?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        {action}
      </div>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
      {children}
    </div>
  )
}

export function StatusBadge({ status, label, children }: { status?: string; label?: string; children?: React.ReactNode }) {
  const color = status === "success" || status === "online" ? "text-green-400" : status === "error" ? "text-red-400" : "text-yellow-400"
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-white/5 border border-white/10 ${color}`}>
      {label || children}
    </span>
  )
}

export function DataRow({ label, value, children }: { label: string; value?: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/5">
      <span className="text-xs text-muted-foreground">{label}</span>
      {value ? <span className="text-xs text-foreground">{value}</span> : children}
    </div>
  )
}
