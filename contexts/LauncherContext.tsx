"use client"

import React, { createContext, useContext, useState } from "react"

interface AppState {
  isReady: boolean
  activeTab: string
}

const LauncherContext = createContext<{
  app: AppState
  setApp: React.Dispatch<React.SetStateAction<AppState>>
}>({
  app: { isReady: true, activeTab: "dashboard" },
  setApp: () => {},
})

export function LauncherProvider({ children }: { children: React.ReactNode }) {
  const [app, setApp] = useState<AppState>({ isReady: true, activeTab: "dashboard" })
  return <LauncherContext.Provider value={{ app, setApp }}>{children}</LauncherContext.Provider>
}

export function useApp() {
  return useContext(LauncherContext)
}
