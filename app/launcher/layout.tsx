"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppProvider } from "@/contexts/LauncherContext";
import { AppSidebar } from "@/components/launcher/AppSidebar";
import { SidebarProvider, SidebarTrigger, SidebarInset } from "@/components/ui/sidebar";
// Theme toggle is in the launcher header for switching dark/light mode
import { ParallaxBackground } from "@/components/launcher/ParallaxBackground";
import { Toaster } from "@/components/ui/toaster";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { ThemeToggle } from "@/components/launcher/ThemeToggle";

const queryClient = new QueryClient();

/* ── Skip Link for keyboard users ── */
function SkipLink() {
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-white focus:text-black focus:rounded-md focus:font-medium focus:text-sm"
    >
      Skip to main content
    </a>
  );
}

/* ── HUD Background + Effects ── */
function LauncherHUDBackground() {
  return (
    <>
      {/* Base gradient — dark HUD in dark mode, clean light in light mode */}
      <div
        className="fixed inset-0 -z-20 dark:hidden"
        style={{
          background: 'linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)',
        }}
      />
      <div
        className="fixed inset-0 -z-20 hidden dark:block"
        style={{
          background: 'linear-gradient(135deg, rgba(8,8,16,0.98) 0%, rgba(4,4,8,0.99) 100%)',
        }}
      />
      {/* Scanline / HUD overlay — dark only */}
      <div
        className="fixed inset-0 pointer-events-none -z-10 hidden dark:block"
        style={{
          background: `
            linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.015) 50%, transparent 100%),
            repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.04) 2px, rgba(0,0,0,0.04) 4px)
          `,
          backgroundSize: '100% 100%, 100% 4px',
        }}
      />
      {/* Vignette — dark only */}
      <div
        className="fixed inset-0 pointer-events-none -z-10 hidden dark:block"
        style={{
          boxShadow: 'inset 0 0 120px rgba(0,0,0,0.6)',
        }}
      />
    </>
  );
}

export default function LauncherLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const router = useRouter();
  const pathname = usePathname();

  // ── Auto-navigate to DiffReviewPage on session_end ──
  useEffect(() => {
    const handleSessionEnd = () => {
      // Avoid redirect loops — don't navigate if already on diff-review
      if (pathname === '/launcher/diff-review') return;

      // Persist the session_end flag so other tabs/windows see it too
      try {
        localStorage.setItem('iris:session_ended', JSON.stringify({
          timestamp: Date.now(),
          pending_writes: 0, // will be filled by API
          branch: '',
        }));
      } catch { /* ignore */ }

      router.push('/launcher/diff-review');
    };

    // Listen for CustomEvent from useIRISWebSocket (same window)
    window.addEventListener('iris:session_end', handleSessionEnd);

    // Also check localStorage on mount (cross-window, e.g. Tauri launcher)
    try {
      const raw = localStorage.getItem('iris:session_ended');
      if (raw) {
        const data = JSON.parse(raw);
        // Only react if the event was within the last 60 seconds
        if (Date.now() - data.timestamp < 60_000) {
          // Clear so we don't re-trigger on next mount
          localStorage.removeItem('iris:session_ended');
          if (pathname !== '/launcher/diff-review') {
            router.push('/launcher/diff-review');
          }
        }
      }
    } catch { /* ignore */ }

    // Listen for cross-window storage changes
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'iris:session_ended' && e.newValue) {
        try {
          const data = JSON.parse(e.newValue);
          if (Date.now() - data.timestamp < 60_000) {
            localStorage.removeItem('iris:session_ended');
            if (pathname !== '/launcher/diff-review') {
              router.push('/launcher/diff-review');
            }
          }
        } catch { /* ignore */ }
      }
    };
    window.addEventListener('storage', handleStorage);

    return () => {
      window.removeEventListener('iris:session_end', handleSessionEnd);
      window.removeEventListener('storage', handleStorage);
    };
  }, [router, pathname]);

  return (
    <QueryClientProvider client={queryClient}>
      <AppProvider>
        <ThemeProvider>
          <Toaster />
          <SidebarProvider>
            <SkipLink />
            <LauncherHUDBackground />
            <ParallaxBackground />
            <div className="min-h-screen flex w-full relative">
              <AppSidebar />
              <SidebarInset id="main-content" className="relative z-10 focus:outline-none">
                <header
                  className="h-12 flex items-center justify-between px-4 relative z-30 bg-gradient-to-b from-background to-muted border-b border-border"
                >
                  <div className="flex items-center">
                    <SidebarTrigger aria-label="Toggle sidebar" className="text-muted-foreground hover:text-foreground transition-colors" />
                    <span className="ml-3 text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-medium">
                      IRIS Launcher
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <ThemeToggle />
                  </div>
                </header>
                <div className="flex-1 px-8 pt-8 pb-12 overflow-auto">
                  <div className="w-full">
                    {children}
                  </div>
                </div>
              </SidebarInset>
            </div>
          </SidebarProvider>
        </ThemeProvider>
      </AppProvider>
    </QueryClientProvider>
  );
}
