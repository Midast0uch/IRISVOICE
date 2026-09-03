"use client"

import React from "react"
import { motion } from "framer-motion"
import { Download, CheckCircle, XCircle, Loader, Package, Terminal } from "lucide-react"

export type InstallStatus = "idle" | "downloading" | "installing" | "configuring" | "success" | "error"

export interface InstallProgressProps {
  integrationName: string
  status: InstallStatus
  progress: number // 0-100
  message?: string
  error?: string
  glowColor?: string
  fontColor?: string
  onRetry?: () => void
  onClose?: () => void
}

const STATUS_CONFIG: Record<InstallStatus, { icon: React.ElementType; label: string; color: string }> = {
  idle: { icon: Download, label: "Ready to install", color: "#00d4ff" },
  downloading: { icon: Loader, label: "Downloading...", color: "#3b82f6" },
  installing: { icon: Package, label: "Installing...", color: "#a855f7" },
  configuring: { icon: Terminal, label: "Configuring...", color: "#f59e0b" },
  success: { icon: CheckCircle, label: "Installation complete!", color: "#22c55e" },
  error: { icon: XCircle, label: "Installation failed", color: "#ef4444" },
}

export function InstallProgress({
  integrationName,
  status,
  progress,
  message,
  error,
  glowColor = "#00d4ff",
  fontColor = "#ffffff",
  onRetry,
  onClose,
}: InstallProgressProps) {
  const config = STATUS_CONFIG[status]
  const StatusIcon = config.icon
  const isComplete = status === "success" || status === "error"
  const isError = status === "error"

  return (
    <div
      className="rounded-xl border p-6"
      style={{
        backgroundColor: "rgba(10,10,20,0.8)",
        borderColor: isError ? "#ef444440" : `${glowColor}30`,
        boxShadow: isError ? "none" : `0 0 40px ${glowColor}10`,
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <motion.div
          animate={status === "downloading" || status === "installing" || status === "configuring" ? { rotate: 360 } : {}}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="w-12 h-12 rounded-xl flex items-center justify-center"
          style={{ backgroundColor: isError ? "#ef444420" : `${glowColor}15` }}
        >
          <StatusIcon
            size={24}
            style={{ color: isError ? "#ef4444" : glowColor }}
            className={status === "downloading" || status === "installing" || status === "configuring" ? "animate-spin" : ""}
          />
        </motion.div>
        <div>
          <h3 className="text-[14px] font-semibold" style={{ color: fontColor }}>
            {integrationName}
          </h3>
          <p
            className="text-[11px] flex items-center gap-2"
            style={{ color: isError ? "#ef4444" : `${fontColor}60` }}
          >
            {config.label}
          </p>
        </div>
      </div>

      {/* Progress Bar */}
      {!isComplete && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px]" style={{ color: `${fontColor}40` }}>
              {message || getDefaultMessage(status)}
            </span>
            <span className="text-[10px] font-medium" style={{ color: glowColor }}>
              {Math.round(progress)}%
            </span>
          </div>
          <div
            className="h-2 rounded-full overflow-hidden"
            style={{ backgroundColor: "rgba(255,255,255,0.05)" }}
          >
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ type: "spring", stiffness: 100, damping: 20 }}
              className="h-full rounded-full"
              style={{
                backgroundColor: isError ? "#ef4444" : glowColor,
                boxShadow: `0 0 10px ${isError ? "#ef4444" : glowColor}50`,
              }}
            />
          </div>
        </div>
      )}

      {/* Success State */}
      {status === "success" && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center py-4"
        >
          <div
            className="w-16 h-16 rounded-full mx-auto mb-3 flex items-center justify-center"
            style={{ backgroundColor: "#22c55e20" }}
          >
            <CheckCircle size={32} style={{ color: "#22c55e" }} />
          </div>
          <p className="text-[12px] mb-1" style={{ color: fontColor }}>
            Installation successful!
          </p>
          <p className="text-[10px]" style={{ color: `${fontColor}50` }}>
            {integrationName} is now ready to use
          </p>
        </motion.div>
      )}

      {/* Error State */}
      {isError && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center py-4"
        >
          <div
            className="w-16 h-16 rounded-full mx-auto mb-3 flex items-center justify-center"
            style={{ backgroundColor: "#ef444420" }}
          >
            <XCircle size={32} style={{ color: "#ef4444" }} />
          </div>
          <p className="text-[12px] mb-1" style={{ color: fontColor }}>
            Installation failed
          </p>
          <p
            className="text-[10px] mb-4 px-4"
            style={{ color: "#ef4444" }}
          >
            {error || "An unexpected error occurred during installation"}
          </p>
        </motion.div>
      )}

      {/* Actions */}
      {isComplete && (
        <div className="flex items-center gap-3 mt-4">
          {isError && onRetry && (
            <button
              onClick={onRetry}
              className="flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all duration-150"
              style={{
                color: fontColor,
                backgroundColor: "rgba(255,255,255,0.05)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.1)"
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.05)"
              }}
            >
              Retry
            </button>
          )}
          {onClose && (
            <button
              onClick={onClose}
              className="flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all duration-150"
              style={{
                color: "#000",
                backgroundColor: isError ? "#ef4444" : glowColor,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.filter = "brightness(1.1)"
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.filter = "brightness(1)"
              }}
            >
              {isError ? "Close" : "Start Using"}
            </button>
          )}
        </div>
      )}

      {/* Status Steps */}
      <div className="flex items-center justify-between mt-6 pt-4 border-t" style={{ borderColor: `${glowColor}10` }}>
        {["downloading", "installing", "configuring"].map((step, index) => {
          const stepStatus = getStepStatus(status, step as InstallStatus)
          return (
            <div key={step} className="flex items-center gap-2">
              <div
                className="w-2 h-2 rounded-full"
                style={{
                  backgroundColor:
                    stepStatus === "complete"
                      ? "#22c55e"
                      : stepStatus === "active"
                      ? glowColor
                      : "rgba(255,255,255,0.1)",
                  boxShadow:
                    stepStatus === "active" ? `0 0 8px ${glowColor}` : "none",
                }}
              />
              <span
                className="text-[9px] capitalize"
                style={{
                  color:
                    stepStatus === "complete"
                      ? "#22c55e"
                      : stepStatus === "active"
                      ? glowColor
                      : `${fontColor}30`,
                }}
              >
                {step}
              </span>
              {index < 2 && (
                <div
                  className="w-8 h-px mx-1"
                  style={{
                    backgroundColor:
                      stepStatus === "complete" ? "#22c55e" : "rgba(255,255,255,0.1)",
                  }}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function getDefaultMessage(status: InstallStatus): string {
  switch (status) {
    case "downloading":
      return "Downloading package files..."
    case "installing":
      return "Installing dependencies..."
    case "configuring":
      return "Setting up configuration..."
    default:
      return "Preparing installation..."
  }
}

function getStepStatus(
  currentStatus: InstallStatus,
  step: InstallStatus
): "pending" | "active" | "complete" {
  const steps: InstallStatus[] = ["downloading", "installing", "configuring"]
  const currentIndex = steps.indexOf(currentStatus)
  const stepIndex = steps.indexOf(step)

  if (stepIndex < currentIndex) return "complete"
  if (stepIndex === currentIndex) return "active"
  return "pending"
}

export default InstallProgress
