"use client"

import React, { useState, useEffect, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Send } from 'lucide-react';
import { X } from 'lucide-react';
import { Settings } from 'lucide-react';
import { BarChart3, ChevronUp, ChevronDown, Trash2, AlertCircle } from 'lucide-react';
import { DarkGlassDashboard } from './dark-glass-dashboard';


import { useNavigation } from "@/contexts/NavigationContext";

interface Message {
  id: string
  text: string
  sender: "user" | "assistant" | "error"
  timestamp: Date
  errorType?: "agent" | "voice" | "validation"
}

interface ChatViewProps {
  onClose: () => void
  isActive: boolean
  sendMessage?: (message: any) => void
  fieldValues?: Record<string, any>
  updateField?: (subnodeId: string, fieldId: string, value: any) => void
}

export function ChatView({ onClose, isActive, sendMessage, fieldValues, updateField }: ChatViewProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputText, setInputText] = useState("")
  const [showDashboard, setShowDashboard] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const { lastTextResponse, voiceState, clearChat, activeTheme, fieldErrors } = useNavigation();
  
  // Derive isTyping from agent processing state
  const isTyping = voiceState === "processing_conversation" || voiceState === "processing_tool";
  
  // Get theme colors with fallback
  const glowColor = activeTheme?.glow || "#00d4ff";
  const primaryColor = activeTheme?.primary || "#00d4ff";
  const fontColor = activeTheme?.font || "#ffffff";

  // Auto-focus input when chat becomes active
  useEffect(() => {
    if (isActive && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [isActive])

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, isTyping])

  // Handle incoming WebSocket messages from the navigation context
  useEffect(() => {
    if (lastTextResponse) {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        text: lastTextResponse.text,
        sender: "assistant",
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, assistantMessage])
    }
  }, [lastTextResponse])
  
  // Handle voice command errors
  useEffect(() => {
    if (voiceState === "error") {
      const errorMessage: Message = {
        id: Date.now().toString(),
        text: "Voice command failed. Please try again.",
        sender: "error",
        errorType: "voice",
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMessage])
    }
  }, [voiceState])
  
  // Handle field validation errors
  useEffect(() => {
    if (fieldErrors && Object.keys(fieldErrors).length > 0) {
      // Get the most recent error
      const errorKeys = Object.keys(fieldErrors)
      const latestErrorKey = errorKeys[errorKeys.length - 1]
      const errorText = fieldErrors[latestErrorKey]
      
      const errorMessage: Message = {
        id: Date.now().toString(),
        text: `Validation error: ${errorText}`,
        sender: "error",
        errorType: "validation",
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMessage])
    }
  }, [fieldErrors])

  const handleSendMessage = async () => {
    if (!inputText.trim()) return

    const userMessage: Message = {
      id: Date.now().toString(),
      text: inputText.trim(),
      sender: "user",
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMessage])
    setInputText("")

    // Send message via WebSocket if available
    if (sendMessage) {
      sendMessage({
        source: "chat_view",
        type: "text_message",
        payload: {
          text: userMessage.text
        }
      })
    }
  }

  const handleClearChat = () => {
    // Clear local messages
    setMessages([])
    // Clear conversation history on backend
    clearChat()
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  return (
    <AnimatePresence>
      {isActive && (
        <>
          {/* Backdrop with glass effect and 3D perspective */}
          <motion.div
            className="fixed inset-0 z-[200]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            onClick={onClose}
            style={{ perspective: "1000px" }}
          >
            <div 
              className="absolute inset-0 bg-black/20 backdrop-blur-sm"
              style={{
                background: 'linear-gradient(135deg, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0.3) 100%)',
                backdropFilter: 'blur(12px)'
              }}
            />
          </motion.div>

          {/* Chat Container with 3D Tilt */}
          <motion.div
            className="fixed inset-x-4 bottom-4 z-[250] max-w-md mx-auto"
            initial={{ y: 100, opacity: 0, rotateX: 15, scale: 0.9 }}
            animate={{ y: 0, opacity: 1, rotateX: 10, scale: 1 }}
            exit={{ y: 100, opacity: 0, rotateX: 15, scale: 0.9 }}
            transition={{ 
              type: "spring", 
              stiffness: 300, 
              damping: 30,
              delay: 0.1 
            }}
            style={{ 
              transformStyle: "preserve-3d",
              transform: "perspective(1000px) rotateX(5deg) rotateY(0deg)"
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Constrain size to float within widget frame */}
            <div className="max-h-[70vh] bg-black/30 backdrop-blur-lg border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
              {/* Header */}
              <div 
                className="flex items-center justify-between p-4 border-b" 
                style={{ borderColor: `${glowColor}20` }}
              >
                <div className="flex items-center space-x-3">
                  <div 
                    className="w-2 h-2 rounded-full animate-pulse" 
                    style={{ backgroundColor: glowColor }}
                  />
                  <span 
                    className="font-medium" 
                    style={{ color: fontColor, opacity: 0.9 }}
                  >
                    IRIS Assistant
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  {messages.length > 0 && (
                    <button
                      onClick={handleClearChat}
                      className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                      style={{ color: fontColor, opacity: 0.6 }}
                      onMouseEnter={(e) => e.currentTarget.style.opacity = '0.9'}
                      onMouseLeave={(e) => e.currentTarget.style.opacity = '0.6'}
                      title="Clear Chat"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                  <button
                    onClick={() => setShowDashboard(!showDashboard)}
                    className="p-2 rounded-lg hover:bg-white/10 transition-colors flex items-center space-x-1"
                    style={{ color: fontColor, opacity: 0.6 }}
                    onMouseEnter={(e) => e.currentTarget.style.opacity = '0.9'}
                    onMouseLeave={(e) => e.currentTarget.style.opacity = '0.6'}
                    title={showDashboard ? "Hide Dashboard" : "Show Dashboard"}
                  >
                    <BarChart3 size={16} />
                    <ChevronDown size={12} className={`transition-transform ${showDashboard ? 'rotate-180' : ''}`} />
                  </button>
                  <button
                    onClick={onClose}
                    className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                    style={{ color: fontColor, opacity: 0.6 }}
                    onMouseEnter={(e) => e.currentTarget.style.opacity = '0.9'}
                    onMouseLeave={(e) => e.currentTarget.style.opacity = '0.6'}
                  >
                    <X size={16} />
                  </button>
                </div>
              </div>

              {/* Dashboard Integration */}
              <AnimatePresence>
                {showDashboard && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3, ease: "easeInOut" }}
                    className="overflow-hidden"
                    style={{ borderBottom: `1px solid ${glowColor}20` }}
                  >
                    <div className="p-4 bg-white/5">
                      <DarkGlassDashboard 
                        fieldValues={fieldValues} 
                        updateField={updateField}
                      />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Messages Area - Conditional */}
              {(messages.length > 0 || isTyping) && (
                <div className="h-80 overflow-y-auto p-4 space-y-4">
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      <motion.div
                        initial={{ opacity: 0, y: 10, scale: 0.9 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{ duration: 0.2 }}
                        className={`max-w-xs px-4 py-2 rounded-2xl ${
                          message.sender === 'user'
                            ? 'text-white'
                            : message.sender === 'error'
                            ? 'border'
                            : 'border'
                        }`}
                        style={{
                          backgroundColor: message.sender === 'user' 
                            ? `${primaryColor}cc` 
                            : message.sender === 'error'
                            ? 'rgba(239, 68, 68, 0.2)'
                            : 'rgba(255, 255, 255, 0.1)',
                          borderColor: message.sender === 'error' 
                            ? 'rgba(239, 68, 68, 0.5)' 
                            : 'rgba(255, 255, 255, 0.2)',
                          color: message.sender === 'error' ? '#fca5a5' : fontColor,
                        }}
                      >
                        {message.sender === 'error' && (
                          <div className="flex items-center space-x-2 mb-1">
                            <AlertCircle size={14} className="text-red-400" />
                            <span className="text-xs font-semibold text-red-400">
                              {message.errorType === 'voice' ? 'Voice Error' : 
                               message.errorType === 'validation' ? 'Validation Error' : 
                               'Error'}
                            </span>
                          </div>
                        )}
                        {message.sender === 'assistant' && (
                          <div className="flex items-center space-x-2 mb-1">
                            <span className="text-xs font-semibold" style={{ color: glowColor }}>
                              IRIS
                            </span>
                          </div>
                        )}
                        <p className="text-sm">{message.text}</p>
                        <p 
                          className="text-xs mt-1"
                          style={{ 
                            color: message.sender === 'user' ? 'rgba(255, 255, 255, 0.7)' : 'rgba(255, 255, 255, 0.5)' 
                          }}
                        >
                          {message.timestamp.toLocaleTimeString()}
                        </p>
                      </motion.div>
                    </div>
                  ))}

                  {isTyping && (
                    <div className="flex justify-start">
                      <motion.div
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        className="border rounded-2xl px-4 py-2"
                        style={{
                          backgroundColor: 'rgba(255, 255, 255, 0.1)',
                          borderColor: 'rgba(255, 255, 255, 0.2)',
                          color: fontColor,
                        }}
                      >
                        <div className="flex items-center space-x-2 mb-1">
                          <span className="text-xs font-semibold" style={{ color: glowColor }}>
                            IRIS is typing...
                          </span>
                        </div>
                        <div className="flex space-x-1">
                          <div 
                            className="w-2 h-2 rounded-full animate-bounce" 
                            style={{ backgroundColor: `${glowColor}99` }}
                          />
                          <div 
                            className="w-2 h-2 rounded-full animate-bounce" 
                            style={{ backgroundColor: `${glowColor}99`, animationDelay: '0.1s' }}
                          />
                          <div 
                            className="w-2 h-2 rounded-full animate-bounce" 
                            style={{ backgroundColor: `${glowColor}99`, animationDelay: '0.2s' }}
                          />
                        </div>
                      </motion.div>
                    </div>
                  )}

                  <div ref={messagesEndRef} />
                </div>
              )}

              {/* Empty State - Conditional */}
              {messages.length === 0 && !isTyping && (
                <div 
                  className="h-80 flex items-center justify-center p-4"
                  style={{ color: `${fontColor}80` }}
                >
                  <p className="text-center">
                    Start a conversation with IRIS
                    <br />
                    <span className="text-sm">How can I help you today?</span>
                  </p>
                </div>
              )}

              {/* Input Area */}
              <div 
                className="p-4 border-t"
                style={{ borderColor: `${glowColor}20` }}
              >
                <div className="flex items-center space-x-3">
                  <input
                    ref={inputRef}
                    type="text"
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Type your message..."
                    className="flex-1 bg-white/5 border rounded-xl px-4 py-3 focus:outline-none focus:ring-2 transition-all"
                    style={{
                      borderColor: `${glowColor}20`,
                      color: fontColor,
                      caretColor: glowColor,
                    }}
                  />
                  <button
                    onClick={handleSendMessage}
                    disabled={!inputText.trim() || isTyping}
                    className="p-3 text-white rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{
                      backgroundColor: `${primaryColor}cc`,
                    }}
                    onMouseEnter={(e) => !e.currentTarget.disabled && (e.currentTarget.style.backgroundColor = primaryColor)}
                    onMouseLeave={(e) => !e.currentTarget.disabled && (e.currentTarget.style.backgroundColor = `${primaryColor}cc`)}
                  >
                    <Send size={18} />
                  </button>
                </div>
              </div>
            </div>
          </motion.div>

          
        </>
      )}
    </AnimatePresence>
  )
}

export default ChatView