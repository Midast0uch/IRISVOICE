import React from "react"
import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'
import { NavigationProvider } from "@/contexts/NavigationContext"
import { BrandColorProvider } from "@/contexts/BrandColorContext"
import { TransitionProvider } from "@/contexts/TransitionContext"
import { TransitionIndicator } from "@/components/ui/transition-indicator"
import { TransitionSwitch } from "@/components/ui/transition-switch"
import { ThemeTestSwitcher } from "@/components/testing/ThemeTestSwitcher"

const _geist = Geist({ subsets: ["latin"] });
const _geistMono = Geist_Mono({ subsets: ["latin"] });

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
    <html lang="en" className="bg-transparent">
      <body className="font-sans antialiased bg-transparent text-foreground">
        <BrandColorProvider>
          <TransitionProvider>
            <NavigationProvider>
              {children}
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
