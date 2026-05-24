"use client"

import * as React from "react"

interface SidebarProps {
  children?: React.ReactNode
  className?: string
}

export function Sidebar({ children, className }: SidebarProps) {
  return (
    <aside className={`w-64 h-screen border-r border-white/5 bg-black/20 ${className || ""}`}>
      {children}
    </aside>
  )
}

export function SidebarHeader({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`px-4 py-3 border-b border-white/5 ${className || ""}`}>{children}</div>
}

export function SidebarContent({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`p-4 ${className || ""}`}>{children}</div>
}

// Stubs for launcher layout compatibility
export function SidebarProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

export function SidebarTrigger({ className }: { className?: string }) {
  return <button className={className}>☰</button>
}

export function SidebarInset({ children, id, className }: { children?: React.ReactNode; id?: string; className?: string }) {
  return <main id={id} className={className}>{children}</main>
}
