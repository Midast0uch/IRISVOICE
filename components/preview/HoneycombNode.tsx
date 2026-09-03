'use client'

import React from 'react'
import type { ElementType } from 'react'

interface HoneycombNodeProps {
  glowColor: string
  label: string
  icon: ElementType
  isActive?: boolean
  onClick?: () => void
}

const HEX_CLIP = 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)'

export function HoneycombNode({ glowColor, label, icon: Icon, isActive = false, onClick }: HoneycombNodeProps) {
  return (
    <button
      className="relative flex items-center justify-center cursor-pointer"
      style={{
        width: 90,
        height: 90,
        clipPath: HEX_CLIP,
        border: 'none',
        background: 'none',
        padding: 0,
        opacity: isActive ? 1 : 0.85,
        transform: isActive ? 'scale(1.05)' : 'scale(1)',
        transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        const el = e.currentTarget
        el.style.transform = isActive ? 'scale(1.05) rotate(5deg) translateY(-4px)' : 'rotate(5deg) translateY(-4px)'
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget
        el.style.transform = isActive ? 'scale(1.05)' : 'scale(1)'
      }}
    >
      {/* 1. Outer glow */}
      <div
        className="absolute pointer-events-none"
        style={{
          inset: -12,
          clipPath: HEX_CLIP,
          background: `radial-gradient(circle, ${glowColor}${Math.round(0.4 * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
          filter: 'blur(12px)',
          opacity: isActive ? 1 : 0.5,
          transition: 'opacity 0.3s ease',
        }}
      />

      {/* 2. Liquid metal border */}
      <div
        className="absolute pointer-events-none"
        style={{
          inset: 0,
          clipPath: HEX_CLIP,
          border: '2px solid transparent',
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
          filter: 'drop-shadow(0 0 2px rgba(255,255,255,0.4))',
          zIndex: 2,
        }}
      />

      {/* 3. Glassmorphic base */}
      <div
        className="absolute inset-0 flex items-center justify-center overflow-hidden"
        style={{
          clipPath: HEX_CLIP,
          background: `linear-gradient(135deg, #0a0a0c 0%, color-mix(in srgb, ${glowColor}, #0a0a0c 85%) 100%)`,
          boxShadow: '0 4px 12px rgba(0,0,0,0.5), inset 0 1.5px 3px rgba(255,255,255,0.25)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          zIndex: 3,
        }}
      >
        {/* Hex-grid pattern overlay */}
        <div
          className="absolute inset-0 pointer-events-none opacity-[0.04]"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='49' viewBox='0 0 28 49'%3E%3Cg fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.4'%3E%3Cpath d='M13.99 9.25l13 7.5v15l-13 7.5L1 31.75v-15l12.99-7.5zM3 17.9v12.7l10.99 6.34 11-6.35V17.9l-11-6.34L3 17.9zM0 15l12.98-7.5V0h-2v6.35L0 12.69v2.3zm0 18.5L12.98 41v8h-2v-6.85L0 35.81v-2.3zM15 0v7.5L27.99 15H28v-2.31h-.01L17 6.35V0h-2zm0 49v-8l12.99-7.5H28v2.31h-.01L17 42.15V49h-2z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
            backgroundSize: '14px 24px',
          }}
        />

        {/* Gradient overlay for depth */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `linear-gradient(135deg, ${glowColor}20 0%, transparent 50%, ${glowColor}10 100%)`,
          }}
        />

        {/* 4. Internal hex bevel */}
        <div
          className="absolute pointer-events-none"
          style={{
            inset: 8,
            clipPath: HEX_CLIP,
            background: `linear-gradient(135deg, rgba(0,0,0,0.3) 0%, transparent 50%, rgba(255,255,255,0.05) 100%)`,
            borderTop: '1px solid rgba(255,255,255,0.2)',
            zIndex: 4,
          }}
        />

        {/* 5. Active state fill */}
        {isActive && (
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              clipPath: HEX_CLIP,
              background: `radial-gradient(circle, ${glowColor}40 0%, transparent 70%)`,
              animation: 'hexFill 0.4s ease-out',
              zIndex: 3,
            }}
          />
        )}

        {/* 6. Content: Icon + Label */}
        <div className="relative z-10 flex flex-col items-center justify-center gap-1.5 pointer-events-none">
          <Icon
            className="w-5 h-5"
            style={{
              color: '#ffffff',
              filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.7))',
            }}
            strokeWidth={1.5}
          />
          <span
            className="font-semibold uppercase text-center px-1"
            style={{
              fontSize: '8.5px',
              color: '#ffffff',
              textShadow: '0 1px 2px rgba(0,0,0,0.7), 0 0 2px rgba(0,0,0,0.5)',
              letterSpacing: '0.1em',
            }}
          >
            {label}
          </span>
        </div>
      </div>

      <style>{`
        @keyframes hexFill {
          from { opacity: 0; transform: scale(0.3); }
          to { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </button>
  )
}
