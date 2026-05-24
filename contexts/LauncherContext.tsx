"use client"

import React, { createContext, useContext, useState } from "react"

interface AppState {
  isReady: boolean
  activeTab: string
  mode?: string
}

interface AppContextValue {
  app: AppState
  setApp: React.Dispatch<React.SetStateAction<AppState>>
  mode: string
}

const LauncherContext = createContext<AppContextValue>({
  app: { isReady: true, activeTab: "dashboard", mode: "personal" },
  setApp: () => {},
  mode: "personal",
})

export function LauncherProvider({ children }: { children: React.ReactNode }) {
  const [app, setApp] = useState<AppState>({ isReady: true, activeTab: "dashboard", mode: "personal" })
  const value = React.useMemo<AppContextValue>(() => ({
    app,
    setApp,
    mode: app.mode || "personal",
  }), [app, setApp])
  return <LauncherContext.Provider value={value}>{children}</LauncherContext.Provider>
}

// Alias for launcher layout.tsx compatibility
export { LauncherProvider as AppProvider }

export function useApp() {
  return useContext(LauncherContext)
}
