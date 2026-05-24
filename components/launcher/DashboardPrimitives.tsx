"use client"

import React from "react"

export function SectionHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      {children}
    </div>
  )
}

export function StatusBadge({ status, children }: { status?: string; children?: React.ReactNode }) {
  const color = status === "success" ? "text-green-400" : status === "error" ? "text-red-400" : "text-yellow-400"
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-white/5 border border-white/10 ${color}`}>
      {children}
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
