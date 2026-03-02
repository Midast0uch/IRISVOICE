"use client"

import React, { useMemo, useCallback, useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"

// Extension Manager Hook (Phase 2)
const useExtensionManager = () => {
  const [mcpServers, setMcpServers] = useState([]);
  const [skills, setSkills] = useState([]);
  const [savedWorkflows, setSavedWorkflows] = useState([]);

  const manageMcpServer = (serverId: string, action: 'add' | 'remove' | 'configure') => {
    console.log(`[Phase 2] MCP Server ${action}: ${serverId}`);
    // TODO: Implement in Phase 2
  };

  const manageSkill = (skillId: string, action: 'enable' | 'disable' | 'configure') => {
    console.log(`[Phase 2] Skill ${action}: ${skillId}`);
    // TODO: Implement in Phase 2
  };

  const manageWorkflow = (workflowId: string, action: 'save' | 'delete' | 'execute') => {
    console.log(`[Phase 2] Workflow ${action}: ${workflowId}`);
    // TODO: Implement in Phase 2
  };

  return {
    mcpServers,
    skills,
    savedWorkflows,
    manageMcpServer,
    manageSkill,
    manageWorkflow
  };
};
import { ENERGY_CYCLE } from '@/lib/timing-config'
import { Check } from "lucide-react"
import { ConnectionLine } from "./ConnectionLine"
// Explicitly import from wheel-view fields barrel export to avoid conflict with general fields
import { ToggleField, SliderField, DropdownField, TextField, ColorField } from "./fields"
import type { MiniNode, FieldConfig, FieldValue } from "@/types/navigation"
import { useNavigation } from "@/contexts/NavigationContext"
import { CARD_TO_SECTION_ID } from "@/data/navigation-constants"

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
  const { sendMessage } = useNavigation()
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [audioInputDevices, setAudioInputDevices] = useState<string[]>([])
  const [audioOutputDevices, setAudioOutputDevices] = useState<string[]>([])
  const [wakeWords, setWakeWords] = useState<string[]>([])

  // Fetch current configuration from backend on mount
  useEffect(() => {
    // Request current state from backend
    sendMessage('request_state', {})
    
    // Listen for initial state response
    const handleInitialState = (event: CustomEvent) => {
      const state = event.detail?.state || {}
      console.log('[SidePanel] Received initial state:', state)
      
      // Extract field values from the state
      // BUG-07 FIX: Use CARD_TO_SECTION_ID mapping for correct lookup
      // Backend stores values under Section IDs, not Card IDs
      if (state.fieldValues && miniNode.id) {
        const sectionId = CARD_TO_SECTION_ID[miniNode.id] || miniNode.id
        const subnodeValues = state.fieldValues[sectionId]
        if (subnodeValues) {
          // Update values from backend state
          Object.entries(subnodeValues).forEach(([fieldId, value]) => {
            onValueChange(fieldId, value as FieldValue)
          })
        }
      }
    }
    
    window.addEventListener('iris:initial_state', handleInitialState as EventListener)
    
    return () => {
      window.removeEventListener('iris:initial_state', handleInitialState as EventListener)
    }
  }, [sendMessage, miniNode.id, onValueChange])

  // Fetch available models when models-card mini-node is active
  useEffect(() => {
    if (miniNode.id === 'models-card') {
      // Send get_available_models message to backend
      sendMessage('get_available_models', {})
      
      // Listen for the response
      const handleAvailableModels = (event: CustomEvent) => {
        const models = event.detail.models || []
        const modelOptions = models.map((m: any) => m.name || m.id)
        setAvailableModels(modelOptions)
      }
      
      window.addEventListener('iris:available_models', handleAvailableModels as EventListener)
      
      return () => {
        window.removeEventListener('iris:available_models', handleAvailableModels as EventListener)
      }
    }
  }, [miniNode.id, sendMessage])

  // Fetch audio devices when input-device or output-device mini-nodes are active
  useEffect(() => {
    if (miniNode.id === 'input-device' || miniNode.id === 'output-device') {
      // Send get_audio_devices message to backend
      sendMessage('get_audio_devices', {})
      
      // Listen for the response
      const handleAudioDevices = (event: CustomEvent) => {
        const inputDevices = event.detail.input_devices || []
        const outputDevices = event.detail.output_devices || []
        const inputOptions = inputDevices.map((d: any) => d.name || d.index)
        const outputOptions = outputDevices.map((d: any) => d.name || d.index)
        setAudioInputDevices(inputOptions)
        setAudioOutputDevices(outputOptions)
      }
      
      window.addEventListener('iris:audio_devices', handleAudioDevices as EventListener)
      
      return () => {
        window.removeEventListener('iris:audio_devices', handleAudioDevices as EventListener)
      }
    }
  }, [miniNode.id, sendMessage])

  // Fetch wake words when wake-word-card mini-node is active
  useEffect(() => {
    if (miniNode.id === 'wake-word-card') {
      // Send get_wake_words message to backend
      sendMessage('get_wake_words', {})
      
      // Listen for the response
      const handleWakeWords = (event: CustomEvent) => {
        const wakeWordsList = event.detail.wake_words || []
        const wakeWordOptions = wakeWordsList.map((w: any) => w.display_name || w.filename)
        setWakeWords(wakeWordOptions)
      }
      
      window.addEventListener('iris:wake_words_list', handleWakeWords as EventListener)
      
      return () => {
        window.removeEventListener('iris:wake_words_list', handleWakeWords as EventListener)
      }
    }
  }, [miniNode.id, sendMessage])

  // Calculate panel position: anchored at distance for distinct "beam of light" bridge (Phase 48)
  // Calculate panel position: anchored for a precision 85px bridge from wheel edge (Phase 68)
  // Wheel Edge (startX) = 438. 438 + 85 = 523.
  const panelOffset = 523

  // Memoize field rendering function for performance (Requirement 12.3)
  const renderField = useCallback(
    (field: FieldConfig) => {
      const fieldValue = values[field.id] ?? field.defaultValue

      // Conditional field rendering for inference-card mini-node
      if (miniNode.id === 'inference-card') {
        const inferenceMode = values['inference_mode'] ?? 'Local Models'
        
        // Hide VPS fields unless VPS Gateway is selected
        if ((field.id === 'section_vps' || field.id === 'vps_url' || field.id === 'vps_api_key' || field.id === 'test_vps_connection') && inferenceMode !== 'VPS Gateway') {
          return null
        }
        
        // Hide OpenAI fields unless OpenAI API is selected
        if ((field.id === 'section_openai' || field.id === 'openai_api_key' || field.id === 'test_openai_connection') && inferenceMode !== 'OpenAI API') {
          return null
        }
        
        // Hide GPU warning unless Local Models is selected
        if ((field.id === 'section_local_warning' || field.id === 'local_gpu_warning') && inferenceMode !== 'Local Models') {
          return null
        }
      }

      // For models-card mini-node, use available models for dropdowns
      let fieldOptions = field.options ?? []
      if (miniNode.id === 'models-card' && (field.id === 'reasoning_model' || field.id === 'tool_execution_model')) {
        fieldOptions = availableModels.length > 0 ? availableModels : ['No models available']
      }

      // For input-device mini-node, use audio input devices
      if (miniNode.id === 'input-device' && field.id === 'input_device') {
        fieldOptions = audioInputDevices.length > 0 ? audioInputDevices : ['No input devices found']
      }

      // For output-device mini-node, use audio output devices
      if (miniNode.id === 'output-device' && field.id === 'output_device') {
        fieldOptions = audioOutputDevices.length > 0 ? audioOutputDevices : ['No output devices found']
      }

      // For wake-word-card mini-node, use wake words
      if (miniNode.id === 'wake-word-card' && field.id === 'wake_phrase') {
        fieldOptions = wakeWords.length > 0 ? wakeWords : ['No wake words found']
      }

      switch (field.type) {
        case "section":
          return (
            <div key={field.id} className="pt-4 pb-1 border-b border-white/5 mb-2">
              <span className="text-[9px] font-black uppercase tracking-[0.2em] text-white/30">
                {field.label}
              </span>
            </div>
          )

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
              options={fieldOptions}
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

        case "custom":
          return (
            <button
              key={field.id}
              onClick={() => onValueChange(field.id, "trigger")}
              className="w-full py-2 px-3 rounded-xl text-[10px] font-bold uppercase tracking-wider transition-all"
              style={{
                background: `${glowColor}15`,
                border: `1px solid ${glowColor}44`,
                color: glowColor
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = `${glowColor}25`
                e.currentTarget.style.borderColor = `${glowColor}66`
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = `${glowColor}15`
                e.currentTarget.style.borderColor = `${glowColor}44`
              }}
            >
              {field.label}
            </button>
          )

        default:
          // Skip invalid field types with console warning (Requirement 15.3)
          console.warn(
            `[SidePanel] Invalid field type: ${field.type} for field ${field.id}`
          )
          return null
      }
    },
    [values, onValueChange, glowColor, miniNode.id, availableModels]
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
        {/* Power Intake Energy Border (Phase 85 - Single High-Intensity) */}
        <svg
          className="absolute inset-0 pointer-events-none"
          width="100%"
          height="100%"
          style={{ overflow: 'visible', zIndex: 1 }}
        >
          {/* SS2: Perpetual Smart Panel Particle (Phase 84) - Slot: 4-7s Active */}
          <motion.rect
            x="0.5"
            y="0.5"
            width="154"
            height="100%"
            rx="24"
            ry="24"
            fill="none"
            stroke="white"
            strokeWidth="3.5"
            strokeLinecap="round"
            pathLength="1"
            initial={{ strokeDasharray: "0.02 0.98", strokeDashoffset: 0.8, opacity: 0.35 }}
            animate={{
              strokeDashoffset: [0.8, -0.2], // Constant loop
              opacity: [0.35, 0.35, 0.95, 0.95, 0.35] // Flares during 4-7s active
            }}
            transition={{
              strokeDashoffset: {
                duration: ENERGY_CYCLE.duration / 4,
                repeat: Infinity,
                ease: "linear"
              },
              opacity: {
                duration: ENERGY_CYCLE.duration,
                repeat: Infinity,
                ease: "linear",
                times: [
                  0,
                  ENERGY_CYCLE.segments.ss2Panel.start,
                  ENERGY_CYCLE.segments.ss2Panel.start + 0.05,
                  ENERGY_CYCLE.segments.ss2Panel.end,
                  1.0
                ]
              }
            }}
            style={{
              filter: `blur(0.5px) drop-shadow(0 0 15px ${glowColor}) drop-shadow(0 0 8px white)`,
            }}
          />
        </svg>

        {/* Panel Container with glass-morphism styling */}
        <div
          role="dialog"
          aria-label={`${miniNode.label} settings`}
          className="relative rounded-[1.5rem] overflow-hidden"
          style={{
            backgroundColor: "rgba(0, 0, 0, 0.45)",
            backdropFilter: "blur(16px)",
            border: `1px solid rgba(255, 255, 255, 0.1)`,
            boxShadow: `0 20px 40px rgba(0, 0, 0, 0.4)`,
            height: '100%'
          }}
        >
          {/* Panel Header - Centered Spacing (Phase 68) */}
          <div className="px-7 py-4 border-b border-white/10 flex justify-center">
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: glowColor, boxShadow: `0 0 8px ${glowColor}` }} />
              <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-white/50">
                {miniNode.label}
              </span>
            </div>
          </div>

          {/* Field List - Protective Gutter (Phase 68) */}
          <div className="px-7 py-6 overflow-y-auto max-h-[520px] custom-scrollbar">
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
                  <div className="space-y-6">{fieldList}</div>
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Panel Footer - Protective Gutter (Phase 68) */}
          <div className="px-7 py-4 border-t border-white/10">
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
