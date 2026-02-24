"use client"

import React, { useMemo, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Check } from "lucide-react"
import { ConnectionLine } from "./ConnectionLine"
import { ToggleField } from "./fields/ToggleField"
import { SliderField } from "./fields/SliderField"
import { DropdownField } from "./fields/DropdownField"
import { TextField } from "./fields/TextField"
import { ColorField } from "./fields/ColorField"
import type { MiniNode, FieldConfig, FieldValue } from "@/types/navigation"

interface SidePanelProps {
  miniNode: MiniNode
  glowColor: string
  values: Record<string, FieldValue>
  onValueChange: (fieldId: string, value: FieldValue) => void
  onConfirm: () => void
  lineRetracted: boolean
  orbSize: number
}

/**
 * SidePanel Component
 * 
 * Displays input fields for the selected mini-node with glowing connection line.
 * Features:
 * - Position: Right side of orb (orbSize/2 + 12px offset)
 * - Width: 100px (narrow for vertical space)
 * - Max height: 560px
 * - Styling: Glass-morphism (backdrop blur, transparency)
 * - Connection line with spring extension/retraction
 * - Crossfade transitions when switching mini-nodes
 * - Empty state handling
 * 
 * Validates: Requirements 5.1, 5.2, 5.5, 5.6, 5.7, 11.2, 11.7, 13.3, 15.2, 15.3
 */
export const SidePanel: React.FC<SidePanelProps> = ({
  miniNode,
  glowColor,
  values,
  onValueChange,
  onConfirm,
  lineRetracted,
  orbSize,
}) => {
  // Calculate panel position: orbSize/2 + 12px offset
  const panelOffset = orbSize / 2 + 12

  // Memoize field rendering function for performance (Requirement 12.3)
  const renderField = useCallback(
    (field: FieldConfig) => {
      const fieldValue = values[field.id] ?? field.defaultValue

      switch (field.type) {
        case "text":
          return (
            <TextField
              key={field.id}
              id={field.id}
              label={field.label}
              value={(fieldValue as string) ?? ""}
              placeholder={field.placeholder}
              onChange={(value) => onValueChange(field.id, value)}
              glowColor={glowColor}
            />
          )

        case "slider":
          return (
            <SliderField
              key={field.id}
              id={field.id}
              label={field.label}
              value={(fieldValue as number) ?? field.min ?? 0}
              min={field.min ?? 0}
              max={field.max ?? 100}
              step={field.step ?? 1}
              unit={field.unit}
              onChange={(value) => onValueChange(field.id, value)}
              glowColor={glowColor}
            />
          )

        case "dropdown":
          return (
            <DropdownField
              key={field.id}
              id={field.id}
              label={field.label}
              value={(fieldValue as string) ?? ""}
              options={field.options ?? []}
              loadOptions={field.loadOptions}
              onChange={(value) => onValueChange(field.id, value)}
              glowColor={glowColor}
            />
          )

        case "toggle":
          return (
            <ToggleField
              key={field.id}
              id={field.id}
              label={field.label}
              value={(fieldValue as boolean) ?? false}
              onChange={(value) => onValueChange(field.id, value)}
              glowColor={glowColor}
            />
          )

        case "color":
          return (
            <ColorField
              key={field.id}
              id={field.id}
              label={field.label}
              value={(fieldValue as string) ?? "#000000"}
              onChange={(value) => onValueChange(field.id, value)}
              glowColor={glowColor}
            />
          )

        default:
          // Skip invalid field types with console warning (Requirement 15.3)
          console.warn(
            `[SidePanel] Invalid field type: ${field.type} for field ${field.id}`
          )
          return null
      }
    },
    [values, onValueChange, glowColor]
  )

  // Memoize field list for performance (Requirement 12.2)
  const fieldList = useMemo(
    () => miniNode.fields.map(renderField).filter(Boolean),
    [miniNode.fields, renderField]
  )

  return (
    <>
      {/* Connection Line */}
      <ConnectionLine
        glowColor={glowColor}
        lineRetracted={lineRetracted}
        orbSize={orbSize}
        panelOffset={panelOffset}
      />

      {/* Side Panel */}
      <motion.div
        className="absolute flex flex-col"
        style={{
          left: panelOffset,
          top: "50%",
          transform: "translateY(-50%)",
          width: "100px",
          maxHeight: "560px",
        }}
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -20 }}
        transition={{
          type: "spring",
          stiffness: 200,
          damping: 25,
        }}
      >
        {/* Panel Container with glass-morphism styling */}
        <div
          role="dialog"
          aria-label={`${miniNode.label} settings`}
          className="relative rounded-lg overflow-hidden"
          style={{
            backgroundColor: "rgba(0, 0, 0, 0.4)",
            backdropFilter: "blur(12px)",
            border: `1px solid ${glowColor}33`,
            boxShadow: `0 0 20px ${glowColor}22`,
          }}
        >
          {/* Panel Header */}
          <div className="px-3 py-2 border-b border-white/10">
            <div className="flex items-center gap-2">
              {/* Indicator dot */}
              <div
                className="w-1.5 h-1.5 rounded-full"
                style={{
                  backgroundColor: glowColor,
                  boxShadow: `0 0 6px ${glowColor}`,
                }}
              />
              {/* Mini-node label */}
              <span className="text-[10px] font-medium uppercase tracking-wider text-white/80">
                {miniNode.label}
              </span>
            </div>
          </div>

          {/* Field List with crossfade transitions */}
          <div className="px-3 py-2 overflow-y-auto max-h-[440px] custom-scrollbar">
            <AnimatePresence mode="wait">
              <motion.div
                key={miniNode.id}
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
              >
                {/* Empty state handling (Requirement 5.7, 15.2) */}
                {miniNode.fields.length === 0 ? (
                  <div className="py-4 text-center">
                    <span className="text-[10px] text-white/40 uppercase tracking-wider">
                      No settings available
                    </span>
                    <p className="text-[9px] text-white/30 mt-1">
                      This mini-node has no configurable fields
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">{fieldList}</div>
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Panel Footer with confirm button */}
          <div className="px-3 py-2 border-t border-white/10">
            <button
              onClick={onConfirm}
              aria-label="Confirm settings"
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-white/20"
              style={{
                backgroundColor: `${glowColor}22`,
                border: `1px solid ${glowColor}44`,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = `${glowColor}33`
                e.currentTarget.style.borderColor = `${glowColor}66`
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = `${glowColor}22`
                e.currentTarget.style.borderColor = `${glowColor}44`
              }}
            >
              <Check
                className="w-3.5 h-3.5"
                style={{ color: glowColor }}
              />
              <span
                className="text-[10px] font-medium uppercase tracking-wider"
                style={{ color: glowColor }}
              >
                Confirm
              </span>
            </button>
          </div>
        </div>
      </motion.div>

      {/* Custom scrollbar styles */}
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.05);
          border-radius: 2px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.2);
          border-radius: 2px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.3);
        }
      `}</style>
    </>
  )
}
