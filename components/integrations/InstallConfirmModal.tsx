"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Shield, Download, AlertTriangle, CheckCircle } from "lucide-react"
import type { MarketplaceIntegration } from "./MarketplaceScreen"

interface InstallConfirmModalProps {
  integration: MarketplaceIntegration | null
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  glowColor?: string
  fontColor?: string
}

export function InstallConfirmModal({
  integration,
  isOpen,
  onClose,
  onConfirm,
  glowColor = "#00d4ff",
  fontColor = "#ffffff",
}: InstallConfirmModalProps) {
  if (!integration) return null

  const permissions = getPermissionsForIntegration(integration)

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50"
            style={{ backgroundColor: "rgba(0,0,0,0.7)" }}
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md z-50"
          >
            <div
              className="rounded-2xl border overflow-hidden"
              style={{
                backgroundColor: "rgba(10,10,20,0.95)",
                borderColor: `${glowColor}30`,
                boxShadow: `0 0 60px ${glowColor}20`,
              }}
            >
              {/* Header */}
              <div
                className="flex items-center justify-between p-4 border-b"
                style={{ borderColor: `${glowColor}15` }}
              >
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{integration.icon}</span>
                  <div>
                    <h3
                      className="text-[15px] font-semibold"
                      style={{ color: fontColor }}
                    >
                      {integration.name}
                    </h3>
                    <div className="flex items-center gap-2 text-[10px]" style={{ color: `${fontColor}50` }}>
                      <span>{integration.publisher}</span>
                      {integration.verified && (
                        <>
                          <span>•</span>
                          <span className="flex items-center gap-0.5" style={{ color: glowColor }}>
                            <Shield size={10} />
                            Verified
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="p-2 rounded-lg transition-all duration-150"
                  style={{ color: `${fontColor}50` }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = fontColor
                    e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.05)"
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = `${fontColor}50`
                    e.currentTarget.style.backgroundColor = "transparent"
                  }}
                >
                  <X size={18} />
                </button>
              </div>

              {/* Content */}
              <div className="p-4 space-y-4">
                {/* Description */}
                <p className="text-[12px]" style={{ color: `${fontColor}70` }}>
                  {integration.description}
                </p>

                {/* Permissions */}
                <div>
                  <h4
                    className="text-[11px] font-semibold uppercase tracking-wider mb-3"
                    style={{ color: `${fontColor}50` }}
                  >
                    Permissions Required
                  </h4>
                  <div className="space-y-2">
                    {permissions.map((permission, index) => (
                      <div
                        key={index}
                        className="flex items-start gap-3 p-3 rounded-lg"
                        style={{ backgroundColor: "rgba(255,255,255,0.03)" }}
                      >
                        <div
                          className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: `${glowColor}15` }}
                        >
                          <permission.icon size={14} style={{ color: glowColor }} />
                        </div>
                        <div>
                          <p className="text-[11px] font-medium" style={{ color: fontColor }}>
                            {permission.title}
                          </p>
                          <p className="text-[9px]" style={{ color: `${fontColor}50` }}>
                            {permission.description}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Warning */}
                <div
                  className="flex items-start gap-2 p-3 rounded-lg"
                  style={{ backgroundColor: "rgba(251,191,36,0.1)" }}
                >
                  <AlertTriangle size={14} style={{ color: "#fbbf24" }} className="flex-shrink-0 mt-0.5" />
                  <p className="text-[10px]" style={{ color: "#fbbf24" }}>
                    This integration will have access to your account data. 
                    Only install integrations from publishers you trust.
                  </p>
                </div>
              </div>

              {/* Actions */}
              <div
                className="flex items-center gap-3 p-4 border-t"
                style={{ borderColor: `${glowColor}15` }}
              >
                <button
                  onClick={onClose}
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
                  Cancel
                </button>
                <button
                  onClick={onConfirm}
                  className="flex-1 py-2.5 rounded-lg text-[12px] font-medium flex items-center justify-center gap-2 transition-all duration-150"
                  style={{
                    color: "#000",
                    backgroundColor: glowColor,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.filter = "brightness(1.1)"
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.filter = "brightness(1)"
                  }}
                >
                  <Download size={14} />
                  Install
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

interface Permission {
  icon: React.ElementType
  title: string
  description: string
}

function getPermissionsForIntegration(integration: MarketplaceIntegration): Permission[] {
  const basePermissions: Permission[] = [
    {
      icon: CheckCircle,
      title: "Basic Integration Access",
      description: "Access to basic integration functionality and settings",
    },
  ]

  switch (integration.category) {
    case "email":
      return [
        ...basePermissions,
        {
          icon: Shield,
          title: "Email Access",
          description: "Read, send, and manage emails from your account",
        },
      ]
    case "messaging":
      return [
        ...basePermissions,
        {
          icon: Shield,
          title: "Messaging Access",
          description: "Send and receive messages on your behalf",
        },
      ]
    case "productivity":
      return [
        ...basePermissions,
        {
          icon: Shield,
          title: "Workspace Access",
          description: "Create and modify items in your workspace",
        },
      ]
    case "developer":
      return [
        ...basePermissions,
        {
          icon: Shield,
          title: "Repository/Project Access",
          description: "Access to repositories, issues, and project data",
        },
      ]
    default:
      return basePermissions
  }
}

export default InstallConfirmModal
