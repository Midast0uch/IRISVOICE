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
    <div className="flex flex-col gap-1 py-1">
      <div className="flex items-center justify-between">
        <label
          htmlFor={id}
          className="text-[10px] font-medium uppercase tracking-wider text-white/60"
        >
          {label}
        </label>
        <span className="text-[10px] font-mono text-white/80">
          {value}
          {unit && <span className="text-white/40 ml-0.5">{unit}</span>}
        </span>
      </div>
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
          background: `linear-gradient(to right, ${glowColor} 0%, ${glowColor} ${
            ((value - min) / (max - min)) * 100
          }%, rgba(255, 255, 255, 0.1) ${
            ((value - min) / (max - min)) * 100
          }%, rgba(255, 255, 255, 0.1) 100%)`,
        }}
      />
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
