"use client"

import React, { Component, ReactNode } from "react"

interface WheelViewErrorBoundaryProps {
  children: ReactNode
}

interface WheelViewErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

/**
 * Error boundary component for WheelView to prevent rendering errors from crashing the entire app.
 * Implements getDerivedStateFromError and componentDidCatch for error handling.
 * Displays fallback UI with error message and "Try again" button.
 */
export class WheelViewErrorBoundary extends Component<
  WheelViewErrorBoundaryProps,
  WheelViewErrorBoundaryState
> {
  constructor(props: WheelViewErrorBoundaryProps) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
    }
  }

  /**
   * Update state when an error is caught
   */
  static getDerivedStateFromError(error: Error): WheelViewErrorBoundaryState {
    return {
      hasError: true,
      error,
    }
  }

  /**
   * Log error details when component catches an error
   */
  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error("[WheelView] Rendering error:", error, errorInfo)
  }

  /**
   * Reset error state to try rendering again
   */
  handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
    })
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <div className="text-red-400 text-sm mb-2">
              Failed to render settings view
            </div>
            <button
              onClick={this.handleReset}
              className="text-xs text-white/60 hover:text-white transition-colors"
              aria-label="Try again"
            >
              Try again
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
