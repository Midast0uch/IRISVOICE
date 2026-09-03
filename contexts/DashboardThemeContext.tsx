'use client';

import { createContext, useContext, ReactNode } from 'react';

export type DashboardTheme = 'aether' | 'ember' | 'aurum' | 'verdant' | 'nebula' | 'crimson';

export interface ThemeConfig {
  primary: string;
  glow: string;
  accent: string;
  ambient: string;
}

export const dashboardThemes: Record<DashboardTheme, ThemeConfig> = {
  aether: {
    primary: 'cyan-400',
    glow: 'cyan-400/30',
    accent: 'bg-cyan-400/20 text-cyan-300',
    ambient: 'bg-cyan-500/20',
  },
  ember: {
    primary: 'orange-500',
    glow: 'orange-500/30',
    accent: 'bg-orange-500/20 text-orange-300',
    ambient: 'bg-orange-500/20',
  },
  aurum: {
    primary: 'amber-400',
    glow: 'amber-400/30',
    accent: 'bg-amber-400/20 text-amber-300',
    ambient: 'bg-amber-500/20',
  },
  verdant: {
    primary: 'emerald-400',
    glow: 'emerald-400/30',
    accent: 'bg-emerald-400/20 text-emerald-300',
    ambient: 'bg-emerald-500/20',
  },
  nebula: {
    primary: 'violet-500',
    glow: 'violet-500/30',
    accent: 'bg-violet-500/20 text-violet-300',
    ambient: 'bg-violet-600/20',
  },
  crimson: {
    primary: 'rose-500',
    glow: 'rose-500/30',
    accent: 'bg-rose-500/20 text-rose-300',
    ambient: 'bg-rose-600/20',
  },
};

const DashboardThemeContext = createContext<DashboardTheme>('nebula');

export function useDashboardTheme() {
  return useContext(DashboardThemeContext);
}

interface DashboardThemeProviderProps {
  children: ReactNode;
  theme?: DashboardTheme;
}

export function DashboardThemeProvider({ children, theme = 'nebula' }: DashboardThemeProviderProps) {
  return (
    <DashboardThemeContext.Provider value={theme}>
      {children}
    </DashboardThemeContext.Provider>
  );
}
