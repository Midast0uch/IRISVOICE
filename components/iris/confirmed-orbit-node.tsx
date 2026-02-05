"use client"

import React, { type ElementType } from "react"
import { motion } from "framer-motion"
import { Mic, Bot, Settings, Database, Activity, Volume2, AudioWaveform as Waveform, Cpu, Sparkles, MessageSquare, Palette, Power, Keyboard, RefreshCw, BarChart3, FileText, Smile, Zap, Wrench, Layers, Star, Monitor, HardDrive, Wifi, Sliders, Bell, Stethoscope } from "lucide-react"

const ICON_MAP: Record<string, ElementType> = {
  Mic,
  Bot,
  Settings,
  Database,
  Activity,
  Volume2,
  Waveform,
  Cpu,
  Sparkles,
  MessageSquare,
  Palette,
  Power,
  Keyboard,
  RefreshCw,
  BarChart3,
  FileText,
  Smile,
  Zap,
  Wrench,
  Layers,
  Star,
  Monitor,
  HardDrive,
  Wifi,
  Sliders,
  Bell,
  Stethoscope,
}

interface ConfirmedOrbitNodeProps {
  label: string
  icon: string | ElementType
  orbitAngle: number
  glowColor: string
  orbitRadius: number
  size: number
}

export function ConfirmedOrbitNode({ label, icon, orbitAngle, glowColor, orbitRadius, size }: ConfirmedOrbitNodeProps) {
  const IconComponent = typeof icon === "string" ? ICON_MAP[icon] || Mic : icon

  return (
    <motion.div
      className="absolute flex items-center justify-center pointer-events-auto"
      style={{
        width: size,
        height: size,
        left: "50%",
        top: "50%",
        marginLeft: -size / 2,
        marginTop: -size / 2,
      }}
      initial={{ scale: 0, opacity: 0 }}
      animate={{
        scale: 1,
        x: Math.cos((orbitAngle * Math.PI) / 180) * orbitRadius,
        y: Math.sin((orbitAngle * Math.PI) / 180) * orbitRadius,
        opacity: 1,
      }}
      transition={{ type: "spring", stiffness: 100, damping: 15 }}
    >
      <div
        className="w-full h-full flex flex-col items-center justify-center gap-1 rounded-2xl cursor-pointer"
        style={{
          background: "rgba(255, 255, 255, 0.08)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255, 255, 255, 0.1)",
        }}
      >
        <IconComponent className="w-5 h-5" style={{ color: glowColor }} strokeWidth={1.5} />
        <span className="text-[8px] font-medium tracking-wider text-muted-foreground">
          {label}
        </span>
      </div>
    </motion.div>
  )
}
