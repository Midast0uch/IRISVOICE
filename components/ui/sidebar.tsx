"use client"

import * as React from "react"

const SidebarContext = React.createContext<{ state: string; toggle: () => void }>({
  state: "expanded",
  toggle: () => {},
})

export function useSidebar() {
  return React.useContext(SidebarContext)
}

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState("expanded")
  const toggle = React.useCallback(() => setState(s => s === "expanded" ? "collapsed" : "expanded"), [])
  return (
    <SidebarContext.Provider value={{ state, toggle }}>
      {children}
    </SidebarContext.Provider>
  )
}

interface SidebarProps {
  children?: React.ReactNode
  className?: string
  collapsible?: string
  "aria-label"?: string
}

export function Sidebar({ children, className }: SidebarProps) {
  return (
    <aside className={`w-64 h-screen border-r border-white/5 bg-black/20 flex flex-col ${className || ""}`}>
      {children}
    </aside>
  )
}

export function SidebarHeader({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`px-4 py-3 border-b border-white/5 ${className || ""}`}>{children}</div>
}

export function SidebarContent({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`flex flex-col flex-1 overflow-auto ${className || ""}`}>{children}</div>
}

export function SidebarFooter({ children, className, style }: { children?: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return <div className={`px-4 py-3 border-t border-white/5 ${className || ""}`} style={style}>{children}</div>
}

export function SidebarGroup({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`${className || ""}`}>{children}</div>
}

export function SidebarGroupContent({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`${className || ""}`}>{children}</div>
}

export function SidebarGroupLabel({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`text-xs uppercase tracking-wider text-white/40 ${className || ""}`}>{children}</div>
}

export function SidebarMenu({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`flex flex-col gap-1 ${className || ""}`}>{children}</div>
}

export function SidebarMenuItem({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <div className={`${className || ""}`}>{children}</div>
}

export function SidebarMenuButton({ children, className, asChild }: { children?: React.ReactNode; className?: string; asChild?: boolean }) {
  if (asChild && React.Children.count(children) === 1) {
    return React.cloneElement(React.Children.only(children) as any, { className: `${className || ""}` } as any)
  }
  return <button className={`w-full text-left px-3 py-2 rounded-lg hover:bg-white/5 transition-colors ${className || ""}`}>{children}</button>
}

export function SidebarTrigger({ className }: { className?: string }) {
  const { toggle } = useSidebar()
  return <button onClick={toggle} className={className}>☰</button>
}

export function SidebarInset({ children, id, className }: { children?: React.ReactNode; id?: string; className?: string }) {
  return <main id={id} className={className}>{children}</main>
}
