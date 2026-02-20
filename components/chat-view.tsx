"use client"

import React, { useState, useEffect, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Send } from 'lucide-react';
import { X } from 'lucide-react';
import { Settings } from 'lucide-react';
import { BarChart3, ChevronUp, ChevronDown } from 'lucide-react';
import { DarkGlassDashboard } from './dark-glass-dashboard';


interface Message {
  id: string
  text: string
  sender: "user" | "assistant"
  timestamp: Date
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
  const [isTyping, setIsTyping] = useState(false)
  const [showDashboard, setShowDashboard] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-focus input when chat becomes active
  useEffect(() => {
    if (isActive && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [isActive])

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

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
    setIsTyping(true)

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

    // Simulate AI response (replace with actual WebSocket response)
    setTimeout(() => {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        text: "I understand your message. How can I assist you further?",
        sender: "assistant",
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, assistantMessage])
      setIsTyping(false)
    }, 1500)
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
              <div className="flex items-center justify-between p-4 border-b border-white/10">
                <div className="flex items-center space-x-3">
                  <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                  <span className="text-white/90 font-medium">IRIS Assistant</span>
                </div>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => setShowDashboard(!showDashboard)}
                    className="p-2 rounded-lg hover:bg-white/10 transition-colors text-white/60 hover:text-white/90 flex items-center space-x-1"
                    title={showDashboard ? "Hide Dashboard" : "Show Dashboard"}
                  >
                    <BarChart3 size={16} />
                    <ChevronDown size={12} className={`transition-transform ${showDashboard ? 'rotate-180' : ''}`} />
                  </button>
                  <button
                    onClick={onClose}
                    className="p-2 rounded-lg hover:bg-white/10 transition-colors text-white/60 hover:text-white/90"
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
                    className="overflow-hidden border-b border-white/10"
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
                            ? 'bg-blue-500/80 text-white'
                            : 'bg-white/10 text-white/90 border border-white/20'
                        }`}
                      >
                        <p className="text-sm">{message.text}</p>
                        <p className={`text-xs mt-1 ${
                          message.sender === 'user' ? 'text-white/70' : 'text-white/50'
                        }`}>
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
                        className="bg-white/10 text-white/90 border border-white/20 rounded-2xl px-4 py-2"
                      >
                        <div className="flex space-x-1">
                          <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" />
                          <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                          <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                        </div>
                      </motion.div>
                    </div>
                  )}

                  <div ref={messagesEndRef} />
                </div>
              )}

              {/* Empty State - Conditional */}
              {messages.length === 0 && !isTyping && (
                <div className="h-80 flex items-center justify-center p-4 text-white/50">
                  <p className="text-center">
                    Start a conversation with IRIS
                    <br />
                    <span className="text-sm">How can I help you today?</span>
                  </p>
                </div>
              )}

              {/* Input Area */}
              <div className="p-4 border-t border-white/10">
                <div className="flex items-center space-x-3">
                  <input
                    ref={inputRef}
                    type="text"
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Type your message..."
                    className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white/90 placeholder-white/40 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/30 transition-all"
                  />
                  <button
                    onClick={handleSendMessage}
                    disabled={!inputText.trim() || isTyping}
                    className="p-3 bg-blue-500/80 hover:bg-blue-500 text-white rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed"
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