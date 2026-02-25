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
  // Calculate panel position: anchored at distance for distinct "beam of light" bridge (Phase 48)
  // Calculate panel position: anchored for a precision 65px bridge from wheel edge (Phase 66)
  // Wheel Edge (startX) = 438. 438 + 65 = 503.
  const panelOffset = 503

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
        onMouseDown={(e) => e.stopPropagation()}
        style={{
          left: panelOffset,
          top: "50%",
          width: "155px", // Precision Stretch (Phase 59)
          maxHeight: "680px", // High-Capacity Vertical (Phase 59)
          pointerEvents: "auto",
        }}
        initial={{ opacity: 0, x: -20, y: "-50%" }}
        animate={{ opacity: 1, x: 0, y: "-50%" }}
        exit={{ opacity: 0, x: -20, y: "-50%" }}
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
          {/* Panel Header - Reference Gutter (Phase 60) */}
          <div className="px-6 py-4 border-b border-white/10">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: glowColor, boxShadow: `0 0 8px ${glowColor}` }} />
              <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-white/50">
                {miniNode.label}
              </span>
            </div>
          </div>

          {/* Field List - Deep Gutter (Phase 60) */}
          <div className="px-6 py-6 overflow-y-auto max-h-[520px] custom-scrollbar">
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
                  <div className="py-6 text-center">
                    <span className="text-[10px] text-white/40 uppercase tracking-wider">
                      No settings available
                    </span>
                    <p className="text-[9px] text-white/30 mt-2 leading-relaxed px-2">
                      This mini-node has no configurable fields
                    </p>
                  </div>
                ) : (
                  <div className="space-y-6">{fieldList}</div> // Stretched spacing (Phase 59)
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Panel Footer - Rounded Pill (Phase 60) */}
          <div className="px-6 py-4 border-t border-white/10">
            <button
              onClick={onConfirm}
              aria-label="Confirm settings"
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-full transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-white/20 active:scale-[0.97]"
              style={{
                backgroundColor: `${glowColor}15`,
                border: `1px solid ${glowColor}33`,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = `${glowColor}25`
                e.currentTarget.style.borderColor = `${glowColor}55`
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = `${glowColor}15`
                e.currentTarget.style.borderColor = `${glowColor}33`
              }}
            >
              <Check
                className="w-4 h-4"
                style={{ color: glowColor }}
                strokeWidth={3}
              />
              <span
                className="text-[11px] font-bold uppercase tracking-wider"
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
