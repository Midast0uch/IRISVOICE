"use client"

import React from "react"

interface SliderFieldProps {
  id: string
  label: string
  value: number
  min: number
  max: number
  step: number
  unit?: string
  onChange: (value: number) => void
  glowColor: string
}

const SliderFieldComponent: React.FC<SliderFieldProps> = ({
  id,
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  glowColor,
}) => {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex justify-between items-end">
        <label
          htmlFor={id}
          className="text-[9px] font-bold uppercase tracking-[0.08em] text-white/30 leading-tight flex-1"
        >
          {label}
        </label>
        <div className="flex items-baseline gap-1">
          <span className="text-[12px] font-bold text-white/90">
            {value}
          </span>
          {unit && <span className="text-[8px] text-white/40 uppercase tracking-tighter">{unit}</span>}
        </div>
      </div>
      <div className="px-4 py-4 rounded-xl border border-white/10 bg-black/20">
        <input
          id={id}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full h-1 rounded-full appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-white/20"
          style={{
            background: `linear-gradient(to right, ${glowColor} 0%, ${glowColor} ${((value - min) / (max - min)) * 100
              }%, rgba(255, 255, 255, 0.1) ${((value - min) / (max - min)) * 100
              }%, rgba(255, 255, 255, 0.1) 100%)`,
          }}
        />
      </div>
      <style jsx>{`
        input[type="range"]::-webkit-slider-thumb {
          appearance: none;
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: white;
          cursor: pointer;
          box-shadow: 0 0 4px rgba(0, 0, 0, 0.3);
        }
        input[type="range"]::-moz-range-thumb {
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: white;
          cursor: pointer;
          border: none;
          box-shadow: 0 0 4px rgba(0, 0, 0, 0.3);
        }
      `}</style>
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const SliderField = React.memo(SliderFieldComponent)
