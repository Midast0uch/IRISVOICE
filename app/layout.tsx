import React from "react"
import type { Metadata, Viewport } from 'next'
import Script from "next/script"

// NOTE: CSS is served as a static file from public/globals.css (via <link> in head)
// to avoid Turbopack's PostCSS pipeline timeout. The source is css-src/globals.css
// and must be re-compiled with `npx @tailwindcss/cli -i css-src/globals.css -o public/globals.css`.

import { NavigationProvider } from "@/contexts/NavigationContext"
import { BrandColorProvider } from "@/contexts/BrandColorContext"
import { TransitionProvider } from "@/contexts/TransitionContext"
import { IntegrationsProvider } from "@/contexts/IntegrationsContext"
import { TerminalProvider } from "@/contexts/TerminalContext"

export const metadata: Metadata = {
  title: 'Control Center | TTS Chatbot',
  description: 'Hexagonal hub-and-spoke glassmorphic control center for TTS chatbot settings',
  generator: 'v0.app',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  themeColor: '#0a0a0f',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          Inline script runs synchronously before first paint.
          Detects Tauri by checking window.__TAURI_INTERNALS__ (set by Tauri's
          init script before page JS loads). Non-Tauri (browser) gets the
          'in-browser' class which triggers a dark background via CSS so the
          page isn't blank white. Tauri keeps transparent background so the
          desktop shows through the glass UI.
        */}
        <Script
          id="tauri-detection"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{
            __html: `(function(){try{if(!window.__TAURI_INTERNALS__)document.documentElement.classList.add('in-browser');}catch(e){document.documentElement.classList.add('in-browser');}})();`
          }}
        />
        {/* Space Grotesk (UI) + JetBrains Mono (data) — geometric, futuristic, dark-mode optimized */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
        {/* Pre-compiled Tailwind CSS — see note at top of file */}
        <link rel="stylesheet" href="/globals.css" />
        {/* Pre-compiled Tailwind CSS — see note at top of file */}</head>
      <body className={`font-sans antialiased text-foreground`}>
        <BrandColorProvider>
          <TransitionProvider>
            <NavigationProvider>
              <TerminalProvider>
                <IntegrationsProvider>
                  {children}
                </IntegrationsProvider>
              </TerminalProvider>
              {/* Transition testing components removed - they were interfering with widget drag */}
              {/* <TransitionIndicator /> */}
              {/* <TransitionSwitch /> */}
            </NavigationProvider>
        </TransitionProvider>
      </BrandColorProvider>
      </body>
    </html>
  )
}

