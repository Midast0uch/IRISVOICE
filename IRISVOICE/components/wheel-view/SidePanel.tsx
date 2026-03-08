"use client"

import React, { useMemo, useCallback, useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"

import { ENERGY_CYCLE } from '@/lib/timing-config'
import { Check, Palette } from "lucide-react"
import { ConnectionLine } from "./ConnectionLine"
// Explicitly import from wheel-view fields barrel export to avoid conflict with general fields
import { ToggleField, SliderField, DropdownField, TextField, ColorField } from "./fields"
import type { Card, FieldConfig, FieldValue } from "@/types/navigation"
import { useNavigation } from "@/contexts/NavigationContext"
import { CARD_TO_SECTION_ID } from "@/data/navigation-constants"
import { IntegrationListPanel } from "@/components/integrations/IntegrationListPanel"
import { CollapsibleSection } from "./CollapsibleSection"
import { ColorSliderGroup } from "./ColorSliderGroup"
import { useBrandColor, ThemeType, PRISM_THEMES } from "@/contexts/BrandColorContext"

interface SidePanelProps {
  card: Card
  glowColor: string
  values: Record<string, FieldValue>
  onValueChange: (fieldId: string, value: FieldValue) => void
  onConfirm: () => void
  lineRetracted: boolean
  orbSize: number
  onBrowseMarketplace?: () => void
}

/**
 * SidePanel Component
 * 
 * Displays input fields for the selected section with glowing connection line.
 * Features:
 * - Position: Right side of orb (orbSize/2 + 12px offset)
 * - Width: 100px (narrow for vertical space)
 * - Max height: 560px
 * - Styling: Glass-morphism (backdrop blur, transparency)
 * - Connection line with spring extension/retraction
 * - Crossfade transitions when switching sections
 * - Empty state handling
 * 
 * Validates: Requirements 5.1, 5.2, 5.5, 5.6, 5.7, 11.2, 11.7, 13.3, 15.2, 15.3
 */
export const SidePanel: React.FC<SidePanelProps> = ({
  card,
  glowColor,
  values,
  onValueChange,
  onConfirm,
  lineRetracted,
  orbSize,
  onBrowseMarketplace,
}) => {
  const { sendMessage } = useNavigation()
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [audioInputDevices, setAudioInputDevices] = useState<string[]>([])
  const [audioOutputDevices, setAudioOutputDevices] = useState<string[]>([])
  const [wakeWords, setWakeWords] = useState<string[]>([])

  // Brand color context for theme panel
  const {
    theme,
    setTheme,
    getThemeConfig,
    brandColor,
    basePlateColor,
    setHue,
    setSaturation,
    setLightness,
    setBasePlateHue,
    setBasePlateSaturation,
    setBasePlateLightness,
    resetToThemeDefault,
  } = useBrandColor()

  // Collapsible section states for theme panel (persist across renders)
  const [brandColorExpanded, setBrandColorExpanded] = useState(false)
  const [basePlateExpanded, setBasePlateExpanded] = useState(false)

  // Theme panel glow color based on current brand settings
  const themeGlowColor = React.useMemo(() => {
    return `hsl(${brandColor.hue}, ${brandColor.saturation}%, ${brandColor.lightness}%)`
  }, [brandColor])

  const themes: ThemeType[] = ['aether', 'ember', 'aurum', 'verdant']

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
      // BUG-02 FIX: Backend sends field_values (snake_case), not fieldValues (camelCase)
      const fv = state.field_values || state.fieldValues
      if (fv && card.id) {
        const sectionId = CARD_TO_SECTION_ID[card.id] || card.id
        const sectionValues = fv[sectionId]
        if (sectionValues) {
          // Update values from backend state
          Object.entries(sectionValues).forEach(([fieldId, value]) => {
            onValueChange(fieldId, value as FieldValue)
          })
        }
      }
    }
    
    window.addEventListener('iris:initial_state', handleInitialState as EventListener)
    
    return () => {
      window.removeEventListener('iris:initial_state', handleInitialState as EventListener)
    }
  }, [sendMessage, card.id, onValueChange])

  // Fetch available models when models-card section is active
  useEffect(() => {
    if (card.id === 'models-card') {
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
  }, [card.id, sendMessage])

  // Fetch audio devices when microphone-card or speaker-card sections are active
  useEffect(() => {
    if (card.id === 'microphone-card' || card.id === 'speaker-card') {
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
  }, [card.id, sendMessage])

  // Fetch wake words when wake-word-card section is active
  useEffect(() => {
    if (card.id === 'wake-word-card') {
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
  }, [card.id, sendMessage])

  // Calculate panel position: anchored at distance for distinct "beam of light" bridge (Phase 48)
  // Calculate panel position: anchored for a precision 85px bridge from wheel edge (Phase 68)
  // Wheel Edge (startX) = 438. 438 + 85 = 523.
  const panelOffset = 523

  // Memoize field rendering function for performance (Requirement 12.3)
  const renderField = useCallback(
    (field: FieldConfig) => {
      const fieldValue = values[field.id] ?? field.defaultValue

      // Conditional field rendering for inference-card section
      if (card.id === 'inference-card') {
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

      // Conditional field rendering for models-card section
      if (card.id === 'models-card') {
        const modelProvider = values['model_provider'] ?? 'local'
        const useSameModel = values['use_same_model'] ?? true

        // Hide API key field unless provider is 'api'
        if (field.id === 'api_key' && modelProvider !== 'api') return null
        // Hide VPS endpoint field unless provider is 'vps'
        if (field.id === 'vps_endpoint' && modelProvider !== 'vps') return null
        // Hide tool_model dropdown when use_same_model is true
        if (field.id === 'tool_model' && useSameModel === true) return null
      }

      // Resolve dropdown options. WebSocket-fetched data takes priority over static loadOptions.
      // When real backend data is available, fieldLoadOptions is cleared so DropdownField
      // uses the `options` prop directly instead of calling the static loadOptions function.
      let fieldOptions = field.options ?? []
      let fieldLoadOptions = field.loadOptions

      // For models-card section, use available models for dropdowns
      if (card.id === 'models-card' && (field.id === 'reasoning_model' || field.id === 'tool_model')) {
        fieldOptions = availableModels.length > 0 ? availableModels : ['No models available']
        fieldLoadOptions = undefined
      }

      // For microphone-card section, use audio input devices from backend
      if (card.id === 'microphone-card' && field.id === 'input_device') {
        // Show real devices from backend; empty until backend responds (no static fallback)
        fieldOptions = audioInputDevices.length > 0 ? audioInputDevices : []
        fieldLoadOptions = undefined
      }

      // For speaker-card section, use audio output devices from backend
      if (card.id === 'speaker-card' && field.id === 'output_device') {
        // Show real devices from backend; empty until backend responds (no static fallback)
        fieldOptions = audioOutputDevices.length > 0 ? audioOutputDevices : []
        fieldLoadOptions = undefined
      }

      // For wake-word-card section, use wake words from backend
      if (card.id === 'wake-word-card' && field.id === 'wake_phrase') {
        fieldOptions = wakeWords.length > 0 ? wakeWords : ['No wake words found']
        fieldLoadOptions = undefined
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
              loadOptions={fieldLoadOptions}
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
    [values, onValueChange, glowColor, card.id, availableModels, audioInputDevices, audioOutputDevices, wakeWords]
  )

  // Memoize field list for performance (Requirement 12.2)
  const fieldList = useMemo(
    () => card.fields.map(renderField).filter(Boolean),
    [card.fields, renderField]
  )

  // ThemePanel component for theme-card
  const ThemePanel = () => {
    const currentTheme = getThemeConfig()

    return (
      <div className="space-y-4">
        {/* Theme Selection Grid - 4 themes in 2x2 */}
        <div className="grid grid-cols-2 gap-2">
          {themes.map((t) => {
            const themeConfig = PRISM_THEMES[t]
            const isSelected = theme === t
            const themeGlow = themeConfig.glow.color

            return (
              <motion.button
                key={t}
                onClick={() => setTheme(t)}
                className="relative p-3 rounded-xl border transition-all duration-200"
                style={{
                  background: isSelected
                    ? `${themeGlow}20`
                    : 'rgba(255,255,255,0.05)',
                  borderColor: isSelected
                    ? themeGlow
                    : 'rgba(255,255,255,0.1)',
                }}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                {/* Color preview dot */}
                <div
                  className="w-4 h-4 rounded-full mx-auto mb-2"
                  style={{
                    background: themeGlow,
                    boxShadow: `0 0 8px ${themeGlow}`,
                  }}
                />
                <span
                  className="text-[9px] font-bold uppercase tracking-wider block text-center"
                  style={{
                    color: isSelected ? '#fff' : 'rgba(255,255,255,0.6)',
                  }}
                >
                  {themeConfig.name}
                </span>
                {isSelected && (
                  <motion.div
                    layoutId="theme-indicator"
                    className="absolute -top-1 -right-1 w-3 h-3 rounded-full"
                    style={{
                      background: themeGlow,
                      boxShadow: `0 0 6px ${themeGlow}`,
                    }}
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  />
                )}
              </motion.button>
            )
          })}
        </div>

        {/* Brand Color Section */}
        <CollapsibleSection
          title="Brand Color"
          isExpanded={brandColorExpanded}
          onToggle={() => setBrandColorExpanded(!brandColorExpanded)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseUp={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerUp={(e) => e.stopPropagation()}
          >
            <ColorSliderGroup
              hue={brandColor.hue}
              saturation={brandColor.saturation}
              lightness={brandColor.lightness}
              onHueChange={setHue}
              onSatChange={setSaturation}
              onLightChange={setLightness}
              glowColor={themeGlowColor}
            />
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation()
              resetToThemeDefault()
            }}
            className="w-full py-2 mt-3 text-[9px] font-bold uppercase tracking-wider rounded-lg transition-all duration-200"
            style={{
              background: `${themeGlowColor}15`,
              border: `1px solid ${themeGlowColor}33`,
              color: themeGlowColor,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = `${themeGlowColor}25`
              e.currentTarget.style.borderColor = `${themeGlowColor}55`
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = `${themeGlowColor}15`
              e.currentTarget.style.borderColor = `${themeGlowColor}33`
            }}
          >
            Reset to Default
          </button>
        </CollapsibleSection>

        {/* Base Plate Section */}
        <CollapsibleSection
          title="Base Plate"
          isExpanded={basePlateExpanded}
          onToggle={() => setBasePlateExpanded(!basePlateExpanded)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseUp={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerUp={(e) => e.stopPropagation()}
          >
          <ColorSliderGroup
            hue={basePlateColor.hue}
            saturation={basePlateColor.saturation}
            lightness={basePlateColor.lightness}
            onHueChange={setBasePlateHue}
            onSatChange={setBasePlateSaturation}
            onLightChange={setBasePlateLightness}
            glowColor={themeGlowColor}
          />
          <button
            onClick={() => {
              // Reset base plate to theme defaults
              const themeDefaults = {
                aether: { hue: 220, saturation: 15, lightness: 15 },
                ember: { hue: 15, saturation: 20, lightness: 15 },
                aurum: { hue: 45, saturation: 20, lightness: 15 },
                verdant: { hue: 150, saturation: 20, lightness: 15 },
              }
              const defaults = themeDefaults[theme]
              setBasePlateHue(defaults.hue)
              setBasePlateSaturation(defaults.saturation)
              setBasePlateLightness(defaults.lightness)
            }}
            className="w-full py-2 mt-3 text-[9px] font-bold uppercase tracking-wider rounded-lg transition-all duration-200"
            style={{
              background: `${themeGlowColor}15`,
              border: `1px solid ${themeGlowColor}33`,
              color: themeGlowColor,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = `${themeGlowColor}25`
              e.currentTarget.style.borderColor = `${themeGlowColor}55`
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = `${themeGlowColor}15`
              e.currentTarget.style.borderColor = `${themeGlowColor}33`
            }}
          >
            Reset to Default
          </button>
          </div>
        </CollapsibleSection>
      </div>
    )
  }

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
          aria-label={`${card.label} settings`}
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
                {card.label}
              </span>
            </div>
          </div>

          {/* Field List - Protective Gutter (Phase 68) */}
          <div className="px-2 py-4 overflow-y-auto max-h-[520px] custom-scrollbar">
            <AnimatePresence mode="wait">
              <motion.div
                key={card.id}
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
                className="h-full"
              >
               {/* Integration List Panel for integrations-card */}
                {card.id === 'integrations-card' ? (
                  <IntegrationListPanel onBrowseMarketplace={onBrowseMarketplace} />
                ) : card.id === 'theme-card' ? (
                  <ThemePanel />
                ) : card.fields.length === 0 ? (
                  /* Empty state handling (Requirement 5.7, 15.2) */
                  <div className="py-6 text-center">
                    <span className="text-[10px] text-white/40 uppercase tracking-wider">
                      No settings available
                    </span>
                    <p className="text-[9px] text-white/30 mt-2 leading-relaxed px-2">
                      This section has no configurable fields
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
