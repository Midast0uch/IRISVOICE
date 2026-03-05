"use client"

import React, { useRef, useCallback, useEffect, useState } from "react"

interface ColorSliderGroupProps {
  hue: number
  saturation: number
  lightness: number
  onHueChange: (value: number) => void
  onSatChange: (value: number) => void
  onLightChange: (value: number) => void
  glowColor: string
}

/**
 * ColorSliderGroup Component
 * 
 * Three HSL sliders using native range inputs with optimized responsiveness.
 * Uses requestAnimationFrame for smooth updates and onInput for immediate feedback.
 */
export const ColorSliderGroup: React.FC<ColorSliderGroupProps> = ({
  hue,
  saturation,
  lightness,
  onHueChange,
  onSatChange,
  onLightChange,
  glowColor,
}) => {
  // Use refs to avoid re-render lag
  const hueRef = useRef<HTMLInputElement>(null)
  const satRef = useRef<HTMLInputElement>(null)
  const lightRef = useRef<HTMLInputElement>(null)
  
  // Local state for immediate UI updates
  const [localHue, setLocalHue] = useState(hue)
  const [localSat, setLocalSat] = useState(saturation)
  const [localLight, setLocalLight] = useState(lightness)
  
  // Sync local state with props
  useEffect(() => setLocalHue(hue), [hue])
  useEffect(() => setLocalSat(saturation), [saturation])
  useEffect(() => setLocalLight(lightness), [lightness])

  // Optimized change handler using requestAnimationFrame
  const handleChange = useCallback((
    value: number,
    setter: (v: number) => void,
    onChange: (v: number) => void
  ) => {
    // Update local state immediately for responsive UI
    setter(value)
    // Use requestAnimationFrame to batch the parent update
    requestAnimationFrame(() => {
      onChange(value)
    })
  }, [])

  return (
    <>
      <style jsx>{`
        input[type="range"] {
          -webkit-appearance: none;
          appearance: none;
          height: 8px;
          border-radius: 4px;
          outline: none;
          padding: 0;
          margin: 0;
          touch-action: none;
        }
        
        input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: white;
          cursor: grab;
          box-shadow: 0 0 8px rgba(0,0,0,0.3), 0 2px 4px rgba(0,0,0,0.2);
          transition: transform 0.1s;
        }
        
        input[type="range"]::-webkit-slider-thumb:active {
          cursor: grabbing;
          transform: scale(1.1);
        }
        
        input[type="range"]::-moz-range-thumb {
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: white;
          cursor: grab;
          border: none;
          box-shadow: 0 0 8px rgba(0,0,0,0.3), 0 2px 4px rgba(0,0,0,0.2);
        }
        
        input[type="range"]::-moz-range-thumb:active {
          cursor: grabbing;
          transform: scale(1.1);
        }
      `}</style>
      <div className="space-y-4">
        {/* Hue Slider */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-white/60">Hue</span>
            <span className="text-[11px] font-mono" style={{ color: glowColor }}>
              {Math.round(localHue)}°
            </span>
          </div>
          <input
            ref={hueRef}
            type="range"
            min={0}
            max={360}
            value={localHue}
            onInput={(e) => handleChange(
              Number((e.target as HTMLInputElement).value),
              setLocalHue,
              onHueChange
            )}
            className="w-full cursor-pointer"
            style={{
              background: `linear-gradient(to right, 
                hsl(0, 100%, 50%), 
                hsl(60, 100%, 50%), 
                hsl(120, 100%, 50%), 
                hsl(180, 100%, 50%), 
                hsl(240, 100%, 50%), 
                hsl(300, 100%, 50%), 
                hsl(360, 100%, 50%))`,
            }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
          />
        </div>

        {/* Saturation Slider */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-white/60">Saturation</span>
            <span className="text-[11px] font-mono" style={{ color: glowColor }}>
              {Math.round(localSat)}%
            </span>
          </div>
          <input
            ref={satRef}
            type="range"
            min={0}
            max={100}
            value={localSat}
            onInput={(e) => handleChange(
              Number((e.target as HTMLInputElement).value),
              setLocalSat,
              onSatChange
            )}
            className="w-full cursor-pointer"
            style={{
              background: `linear-gradient(to right, hsl(${localHue}, 0%, 50%), hsl(${localHue}, 100%, 50%))`,
            }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
          />
        </div>

        {/* Lightness Slider */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-white/60">Lightness</span>
            <span className="text-[11px] font-mono" style={{ color: glowColor }}>
              {Math.round(localLight)}%
            </span>
          </div>
          <input
            ref={lightRef}
            type="range"
            min={0}
            max={100}
            value={localLight}
            onInput={(e) => handleChange(
              Number((e.target as HTMLInputElement).value),
              setLocalLight,
              onLightChange
            )}
            className="w-full cursor-pointer"
            style={{
              background: `linear-gradient(to right, 
                hsl(${localHue}, ${localSat}%, 0%), 
                hsl(${localHue}, ${localSat}%, 50%), 
                hsl(${localHue}, ${localSat}%, 100%))`,
            }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
          />
        </div>
      </div>
    </>
  )
}

export default ColorSliderGroup