"use client"

import React from "react"

export function PageTransition({ children, variant }: { children: React.ReactNode; variant?: string }) {
  return <div className="animate-fadeIn">{children}</div>
}
