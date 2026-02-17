"use client"

import { useState, useEffect, useCallback } from "react"

// Audio device from backend
export interface AudioDevice {
  index: number
  name: string
  input: boolean
  output: boolean
  sample_rate: number
}

// Device response from API
interface AudioDevicesResponse {
  status: string
  input_devices: AudioDevice[]
  output_devices: AudioDevice[]
  message?: string
}

// Hook return type
export interface UseAudioDevicesReturn {
  inputDevices: string[]
  outputDevices: string[]
  isLoading: boolean
  error: string | null
  refetch: () => void
}

export function useAudioDevices(): UseAudioDevicesReturn {
  const [inputDevices, setInputDevices] = useState<string[]>([])
  const [outputDevices, setOutputDevices] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchDevices = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      
      const response = await fetch("http://localhost:8000/api/voice/devices")
      
      if (!response.ok) {
        throw new Error(`Failed to fetch devices: ${response.status}`)
      }
      
      const data: AudioDevicesResponse = await response.json()
      
      if (data.status === "success") {
        // Extract device names from the response
        const inputs = data.input_devices.map(d => d.name)
        const outputs = data.output_devices.map(d => d.name)
        
        setInputDevices(inputs.length > 0 ? inputs : ["Default"])
        setOutputDevices(outputs.length > 0 ? outputs : ["Default"])
      } else {
        setError(data.message || "Failed to fetch audio devices")
        // Fallback to default options
        setInputDevices(["Default"])
        setOutputDevices(["Default"])
      }
    } catch (err) {
      console.error("[useAudioDevices] Error fetching devices:", err)
      setError(err instanceof Error ? err.message : "Unknown error")
      // Fallback to default options
      setInputDevices(["Default"])
      setOutputDevices(["Default"])
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDevices()
  }, [fetchDevices])

  return {
    inputDevices,
    outputDevices,
    isLoading,
    error,
    refetch: fetchDevices
  }
}
