"use client"

import React, { createContext, useContext } from "react"

const AppContext = createContext({})

export function AppProvider({ children }: { children: React.ReactNode }) {
  return <AppContext.Provider value={{}}>{children}</AppContext.Provider>
}

export function useAppContext() {
  return useContext(AppContext)
}

export function useApp() {
  return useContext(AppContext)
}
