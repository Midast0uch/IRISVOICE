"use client"

import React from "react"
import { Moon, Sun } from "lucide-react"

export function ThemeToggle() {
  const [dark, setDark] = React.useState(true)
  return (
    <button
      onClick={() => setDark(!dark)}
      className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
      title="Toggle theme"
    >
      {dark ? <Moon size={16} className="text-white/70" /> : <Sun size={16} className="text-white/70" />}
    </button>
  )
}
