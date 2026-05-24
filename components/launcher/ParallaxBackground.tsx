"use client"

import React from "react"

export function ParallaxBackground({ children }: { children?: React.ReactNode }) {
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950" />
      <div className="absolute top-0 left-0 w-full h-full opacity-20"
        style={{
          backgroundImage: `radial-gradient(circle at 20% 30%, rgba(59,130,246,0.15) 0%, transparent 50%),
                           radial-gradient(circle at 80% 70%, rgba(139,92,246,0.1) 0%, transparent 50%)`,
        }}
      />
      {children}
    </div>
  )
}
