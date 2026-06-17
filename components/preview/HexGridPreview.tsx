'use client'

import React, { useState } from 'react'
import { Mic, Settings, Zap, Shield, Palette, BarChart3 } from 'lucide-react'
import { HoneycombNode } from './HoneycombNode'

const NODES = [
  { id: 'voice', label: 'Voice', icon: Mic, angle: -90 },
  { id: 'agent', label: 'Agent', icon: Settings, angle: -30 },
  { id: 'automate', label: 'Automate', icon: Zap, angle: 30 },
  { id: 'system', label: 'System', icon: Shield, angle: 90 },
  { id: 'customize', label: 'Customize', icon: Palette, angle: 150 },
  { id: 'monitor', label: 'Monitor', icon: BarChart3, angle: 210 },
]

const RADIUS = 160

interface HexGridPreviewProps {
  glowColor: string
}

export function HexGridPreview({ glowColor }: HexGridPreviewProps) {
  const [activeId, setActiveId] = useState<string | null>(null)

  return (
    <div className="relative" style={{ width: RADIUS * 2 + 180, height: RADIUS * 2 + 180 }}>
      {NODES.map((node) => {
        const angleRad = (node.angle * Math.PI) / 180
        const x = Math.cos(angleRad) * RADIUS
        const y = Math.sin(angleRad) * RADIUS
        const isActive = activeId === node.id

        return (
          <div
            key={node.id}
            className="absolute"
            style={{
              left: '50%',
              top: '50%',
              transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`,
            }}
          >
            <HoneycombNode
              glowColor={glowColor}
              label={node.label}
              icon={node.icon}
              isActive={isActive}
              onClick={() => setActiveId(isActive ? null : node.id)}
            />
          </div>
        )
      })}

      {/* Center point indicator (subtle) */}
      <div
        className="absolute rounded-full pointer-events-none"
        style={{
          left: '50%',
          top: '50%',
          width: 4,
          height: 4,
          transform: 'translate(-50%, -50%)',
          background: `${glowColor}40`,
        }}
      />
    </div>
  )
}
