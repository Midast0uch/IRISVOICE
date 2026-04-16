import React from "react"
import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'

const geist = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
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
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{if(!window.__TAURI_INTERNALS__)document.documentElement.classList.add('in-browser');}catch(e){document.documentElement.classList.add('in-browser');}})();`
          }}
        />
      </head>
      <body className={`${geist.variable} ${geistMono.variable} font-sans antialiased text-foreground`}>
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
