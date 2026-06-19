"use client"

import React from "react"
import type { ElementType } from "react"

// ── Hex node (40px) — glassmorphic hex ───────────────────────────────
// Extracted from components/preview/MenuMockups.tsx (lines 22–135).
// The exact hex clip path, hover glow, liquid metal border, glassmorphic
// base, hex-grid pattern overlay, and icon rendering are preserved.

const HEX_CLIP = 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)'

export interface HexNodeProps {
  glowColor: string
  icon: ElementType
  isActive: boolean
  onHover: (hovered: boolean) => void
  onClick?: () => void
  size?: number
}

/**
 * HexNode — a glassmorphic hexagonal button with liquid metal border,
 * outer glow, and hex-grid pattern overlay.
 *
 * Used by RadialArcNodes for the 6 category nodes in the level 2 menu.
 */
export function HexNode({
  glowColor,
  icon: Icon,
  isActive,
  onHover,
  onClick,
  size = 40,
}: HexNodeProps) {
  return (
    <button
      className="relative flex items-center justify-center cursor-pointer"
      style={{
        width: size,
        height: size,
        clipPath: HEX_CLIP,
        border: 'none',
        background: 'none',
        padding: 0,
        opacity: isActive ? 1 : 0.8,
        transform: isActive ? 'scale(1.08)' : 'scale(1)',
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        flexShrink: 0,
      }}
      onClick={onClick}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      {/* Outer glow */}
      <div
        className="absolute pointer-events-none"
        style={{
          inset: -6,
          clipPath: HEX_CLIP,
          background: `radial-gradient(circle, ${glowColor}${Math.round(0.35 * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
          filter: 'blur(6px)',
          opacity: isActive ? 1 : 0.4,
          transition: 'opacity 0.3s ease',
        }}
      />
      {/* Liquid metal border */}
      <div
        className="absolute pointer-events-none"
        style={{
          inset: 0,
          clipPath: HEX_CLIP,
          background: `conic-gradient(from 0deg,
            #ffffff 0deg,
            ${glowColor} 45deg,
            #101014 120deg,
            #ffffff 180deg,
            ${glowColor} 225deg,
            #101014 300deg,
            #ffffff 360deg) border-box`,
          WebkitMask: 'linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0)',
          WebkitMaskComposite: 'destination-out',
          maskComposite: 'exclude',
          filter: 'drop-shadow(0 0 1px rgba(255,255,255,0.3))',
          zIndex: 2,
        }}
      />
      {/* Glassmorphic base */}
      <div
        className="absolute inset-0 flex items-center justify-center overflow-hidden"
        style={{
          clipPath: HEX_CLIP,
          background: isActive
            ? `linear-gradient(135deg, color-mix(in srgb, ${glowColor}, #0a0a0c 80%) 0%, #0a0a0c 100%)`
            : `linear-gradient(135deg, #0a0a0c 0%, color-mix(in srgb, ${glowColor}, #0a0a0c 90%) 100%)`,
          boxShadow: '0 2px 8px rgba(0,0,0,0.5), inset 0 1px 2px rgba(255,255,255,0.2)',
          zIndex: 3,
        }}
      >
        {/* Hex-grid pattern overlay */}
        <div
          className="absolute inset-0 pointer-events-none opacity-[0.04]"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='49' viewBox='0 0 28 49'%3E%3Cg fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.4'%3E%3Cpath d='M13.99 9.25l13 7.5v15l-13 7.5L1 31.75v-15l12.99-7.5zM3 17.9v12.7l10.99 6.34 11-6.35V17.9l-11-6.34L3 17.9zM0 15l12.98-7.5V0h-2v6.35L0 12.69v2.3zm0 18.5L12.98 41v8h-2v-6.85L0 35.81v-2.3zM15 0v7.5L27.99 15H28v-2.31h-.01L17 6.35V0h-2zm0 49v-8l12.99-7.5H28v2.31h-.01L17 42.15V49h-2z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
            backgroundSize: `${size * 0.35}px ${size * 0.6}px`,
          }}
        />
        {/* Active state fill */}
        {isActive && (
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              clipPath: HEX_CLIP,
              background: `radial-gradient(circle, ${glowColor}35 0%, transparent 70%)`,
              zIndex: 3,
            }}
          />
        )}
        {/* Icon */}
        <div className="relative z-10 flex items-center justify-center pointer-events-none">
          <Icon
            style={{
              width: size * 0.4,
              height: size * 0.4,
              color: isActive ? '#ffffff' : '#94a3b8',
              filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.5))',
            }}
            strokeWidth={1.5}
          />
        </div>
      </div>
    </button>
  )
}
