"use client"

import React from "react"

interface LiquidIconProps {
  color?: string
  size?: "sm" | "md" | "lg"
  bounce?: boolean
  className?: string
  children?: React.ReactNode
}

export function LiquidIcon({ color = "primary", size = "md", bounce = true, className = "", children }: LiquidIconProps) {
  const sizeClasses = size === "sm" ? "w-8 h-8" : size === "lg" ? "w-12 h-12" : "w-10 h-10"
  const colorClass = color === "success" ? "bg-green-500/20 text-green-400" :
                     color === "warning" ? "bg-yellow-500/20 text-yellow-400" :
                     color === "error" ? "bg-red-500/20 text-red-400" :
                     color === "neutral" ? "bg-white/10 text-white/40" :
                     "bg-blue-500/20 text-blue-400"

  return (
    <div className={`${sizeClasses} ${colorClass} rounded-xl flex items-center justify-center ${bounce ? "animate-bounce" : ""} ${className}`}>
      {children}
    </div>
  )
}
