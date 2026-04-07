"use client"

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Send, X, BarChart3, Plus, Trash2, AlertCircle, Bell, AlertTriangle, Shield, Loader, CheckCircle, Info, History, Pin, Copy, ThumbsUp, ThumbsDown, Volume2, ChevronDown, ChevronUp, Download, Share, FileText, Mail, Video, Image, File, Smile, ExternalLink } from 'lucide-react';
import { useNavigation } from "@/contexts/NavigationContext";
import { useBrandColor } from "@/contexts/BrandColorContext";
import { SendMessageFunction } from "@/hooks/useIRISWebSocket";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { IrisApertureIcon } from "@/components/ui/IrisApertureIcon";
import { SpotlightState, SpotlightStateType } from "@/hooks/useUILayoutState";
import { useLauncherMode } from "@/hooks/useLauncherMode";
import { ConversationChips } from "@/components/chat/ConversationChips";
import type { ConversationChip } from "@/types/iris";

// Notification types for the universal notification system
interface Notification {
  id: string;
  type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  progress?: number;
}

// Content type definitions for smart message handling
export type ContentType = 'markdown' | 'email' | 'video' | 'picture' | 'text';

const MESSAGE_THRESHOLDS = {
  TRUNCATE_AT: 500,            // plain text expand/collapse threshold
  DOCUMENT_MODE_AT: 400,       // artifact card threshold for media/email/file uploads
  MARKDOWN_ARTIFACT_AT: 800,   // artifact card threshold for long markdown from assistant
  WARNING_AT: 3000
} as const;

const ContentTypePatterns = {
  video: /(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov)/i,
  picture: /\.(jpg|jpeg|png|gif|webp|svg|bmp)(?:\?.*)?$/i,
  markdown: /(?:^#{1,6}\s|\*\*|__|\[.+?\]\(.+?\)|```)/m,
  email: /(?:^From:|^To:|^Subject:|\S+@\S+\.\S+)/m
};

// Heuristic: does this message look like a web-research / search query?
// If yes, route to crawler_query WS type instead of text_message.
const CRAWLER_PATTERNS = [
  /\b(search|look up|find|google|bing|lookup)\b/i,
  /\b(latest|current|recent|today'?s?|right now|as of)\b/i,
  /\b(news|headlines|article|report|prices?|stock|weather)\b/i,
  /\b(what('?s| is) (the )?(price|cost|rate|score|status|news))\b/i,
  /\b(show me|get me|fetch|retrieve|pull up)\b/i,
]

function isCrawlerQuery(text: string): boolean {
  const t = text.trim()
  if (t.length < 10) return false
  return CRAWLER_PATTERNS.some(re => re.test(t))
}

const ContentTypeLabels: Record<ContentType, string> = {
  markdown: 'Markdown Document',
  email: 'Email',
  video: 'Video',
  picture: 'Image',
  text: 'Text Document'
};

// Helper functions for notification styling
const getNotificationColor = (type: string, glowColor: string): string => {
  switch (type) {
    case 'alert': return '#fbbf24'; // amber
    case 'permission': return '#3b82f6'; // blue
    case 'error': return '#ef4444'; // red
    case 'task': return '#a855f7'; // purple
    case 'completion': return '#22c55e'; // green
    default: return glowColor;
  }
};

const getNotificationIcon = (type: string, glowColor: string) => {
  const iconProps = { size: 10, style: { color: getNotificationColor(type, glowColor) } };
  switch (type) {
    case 'alert': return <AlertTriangle {...iconProps} />;
    case 'permission': return <Shield {...iconProps} />;
    case 'error': return <AlertCircle {...iconProps} />;
    case 'task': return <Loader {...iconProps} className="animate-spin" />;
    case 'completion': return <CheckCircle {...iconProps} />;
    default: return <Info {...iconProps} />;
  }
};

interface Message {
  id: string
  text: string
  sender: "user" | "assistant" | "error"
  timestamp: Date
  errorType?: "agent" | "voice" | "validation"
  words?: string[]; // For TTS word highlighting
  // NOTE: currentWordIndex is NOT stored in message state — it lives in ttsWordIndex
  // component state to avoid re-serialising all conversations on every 200 ms tick.
  feedback?: 'positive' | 'negative' | null; // User feedback on AI responses
  thinking?: string; // Chain-of-thought from the model, shown in a collapsible block
}

// Thread-based conversation structure
interface Conversation {
  id: string;
  title: string;
  preview: string;
  messages: Message[];
  timestamp: Date;
  isPinned: boolean;
  lastMessagePreview: string;
}

interface ChatWingProps {
  isOpen: boolean
  onClose: () => void
  onDashboardClick: () => void
  onDashboardClose?: () => void
  sendMessage?: SendMessageFunction
  fieldValues?: Record<string, any>
  updateField?: (sectionId: string, fieldId: string, value: any) => void
  // Spotlight Mode props
  spotlightState?: SpotlightStateType
  onSpotlightToggle?: () => void
  isDashboardOpen?: boolean
  // Browser passthrough — called when user clicks a URL in chat
  onOpenBrowserUrl?: (url: string) => void
}

export function ChatWing({
  isOpen,
  onClose,
  onDashboardClick,
  onDashboardClose,
  sendMessage,
  fieldValues,
  updateField,
  spotlightState = SpotlightState.BALANCED,
  onSpotlightToggle,
  isDashboardOpen = false,
  onOpenBrowserUrl,
}: ChatWingProps) {
  const prefersReducedMotion = useReducedMotion();
  
  // Thread-based conversation state — persisted to localStorage so history
  // survives page reloads and Tauri window closes.
  // Max 50 conversations kept; messages within each conversation capped at 200.
  const STORAGE_KEY = "iris_conversations_v1"
  const ACTIVE_ID_KEY = "iris_active_conversation_id_v1"
  const MAX_CONVERSATIONS = 50
  const MAX_MESSAGES_PER_CONV = 200

  const [conversations, setConversations] = useState<Conversation[]>(() => {
    if (typeof window === "undefined") return []
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return []
      const parsed: Conversation[] = JSON.parse(raw)
      // Deserialise timestamp strings back to Date objects
      return parsed.map(c => ({
        ...c,
        timestamp: new Date(c.timestamp),
        messages: c.messages.map(m => ({ ...m, timestamp: new Date(m.timestamp) })),
      }))
    } catch {
      return []
    }
  })
  const [activeConversationId, setActiveConversationId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null
    return localStorage.getItem(ACTIVE_ID_KEY) || null
  })

  // Persist conversations with a 1 s debounce — avoids hammering localStorage on every
  // fast state change (typing, streaming, etc.).  isSpeaking is excluded from the debounce
  // because the TTS interval no longer mutates conversations anyway.
  useEffect(() => {
    if (typeof window === "undefined") return
    const id = setTimeout(() => {
      try {
        const toStore = conversations.slice(-MAX_CONVERSATIONS).map(c => ({
          ...c,
          messages: c.messages.slice(-MAX_MESSAGES_PER_CONV),
        }))
        localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore))
      } catch {
        // localStorage full or unavailable — silently skip
      }
    }, 1000);
    return () => clearTimeout(id);
  }, [conversations])

  // Persist active conversation ID
  useEffect(() => {
    if (typeof window === "undefined") return
    if (activeConversationId) {
      localStorage.setItem(ACTIVE_ID_KEY, activeConversationId)
    } else {
      localStorage.removeItem(ACTIVE_ID_KEY)
    }
  }, [activeConversationId])
  const [inputText, setInputText] = useState("")
  const [justSent, setJustSent] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const lastProcessedResponseRef = useRef<typeof lastTextResponse>(null)
  const activeConversationIdRef = useRef<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const chatPanelRef = useRef<HTMLDivElement>(null)
  const { lastTextResponse, voiceState, isChatTyping, clearChat, activeTheme, fieldErrors, audioLevel } = useNavigation();
  
  // Notification system state
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  
  // TTS state
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [currentTtsMessageId, setCurrentTtsMessageId] = useState<string | null>(null);
  // Word index lives here, NOT inside Message/Conversations, so the 200 ms tick
  // updates a single number rather than remapping all conversations + localStorage.
  const [ttsWordIndex, setTtsWordIndex] = useState(-1);
  
  // Copy feedback state
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  
  // Smart message length handling state
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  // Thinking block expand/collapse — collapsed by default
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(new Set());
  const [documentModalMessage, setDocumentModalMessage] = useState<Message | null>(null);
  const [messageContentTypes, setMessageContentTypes] = useState<Record<string, ContentType>>({});
  
  // File upload drag-and-drop state
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [draggedFileType, setDraggedFileType] = useState<'image' | 'video' | 'file' | null>(null);
  
  // Conversation chips — input focus state (chips slide away on focus)
  const { isDeveloper } = useLauncherMode()
  const [isInputFocused, setIsInputFocused] = useState(false)

  // Derive isTyping: use isChatTyping for text messages (won't animate the orb),
  // and voiceState for voice pipeline processing/tool states.
  const isTyping = isChatTyping || voiceState === "processing_tool";

  // Get theme colors from BrandColorContext for real-time updates
  const { getThemeConfig } = useBrandColor();
  const brandTheme = getThemeConfig();
  const glowColor = brandTheme.glow.color || "#00d4ff";
  const primaryColor = brandTheme.glow.color || "#00d4ff";
  const fontColor = brandTheme.text.primary || "#ffffff";

  // Get active conversation messages
  const activeConversation = conversations.find(c => c.id === activeConversationId);
  const messages = activeConversation?.messages || [];

  // Conversation chips — derived from user messages, front-end only, no LLM
  const conversationChips: ConversationChip[] = useMemo(() => (
    messages
      .filter(m => m.sender === 'user')
      .map((m, index) => ({
        messageId: m.id,
        label: m.text.length > 24 ? m.text.slice(0, 24) + '\u2026' : m.text,
        index,
      }))
  ), [messages])

  const handleChipClick = useCallback((messageId: string) => {
    const el = document.getElementById(`msg-${messageId}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('chip-highlight')
    setTimeout(() => el.classList.remove('chip-highlight'), 2000)
  }, [])

  // Calculate unread count when notifications change
  useEffect(() => {
    setUnreadCount(notifications.filter(n => !n.read).length);
  }, [notifications]);

  // Mark all as read when notification panel opens
  useEffect(() => {
    if (showNotifications) {
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    }
  }, [showNotifications]);

  // Auto-focus input when chat becomes open
  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [isOpen])

  // Keep ref in sync with activeConversationId state
  useEffect(() => {
    activeConversationIdRef.current = activeConversationId
  }, [activeConversationId])

  // Scroll to bottom when messages change — use container scroll to avoid
  // scrollIntoView propagating up the DOM tree and shifting the Tauri frame
  useEffect(() => {
    const el = messagesContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  // Handle incoming WebSocket messages from the navigation context.
  // Uses refs instead of state deps to prevent double-processing when
  // activeConversationId updates cause the effect to re-run.
  useEffect(() => {
    if (!lastTextResponse) return
    // Deduplicate: skip if this exact response object was already processed
    if (lastTextResponse === lastProcessedResponseRef.current) return
    lastProcessedResponseRef.current = lastTextResponse

    const isUserVoice = lastTextResponse.sender === "user"

    // User voice transcriptions show as user bubbles (no TTS — server handles audio)
    // Assistant responses show as assistant bubbles (client-side TTS highlighting)
    const newMessage: Message = {
      id: (Date.now() + 1).toString(),
      text: lastTextResponse.text,
      sender: lastTextResponse.sender,
      timestamp: new Date(),
      words: isUserVoice ? undefined : lastTextResponse.text.split(' '),
      feedback: isUserVoice ? undefined : null,
      thinking: lastTextResponse.thinking || undefined,
    }

    // Read active ID from ref (not closure) to avoid stale-closure double-trigger
    const currentActiveId = activeConversationIdRef.current

    if (currentActiveId) {
      // Add to existing conversation
      setConversations(prev => prev.map(conv =>
        conv.id === currentActiveId
          ? {
              ...conv,
              messages: [...conv.messages, newMessage],
              lastMessagePreview: newMessage.text.substring(0, 60),
              timestamp: new Date()
            }
          : conv
      ))
    } else {
      // Create new conversation — set active ID BEFORE setConversations to
      // ensure the ref is current when the state update lands
      const newId = Date.now().toString()
      activeConversationIdRef.current = newId
      setActiveConversationId(newId)
      setConversations(prev => {
        const newConv: Conversation = {
          id: newId,
          title: `Conversation ${prev.length + 1}`,
          preview: newMessage.text.substring(0, 60),
          messages: [newMessage],
          timestamp: new Date(),
          isPinned: false,
          lastMessagePreview: newMessage.text.substring(0, 60)
        }
        return [...prev, newConv]
      })
    }

    // Only trigger client-side TTS word-highlight for assistant messages.
    // Voice responses: TTS audio is played server-side via TTSManager.
    if (!isUserVoice) {
      setCurrentTtsMessageId(newMessage.id)
      setIsSpeaking(true)
    }
  }, [lastTextResponse, isOpen])
  
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
      
      if (activeConversationId) {
        setConversations(prev => prev.map(conv => 
          conv.id === activeConversationId
            ? { ...conv, messages: [...conv.messages, errorMessage] }
            : conv
        ));
      }
    }
  }, [voiceState, activeConversationId])
  
  // Handle field validation errors
  useEffect(() => {
    if (fieldErrors && Object.keys(fieldErrors).length > 0) {
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
      
      if (activeConversationId) {
        setConversations(prev => prev.map(conv => 
          conv.id === activeConversationId
            ? { ...conv, messages: [...conv.messages, errorMessage] }
            : conv
        ));
      }
    }
  }, [fieldErrors, activeConversationId])

  // Handle TTS word highlighting simulation (fallback when backend doesn't provide tts_word events).
  // PERF: word index lives in ttsWordIndex state — a single number — so each 200 ms tick does
  // NOT remap all conversations or trigger a localStorage write.  messages is NOT in deps;
  // we snapshot the words array into a ref when speaking starts to avoid re-creating the
  // interval on every message change.
  useEffect(() => {
    if (!isSpeaking || !currentTtsMessageId) {
      setTtsWordIndex(-1);
      return;
    }
    const message = messages.find((m: Message) => m.id === currentTtsMessageId);
    if (!message?.words?.length) return;

    const words = message.words; // stable snapshot — won't change while speaking
    setTtsWordIndex(0);
    let wordIndex = 0;
    const interval = setInterval(() => {
      wordIndex++;
      if (wordIndex >= words.length) {
        setIsSpeaking(false);
        setTtsWordIndex(-1);
        clearInterval(interval);
        return;
      }
      setTtsWordIndex(wordIndex);
    }, 200);

    return () => {
      clearInterval(interval);
      setTtsWordIndex(-1);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSpeaking, currentTtsMessageId]); // intentionally omit `messages` — words are snapshotted above

  // Reset speaking state when voice changes to idle
  useEffect(() => {
    if (voiceState === 'idle' && isSpeaking) {
      setIsSpeaking(false);
    }
  }, [voiceState, isSpeaking]);

  const handleSendMessage = async () => {
    if (!inputText.trim()) return

    const userMessage: Message = {
      id: Date.now().toString(),
      text: inputText.trim(),
      sender: "user",
      timestamp: new Date(),
    }

    setInputText("")
    setJustSent(true);
    setTimeout(() => setJustSent(false), 300);

    // Add to active conversation or create new one
    setConversations(prev => {
      if (activeConversationId) {
        // Add to existing conversation
        return prev.map(conv => 
          conv.id === activeConversationId
            ? {
                ...conv,
                messages: [...conv.messages, userMessage],
                lastMessagePreview: userMessage.text.substring(0, 60),
                timestamp: new Date()
              }
            : conv
        );
      } else {
        // Create new conversation
        const newConv: Conversation = {
          id: Date.now().toString(),
          title: `Conversation ${prev.length + 1}`,
          preview: userMessage.text.substring(0, 60),
          messages: [userMessage],
          timestamp: new Date(),
          isPinned: false,
          lastMessagePreview: userMessage.text.substring(0, 60)
        };
        setActiveConversationId(newConv.id);
        return [...prev, newConv];
      }
    });

    // Route to crawler if the query looks like a web-research request
    const msgType = isCrawlerQuery(userMessage.text) ? "crawler_query" : "text_message"
    const payload = msgType === "crawler_query"
      ? { query: userMessage.text }
      : { text: userMessage.text }
    sendMessage?.(msgType, payload)
  }

  // Conversation management functions
  const handleSelectConversation = (conversationId: string) => {
    setActiveConversationId(conversationId);
    setShowHistory(false);
  };

  const handleDeleteConversation = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation();
    setConversations(prev => prev.filter(c => c.id !== conversationId));
    if (activeConversationId === conversationId) {
      const remaining = conversations.filter(c => c.id !== conversationId);
      setActiveConversationId(remaining.length > 0 ? remaining[0].id : null);
    }
  };

  const handlePinConversation = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation();
    setConversations(prev => {
      const updated = prev.map(c => 
        c.id === conversationId ? { ...c, isPinned: !c.isPinned } : c
      );
      // Sort: pinned first, then by timestamp
      return updated.sort((a, b) => {
        if (a.isPinned && !b.isPinned) return -1;
        if (!a.isPinned && b.isPinned) return 1;
        return b.timestamp.getTime() - a.timestamp.getTime();
      });
    });
  };

  const handleNewConversation = () => {
    // Create new conversation thread
    const newConv: Conversation = {
      id: `conv_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      title: `Conversation ${conversations.length + 1}`,
      preview: 'New conversation',
      messages: [],
      timestamp: new Date(),
      isPinned: false,
      lastMessagePreview: 'New conversation'
    };
    
    setConversations(prev => [newConv, ...prev]);
    setActiveConversationId(newConv.id);
    setInputText('');
    
    // Close any open dropdowns
    closeDropdowns();
    
    // Focus input field
    setTimeout(() => inputRef.current?.focus(), 100);
    
    // Notify backend of new conversation
    sendMessage?.('new_conversation', { 
      conversation_id: newConv.id,
      timestamp: newConv.timestamp.toISOString()
    });
  };

  // Feedback action handlers
  const handleCopyMessage = async (text: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(messageId);
      setTimeout(() => setCopiedMessageId(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const handleFeedback = (messageId: string, feedback: 'positive' | 'negative') => {
    if (!activeConversationId) return;
    
    setConversations(prev => prev.map(conv => 
      conv.id === activeConversationId
        ? {
            ...conv,
            messages: conv.messages.map(msg => 
              msg.id === messageId ? { ...msg, feedback } : msg
            )
          }
        : conv
    ));
    
    // Send feedback to backend
    sendMessage?.('message_feedback', { message_id: messageId, feedback });
  };

  const handlePlayTTS = (text: string) => {
    sendMessage?.('tts_play', { text });
  };

  // Smart message length handling helpers
  const detectContentType = useCallback((text: string): ContentType => {
    if (ContentTypePatterns.video.test(text)) return 'video';
    if (ContentTypePatterns.picture.test(text)) return 'picture';
    if (ContentTypePatterns.markdown.test(text)) return 'markdown';
    if (ContentTypePatterns.email.test(text)) return 'email';
    return 'text';
  }, []);

  const getContentType = useCallback((message: Message): ContentType => {
    if (!messageContentTypes[message.id]) {
      const detected = detectContentType(message.text);
      setMessageContentTypes(prev => ({ ...prev, [message.id]: detected }));
      return detected;
    }
    return messageContentTypes[message.id];
  }, [messageContentTypes, detectContentType]);

  const toggleMessageExpanded = useCallback((messageId: string) => {
    setExpandedMessages(prev => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }, []);

  const isMessageExpanded = useCallback((messageId: string) => {
    return expandedMessages.has(messageId);
  }, [expandedMessages]);

  const handleDownloadMessage = useCallback((message: Message) => {
    const contentType = getContentType(message);
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `IRIS_${contentType}_${timestamp}.txt`;
    
    const content = `========================================
IRIS ${ContentTypeLabels[contentType]} Export
Exported: ${new Date().toLocaleString()}
========================================

${message.text}`;
    
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    // Notify backend
    sendMessage?.('message_exported', { 
      message_id: message.id,
      content_type: contentType 
    });
  }, [getContentType, sendMessage]);

  const handleShareMessage = useCallback(async (message: Message) => {
    try {
      await navigator.clipboard.writeText(message.text);
      // Show notification
      const notif: Notification = {
        id: Date.now().toString(),
        type: 'completion',
        title: 'Copied to clipboard',
        message: 'Message content has been copied',
        timestamp: new Date(),
        read: false
      };
      setNotifications(prev => [notif, ...prev]);
    } catch (err) {
      console.error('Failed to share:', err);
    }
  }, []);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  // File upload handlers
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (!isDraggingFile) {
      setIsDraggingFile(true);
      
      // Detect file type from drag data
      const items = e.dataTransfer.items;
      if (items && items.length > 0) {
        const item = items[0];
        if (item.type.startsWith('image/')) {
          setDraggedFileType('image');
        } else if (item.type.startsWith('video/')) {
          setDraggedFileType('video');
        } else {
          setDraggedFileType('file');
        }
      }
    }
  }, [isDraggingFile]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    // Only clear if leaving the container (not entering a child)
    if (e.currentTarget === e.target) {
      setIsDraggingFile(false);
      setDraggedFileType(null);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingFile(false);
    setDraggedFileType(null);
    
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      const file = files[0];
      handleFileUpload(file);
    }
  }, []);

  const handleFileUpload = useCallback((file: File) => {
    // Create a message about the uploaded file
    const fileType = file.type.startsWith('image/') ? 'image' :
                     file.type.startsWith('video/') ? 'video' : 'file';
    
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      
      // Send file content or metadata based on type
      if (fileType === 'image' || fileType === 'video') {
        // For media, just send metadata and a reference
        const message = `[${fileType.toUpperCase()}: ${file.name} (${(file.size / 1024).toFixed(1)} KB)]`;
        setInputText(message);
      } else {
        // For text files, send the content (truncated if needed)
        const textContent = content.slice(0, 1000);
        const truncated = content.length > 1000 ? '... (truncated)' : '';
        setInputText(`[File: ${file.name}]\n\n${textContent}${truncated}`);
      }
    };
    
    if (fileType === 'image' || fileType === 'video') {
      reader.readAsDataURL(file);
    } else {
      reader.readAsText(file);
    }
    
    // Show notification
    const notif: Notification = {
      id: Date.now().toString(),
      type: 'completion',
      title: 'File ready',
      message: `${file.name} loaded. Press Enter to send.`,
      timestamp: new Date(),
      read: false
    };
    setNotifications(prev => [notif, ...prev]);
  }, []);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
    // Reset input
    e.target.value = '';
  }, []);

  // Keyboard navigation - Escape to close
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        // Close document modal first if open
        if (documentModalMessage) {
          setDocumentModalMessage(null);
          return;
        }
        // Close any open dropdowns next
        if (showNotifications || showHistory) {
          closeDropdowns();
          return;
        }
        // Finally close chat
        onClose();
      }
    };
    
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [isOpen, showNotifications, showHistory, onClose, documentModalMessage]);

  // Dropdown exclusivity handlers
  const openNotifications = () => {
    setShowNotifications(true);
    setShowHistory(false);
  };

  const openHistory = () => {
    setShowHistory(true);
    setShowNotifications(false);
  };

  const closeDropdowns = () => {
    setShowNotifications(false);
    setShowHistory(false);
  };

  // Render message text with clickable URL links
  const renderWithLinks = (text: string) => {
    const urlRegex = /https?:\/\/[^\s<>"')\]]+/g;
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = urlRegex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.slice(lastIndex, match.index));
      }
      const url = match[0];
      parts.push(
        <span
          key={match.index}
          onClick={() => onOpenBrowserUrl?.(url)}
          className="underline cursor-pointer transition-opacity hover:opacity-70"
          style={{ color: glowColor }}
          title={`Open in browser: ${url}`}
        >
          {url}
        </span>
      );
      lastIndex = match.index + url.length;
    }
    if (lastIndex < text.length) {
      parts.push(text.slice(lastIndex));
    }
    return parts.length > 1 ? <>{parts}</> : text;
  };

  // Permission response handlers
  const handlePermissionGrant = (notificationId: string) => {
    sendMessage?.('notification_response', { 
      notification_id: notificationId, 
      action: 'grant' 
    });
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
  };

  const handlePermissionDeny = (notificationId: string) => {
    sendMessage?.('notification_response', { 
      notification_id: notificationId, 
      action: 'deny' 
    });
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
  };

  // Global error state (derived from voiceState)
  const globalError = voiceState === 'error';

  // Spotlight Mode derived states
  const isInChatSpotlight = spotlightState === SpotlightState.CHAT_SPOTLIGHT;
  const isInDashboardSpotlight = spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT;
  const isBalanced = spotlightState === SpotlightState.BALANCED;

  // Spotlight dynamic styles
  const getSpotlightWidth = () => {
    if (isInChatSpotlight) return 680; // Spotlight width (2×)
    if (isInDashboardSpotlight) return 360; // Background width (2×)
    return 510; // Balanced width (2×)
  };

  const getSpotlightTransform = () => {
    if (isInChatSpotlight) return 'translateY(-50%) rotateY(0deg) rotateX(0deg)';
    if (isInDashboardSpotlight) return 'translateY(-50%) rotateY(15deg) rotateX(2deg)';
    return 'translateY(-50%) rotateY(15deg) rotateX(2deg)';
  };

  const getSpotlightOpacity = () => {
    if (isInDashboardSpotlight) return 0.3;
    return 1.0;
  };

  const getSpotlightFilter = () => {
    if (isInDashboardSpotlight) return 'saturate(0.6) blur(2px)';
    return 'none';
  };

  const getSpotlightZIndex = () => {
    if (isInChatSpotlight) return 20;
    if (isInDashboardSpotlight) return 5;
    return 10;
  };

  const getSpotlightPointerEvents = () => {
    if (isInDashboardSpotlight) return 'none';
    return 'auto';
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed"
          initial={{ x: -120, opacity: 0, scale: 0.95 }}
          animate={{ 
            x: 0, 
            opacity: getSpotlightOpacity(), 
            scale: 1 
          }}
          exit={{ x: -120, opacity: 0, scale: 0.95 }}
          transition={{ 
            type: "spring", 
            stiffness: 280, 
            damping: 25,
            mass: 0.8
          }}
          style={{ 
            left: 252,
            top: '50%',
            width: getSpotlightWidth(),
            height: '88vh',
            perspective: '800px',
            zIndex: getSpotlightZIndex(),
            filter: getSpotlightFilter(),
            pointerEvents: getSpotlightPointerEvents() as any,
          }}
        >
          {/* HUD Glass Panel Container */}
          <motion.div
            ref={chatPanelRef}
            className="h-full overflow-hidden flex flex-col relative"
            animate={{
              transform: getSpotlightTransform()
            }}
            transition={{
              type: "spring",
              stiffness: 280,
              damping: 25,
              mass: 0.8
            }}
            style={{
              transformOrigin: 'left center',
              transformStyle: 'preserve-3d',
              background: 'linear-gradient(135deg, rgba(10,10,20,0.95) 0%, rgba(5,5,10,0.98) 100%)',
              boxShadow: `
                inset 0 1px 1px rgba(255,255,255,0.05),
                inset 0 -1px 1px rgba(0,0,0,0.5),
                0 0 0 1px rgba(0,0,0,0.8),
                20px 0 60px rgba(0,0,0,0.5)
              `,
              borderRadius: '12px',
              border: `1px solid ${glowColor}20`,
            }}
          >
            {/* HUD Effects Overlay */}
            <div 
              className="absolute inset-0 pointer-events-none z-10"
              style={{
                background: `
                  linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.02) 50%, transparent 100%),
                  repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0,0,0,0.03) 2px,
                    rgba(0,0,0,0.03) 4px
                  )
                `,
                backgroundSize: '100% 100%, 100% 4px',
              }}
            />
            
            {/* Edge Fresnel Effect */}
            <div 
              className="absolute inset-0 pointer-events-none z-20"
              style={{
                background: `
                  linear-gradient(90deg, ${glowColor}08 0%, transparent 15%, transparent 85%, ${glowColor}08 100%),
                  linear-gradient(0deg, ${glowColor}05 0%, transparent 20%, transparent 80%, ${glowColor}05 100%)
                `,
                borderRadius: '12px',
              }}
            />

            {/* 48px Header */}
            <div 
              className="h-12 px-3 flex items-center flex-shrink-0 border-b relative z-30"
              style={{ borderColor: `${glowColor}15`, position: 'relative' }}
            >
              {/* Global error line */}
              {globalError && (
                <motion.div
                  className="absolute top-0 left-0 right-0 h-[1px] z-40"
                  style={{ background: 'rgba(239,68,68,0.8)' }}
                  animate={{ opacity: [1, 0.3, 1] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}
              
              {/* Left section: Pulse + Title + Dashboard */}
              <div className="flex items-center gap-2 flex-1">
                <motion.div
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: glowColor }}
                  animate={{
                    scale: voiceState === 'listening' ? [1, 1.4, 1] : 1,
                    opacity: voiceState === 'listening' ? [1, 0.6, 1] : 1
                  }}
                  transition={{ duration: 1.2, repeat: Infinity }}
                />
                <span
                  className="text-[13px] font-semibold tracking-wide"
                  style={{ color: fontColor, opacity: 0.9 }}
                >
                  IRIS
                </span>
                {/* Dashboard - positioned next to IRIS text - toggles open/close */}
                <button
                  onClick={() => {
                    if (isDashboardOpen && onDashboardClose) {
                      onDashboardClose();
                    } else {
                      onDashboardClick();
                    }
                    closeDropdowns();
                  }}
                  className="p-1.5 rounded-lg transition-all duration-150"
                  style={{ 
                    color: isDashboardOpen ? glowColor : `${fontColor}60`,
                    backgroundColor: isDashboardOpen ? `${glowColor}15` : 'transparent'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = glowColor;
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = isDashboardOpen ? glowColor : `${fontColor}60`;
                    e.currentTarget.style.backgroundColor = isDashboardOpen ? `${glowColor}15` : 'transparent';
                  }}
                  title={isDashboardOpen ? "Close Dashboard" : "Open Dashboard"}
                >
                  <BarChart3 size={14} />
                </button>
              </div>

              {/* Center section: Spotlight Iris Aperture Button - positioned at top edge */}
              <div className="flex items-start justify-center absolute left-1/2 -translate-x-1/2" style={{ top: '-16px' }}>
                {onSpotlightToggle && (
                  <button
                    onClick={() => {
                      onSpotlightToggle();
                      closeDropdowns();
                    }}
                    className="p-3 rounded-full transition-all duration-150 border shadow-lg"
                    style={{ 
                      color: isInChatSpotlight ? glowColor : `${fontColor}60`,
                      backgroundColor: isInChatSpotlight ? `${glowColor}20` : 'rgba(10,10,20,0.95)',
                      borderColor: `${glowColor}30`,
                      boxShadow: `0 -2px 10px rgba(0,0,0,0.5), 0 0 20px ${isInChatSpotlight ? glowColor : 'transparent'}40`,
                      backdropFilter: 'blur(10px)'
                    }}
                    onMouseEnter={(e) => {
                      if (!isInChatSpotlight) e.currentTarget.style.color = `${fontColor}90`;
                      e.currentTarget.style.backgroundColor = 'rgba(20,20,35,0.98)';
                      e.currentTarget.style.borderColor = `${glowColor}60`;
                    }}
                    onMouseLeave={(e) => {
                      if (!isInChatSpotlight) e.currentTarget.style.color = `${fontColor}60`;
                      e.currentTarget.style.backgroundColor = isInChatSpotlight ? `${glowColor}20` : 'rgba(10,10,20,0.95)';
                      e.currentTarget.style.borderColor = `${glowColor}30`;
                    }}
                    title={isInChatSpotlight ? "Restore balanced view" : "Maximize chat"}
                  >
                    <IrisApertureIcon 
                      isActive={isInChatSpotlight} 
                      glowColor={glowColor} 
                      fontColor={fontColor}
                      size={20}
                    />
                  </button>
                )}
              </div>
              
              {/* Right section: Notifications + History + Close */}
              <div className="flex items-center gap-0.5 flex-1 justify-end">
                {/* Notifications */}
                <button
                  onClick={() => showNotifications ? closeDropdowns() : openNotifications()}
                  className="p-2 rounded-lg transition-all duration-150 relative"
                  style={{ 
                    color: showNotifications ? glowColor : unreadCount > 0 ? glowColor : `${fontColor}60`,
                    backgroundColor: showNotifications ? `${glowColor}15` : 'transparent'
                  }}
                  onMouseEnter={(e) => {
                    if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : `${fontColor}90`;
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : `${fontColor}60`;
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title="Notifications"
                >
                  <Bell size={16} />
                  {unreadCount > 0 && (
                    <motion.span
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      className="absolute top-1 right-1 w-2 h-2 rounded-full"
                      style={{ backgroundColor: glowColor }}
                    />
                  )}
                </button>
                
                {/* History */}
                <button
                  onClick={() => showHistory ? closeDropdowns() : openHistory()}
                  className="p-2 rounded-lg transition-all duration-150"
                  style={{ 
                    color: showHistory ? glowColor : `${fontColor}60`,
                    backgroundColor: showHistory ? `${glowColor}15` : 'transparent'
                  }}
                  onMouseEnter={(e) => {
                    if (!showHistory) e.currentTarget.style.color = `${fontColor}90`;
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    if (!showHistory) e.currentTarget.style.color = `${fontColor}60`;
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title="Conversation History"
                >
                  <History size={16} />
                </button>
                
                {/* Close */}
                <button
                  onClick={() => {
                    onClose();
                    closeDropdowns();
                  }}
                  className="p-2 rounded-lg transition-all duration-150"
                  style={{ color: `${fontColor}60` }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = `${fontColor}90`;
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = `${fontColor}60`;
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title="Close Chat"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Notification Dropdown Panel */}
            <AnimatePresence>
              {showNotifications && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                  className="overflow-hidden border-b flex-shrink-0 z-20"
                  style={{ 
                    borderColor: `${glowColor}10`,
                    background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
                    backdropFilter: 'blur(20px)',
                    maxHeight: '50%'
                  }}
                >
                  <div className="p-3 space-y-2 overflow-y-auto">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-semibold tracking-widest uppercase text-white/50">
                        Notifications
                      </span>
                      {notifications.length > 0 && (
                        <button
                          onClick={() => setNotifications([])}
                          className="text-[9px] px-2 py-1 rounded transition-colors text-white/40 hover:text-white/70 hover:bg-white/5"
                        >
                          Clear all
                        </button>
                      )}
                    </div>
                    
                    {notifications.length === 0 ? (
                      <div className="text-center py-6 text-[11px] text-white/40">
                        No notifications
                      </div>
                    ) : (
                      notifications.map((notif) => (
                        <motion.div
                          key={notif.id}
                          initial={{ x: unreadCount > 0 && !notif.read ? -10 : 0, opacity: 0 }}
                          animate={{ x: 0, opacity: 1 }}
                          className="p-2.5 rounded-lg transition-all duration-150 group relative overflow-hidden"
                          style={{
                            backgroundColor: !notif.read ? `${glowColor}08` : 'rgba(255,255,255,0.03)',
                            borderLeft: `2px solid ${getNotificationColor(notif.type, glowColor)}`
                          }}
                        >
                          {/* Type indicator glow */}
                          <div 
                            className="absolute top-0 right-0 w-16 h-16 opacity-10 blur-xl rounded-full -translate-y-1/2 translate-x-1/2"
                            style={{ backgroundColor: getNotificationColor(notif.type, glowColor) }}
                          />
                          
                          <div className="flex items-start justify-between relative">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-1">
                                {getNotificationIcon(notif.type, glowColor)}
                                <span 
                                  className="text-[9px] font-semibold tracking-wide uppercase"
                                  style={{ color: getNotificationColor(notif.type, glowColor) }}
                                >
                                  {notif.type}
                                </span>
                                <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                                  {notif.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                </span>
                              </div>
                              <p className="text-[11px] font-medium text-white/90 leading-snug">
                                {notif.title}
                              </p>
                              <p className="text-[10px] text-white/60 mt-0.5 line-clamp-2">
                                {notif.message}
                              </p>
                            </div>
                          </div>
                          
                          {/* Action buttons based on type */}
                          {notif.type === 'permission' && (
                            <div className="flex gap-2 mt-2">
                              <button
                                onClick={() => handlePermissionGrant(notif.id)}
                                className="flex-1 py-1 rounded text-[9px] font-medium transition-colors"
                                style={{ 
                                  background: `${glowColor}20`,
                                  color: glowColor
                                }}
                              >
                                Allow
                              </button>
                              <button
                                onClick={() => handlePermissionDeny(notif.id)}
                                className="flex-1 py-1 rounded text-[9px] font-medium transition-colors bg-white/10 text-white/70 hover:bg-white/15"
                              >
                                Deny
                              </button>
                            </div>
                          )}
                          
                          {notif.type === 'task' && (
                            <div className="mt-2">
                              <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                                <motion.div 
                                  className="h-full rounded-full"
                                  style={{ backgroundColor: glowColor }}
                                  initial={{ width: 0 }}
                                  animate={{ width: `${notif.progress || 0}%` }}
                                />
                              </div>
                              <span className="text-[8px] text-white/40 mt-1 block">
                                {notif.progress || 0}% complete
                              </span>
                            </div>
                          )}
                        </motion.div>
                      ))
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* History Dropdown Panel - Thread-Based */}
            <AnimatePresence>
              {showHistory && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: prefersReducedMotion ? 0 : 0.2, ease: [0.22, 1, 0.36, 1] }}
                  className="overflow-hidden border-b flex-shrink-0 z-20"
                  style={{ 
                    borderColor: `${glowColor}10`,
                    background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
                    backdropFilter: 'blur(20px)',
                    maxHeight: '50%'
                  }}
                >
                  <div className="p-3 space-y-2 overflow-y-auto">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-semibold tracking-widest uppercase text-white/50">
                        Conversation Threads
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] text-white/30">
                          {conversations.length} total
                        </span>
                        <button
                          onClick={handleNewConversation}
                          className="p-1.5 rounded transition-all duration-150 flex items-center gap-1"
                          style={{ color: `${fontColor}50` }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = glowColor;
                            e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = `${fontColor}50`;
                            e.currentTarget.style.backgroundColor = 'transparent';
                          }}
                          title="Start new conversation"
                          aria-label="New conversation"
                        >
                          <Plus size={12} />
                        </button>
                      </div>
                    </div>
                    
                    {conversations.length === 0 ? (
                      <div className="text-center py-6 text-[11px] text-white/40">
                        No conversations yet
                      </div>
                    ) : (
                      conversations.map((conv) => (
                        <motion.div
                          key={conv.id}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          onClick={() => handleSelectConversation(conv.id)}
                          className="group relative p-2.5 rounded-lg cursor-pointer transition-all duration-150 hover:bg-white/5"
                          style={{
                            backgroundColor: activeConversationId === conv.id ? `${glowColor}15` : 'rgba(255,255,255,0.03)',
                            borderLeft: `2px solid ${activeConversationId === conv.id ? glowColor : 'transparent'}`
                          }}
                        >
                          <div className="flex items-center gap-2">
                            {/* Content */}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-1">
                                {conv.isPinned && (
                                  <Pin size={10} style={{ color: glowColor }} className="fill-current flex-shrink-0" />
                                )}
                                <span className="text-[10px] font-medium text-white/90 truncate">
                                  {conv.title}
                                </span>
                                <span className="text-[8px] text-white/30 tabular-nums flex-shrink-0">
                                  {conv.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                </span>
                              </div>
                              <p className="text-[9px] text-white/50 truncate leading-snug">
                                {conv.lastMessagePreview}
                                {conv.lastMessagePreview.length >= 60 ? '...' : ''}
                              </p>
                              <span className="text-[8px] text-white/30 mt-1 block">
                                {conv.messages.length} message{conv.messages.length !== 1 ? 's' : ''}
                              </span>
                            </div>
                            
                            {/* Action buttons - centered on right */}
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 self-center">
                              <button
                                onClick={(e) => handlePinConversation(e, conv.id)}
                                className="p-1.5 rounded transition-colors hover:bg-white/10"
                                style={{ color: conv.isPinned ? glowColor : 'rgba(255,255,255,0.5)' }}
                                title={conv.isPinned ? 'Unpin' : 'Pin to top'}
                              >
                                <Pin size={12} className={conv.isPinned ? 'fill-current' : ''} />
                              </button>
                              <button
                                onClick={(e) => handleDeleteConversation(e, conv.id)}
                                className="p-1.5 rounded transition-colors hover:bg-white/10 text-white/50 hover:text-red-400"
                                title="Delete conversation"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          </div>
                        </motion.div>
                      ))
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Messages Area - Thread-Based with Separators */}
            <div ref={messagesContainerRef} className="flex-1 overflow-y-auto px-3 py-3 relative z-10">
              {messages.length === 0 && !isTyping ? (
                <div 
                  className="flex-1 flex items-center justify-center h-full"
                  style={{ color: `${fontColor}50` }}
                >
                  <p className="text-center text-[11px]">
                    {conversations.length === 0 ? (
                      <>
                        Start a conversation
                        <br />
                        <span className="text-[10px] opacity-70">How can I help you today?</span>
                      </>
                    ) : (
                      <>
                        Select a conversation
                        <br />
                        <span className="text-[10px] opacity-70">or start a new one</span>
                      </>
                    )}
                  </p>
                </div>
              ) : (
                <div className="space-y-0">
                  {messages.map((message, index) => {
                    // Smart message length handling
                    const charCount = message.text.length;
                    const contentType = getContentType(message);
                    const isExpanded = isMessageExpanded(message.id);
                    const shouldTruncate = charCount > MESSAGE_THRESHOLDS.TRUNCATE_AT;
                    // Artifact card rules:
                    //   - Media, email, explicit file uploads → artifact at DOCUMENT_MODE_AT (400 chars)
                    //   - Long markdown from assistant (code blocks, headers) → artifact at MARKDOWN_ARTIFACT_AT (800 chars)
                    //     This keeps voice-first UX clean: the full response is always readable,
                    //     but the chat thread stays concise — tap to expand if needed.
                    //   - Plain conversational text → always flows as chat (truncate/expand only)
                    const isExplicitFile = message.text.startsWith('[File:') || message.text.startsWith('[IMAGE:') || message.text.startsWith('[VIDEO:');
                    const isAssistantMarkdown = message.sender === 'assistant' && contentType === 'markdown' && charCount > MESSAGE_THRESHOLDS.MARKDOWN_ARTIFACT_AT;
                    const isDocumentMode = (isExplicitFile || contentType === 'email' || contentType === 'picture' || contentType === 'video' || isAssistantMarkdown) && charCount > MESSAGE_THRESHOLDS.DOCUMENT_MODE_AT;
                    
                    // Content type icon mapping
                    const ContentTypeIcon = ({ size = 12 }: { size?: number }) => {
                      const style = { color: glowColor };
                      switch (contentType) {
                        case 'markdown': return <FileText size={size} style={style} />;
                        case 'email': return <Mail size={size} style={style} />;
                        case 'video': return <Video size={size} style={style} />;
                        case 'picture': return <Image size={size} style={style} />;
                        default: return <File size={size} style={style} />;
                      }
                    };
                    
                    return (
                    <div key={message.id} id={`msg-${message.id}`}>
                      {/* Horizontal separator */}
                      {index > 0 && (
                        <div 
                          className="h-px w-full my-3"
                          style={{ backgroundColor: `${glowColor}10` }}
                        />
                      )}
                      
                      <div
                        className={`flex justify-start`}
                      >
                        {message.sender === 'user' ? (
                          // User message - no bubble container
                          <motion.div
                            initial={{ opacity: prefersReducedMotion ? 1 : 0, y: prefersReducedMotion ? 0 : 5 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
                            className="max-w-[90%] py-2"
                          >
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[9px] font-medium text-white/40">You</span>
                              <span className="text-[8px] text-white/30 tabular-nums">
                                {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                              </span>
                            </div>
                            
                            {/* Smart message length handling for user messages */}
                            {isDocumentMode ? (
                              // Document mode for long messages
                              <div className="mt-1">
                                <p className="text-[13px] leading-relaxed text-white/85 line-clamp-3">
                                  {message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT)}...
                                </p>
                                <p className="text-[9px] text-white/40 mt-1">
                                  {charCount.toLocaleString()} characters
                                </p>
                                <div className="flex gap-2 mt-3">
                                  <button
                                    onClick={() => setDocumentModalMessage(message)}
                                    className="flex-1 py-1.5 px-3 rounded text-[10px] font-medium transition-all"
                                    style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
                                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}30`; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}20`; }}
                                  >
                                    View full document
                                  </button>
                                  {onOpenBrowserUrl && (
                                    <button
                                      onClick={() => {
                                        const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:system-ui,sans-serif;padding:2rem;max-width:800px;margin:0 auto;line-height:1.6;white-space:pre-wrap;word-break:break-word}</style></head><body>${message.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</body></html>`;
                                        onOpenBrowserUrl(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
                                      }}
                                      className="p-1.5 rounded transition-colors"
                                      style={{ color: `${fontColor}60` }}
                                      onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                      onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                      title="Open in browser tab"
                                    >
                                      <ExternalLink size={14} />
                                    </button>
                                  )}
                                  <button
                                    onClick={() => handleShareMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Share"
                                  >
                                    <Share size={14} />
                                  </button>
                                  <button
                                    onClick={() => handleDownloadMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Download"
                                  >
                                    <Download size={14} />
                                  </button>
                                </div>
                              </div>
                            ) : shouldTruncate ? (
                              // Truncated message with expand option
                              <div className="mt-1">
                                <div className="flex items-center gap-1 mb-1">
                                  <ContentTypeIcon size={12} />
                                  <span className="text-[9px] text-white/50 uppercase tracking-wide">{contentType}</span>
                                </div>
                                <div className="relative">
                                  <p className="text-[13px] leading-relaxed text-white/90">
                                    {isExpanded ? message.text : message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT) + '...'}
                                  </p>
                                  {!isExpanded && (
                                    <div 
                                      className="absolute bottom-0 left-0 right-0 h-6 pointer-events-none"
                                      style={{ background: 'linear-gradient(to bottom, transparent, rgba(10,10,20,0.95))' }}
                                    />
                                  )}
                                </div>
                                <button
                                  onClick={() => toggleMessageExpanded(message.id)}
                                  className="mt-1 flex items-center gap-1 text-[10px] font-medium transition-colors"
                                  style={{ color: glowColor }}
                                  aria-expanded={isExpanded}
                                >
                                  {isExpanded ? (
                                    <>Show less <ChevronUp size={12} /></>
                                  ) : (
                                    <>Show more <ChevronDown size={12} /></>
                                  )}
                                </button>
                                {isExpanded && (
                                  <div className="flex gap-2 mt-2 pt-2 border-t border-white/10">
                                    <button
                                      onClick={() => handleShareMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Share"
                                    >
                                      <Share size={14} />
                                    </button>
                                    <button
                                      onClick={() => handleDownloadMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Download"
                                    >
                                      <Download size={14} />
                                    </button>
                                  </div>
                                )}
                              </div>
                            ) : (
                              // Short message - display fully
                              <p className="text-[13px] leading-relaxed text-white/90">{renderWithLinks(message.text)}</p>
                            )}
                          </motion.div>
                        ) : message.sender === 'assistant' ? (
                          // AI message - no bubble container with feedback bar
                          <motion.div
                            initial={{ opacity: prefersReducedMotion ? 1 : 0, y: prefersReducedMotion ? 0 : 5 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
                            className="max-w-[90%] py-2"
                          >
                            <div className="flex items-center gap-2 mb-1.5">
                              <span 
                                className="text-[9px] font-semibold tracking-wide"
                                style={{ color: glowColor }}
                              >
                                IRIS
                              </span>
                              {isSpeaking && message.id === currentTtsMessageId && (
                                <span className="text-[8px] text-white/40 flex items-center gap-0.5">
                                  <span className="w-0.5 h-0.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '0ms' }} />
                                  <span className="w-0.5 h-0.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '150ms' }} />
                                  <span className="w-0.5 h-0.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '300ms' }} />
                                </span>
                              )}
                              <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                                {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                              </span>
                            </div>
                            
                            {/* Collapsible thinking block — only shown when model produced reasoning */}
                            {message.thinking && (
                              <div className="mb-2">
                                <button
                                  onClick={() => setExpandedThinking(prev => {
                                    const next = new Set(prev);
                                    next.has(message.id) ? next.delete(message.id) : next.add(message.id);
                                    return next;
                                  })}
                                  className="flex items-center gap-1.5 text-[9px] font-medium tracking-wide uppercase transition-colors"
                                  style={{ color: 'rgba(255,255,255,0.3)' }}
                                  aria-expanded={expandedThinking.has(message.id)}
                                >
                                  {expandedThinking.has(message.id)
                                    ? <><ChevronUp size={10} /> Hide thinking</>
                                    : <><ChevronDown size={10} /> Show thinking</>}
                                </button>
                                <AnimatePresence>
                                  {expandedThinking.has(message.id) && (
                                    <motion.div
                                      initial={{ height: 0, opacity: 0 }}
                                      animate={{ height: 'auto', opacity: 1 }}
                                      exit={{ height: 0, opacity: 0 }}
                                      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                                      className="overflow-hidden"
                                    >
                                      <div
                                        className="mt-1.5 p-2.5 rounded text-[11px] leading-relaxed whitespace-pre-wrap font-mono"
                                        style={{
                                          color: 'rgba(255,255,255,0.35)',
                                          background: 'rgba(255,255,255,0.03)',
                                          borderLeft: '2px solid rgba(255,255,255,0.08)',
                                        }}
                                      >
                                        {message.thinking}
                                      </div>
                                    </motion.div>
                                  )}
                                </AnimatePresence>
                              </div>
                            )}

                            {/* Message content with smart length handling and TTS highlighting */}
                            {isDocumentMode ? (
                              // Document mode for long messages
                              <div className="mt-1">
                                <p className="text-[13px] leading-relaxed text-white/85 line-clamp-3">
                                  {message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT)}...
                                </p>
                                <p className="text-[9px] text-white/40 mt-1">
                                  {charCount.toLocaleString()} characters
                                </p>
                                <div className="flex gap-2 mt-3">
                                  <button
                                    onClick={() => setDocumentModalMessage(message)}
                                    className="flex-1 py-1.5 px-3 rounded text-[10px] font-medium transition-all"
                                    style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
                                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}30`; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}20`; }}
                                  >
                                    View full document
                                  </button>
                                  {onOpenBrowserUrl && (
                                    <button
                                      onClick={() => {
                                        const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:system-ui,sans-serif;padding:2rem;max-width:800px;margin:0 auto;line-height:1.6;white-space:pre-wrap;word-break:break-word}</style></head><body>${message.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</body></html>`;
                                        onOpenBrowserUrl(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
                                      }}
                                      className="p-1.5 rounded transition-colors"
                                      style={{ color: `${fontColor}60` }}
                                      onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                      onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                      title="Open in browser tab"
                                    >
                                      <ExternalLink size={14} />
                                    </button>
                                  )}
                                  <button
                                    onClick={() => handleShareMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Share"
                                  >
                                    <Share size={14} />
                                  </button>
                                  <button
                                    onClick={() => handleDownloadMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Download"
                                  >
                                    <Download size={14} />
                                  </button>
                                </div>
                              </div>
                            ) : shouldTruncate ? (
                              // Truncated message with expand option
                              <div className="mt-1">
                                <div className="flex items-center gap-1 mb-1">
                                  <ContentTypeIcon size={12} />
                                  <span className="text-[9px] text-white/50 uppercase tracking-wide">{contentType}</span>
                                </div>
                                <div className="relative">
                                  <div className="text-[13px] leading-relaxed text-white/85 prose prose-invert prose-sm max-w-none">
                                    {isExpanded ? (
                                      message.words ? message.words.map((word, idx) => {
                                        const activeIdx = message.id === currentTtsMessageId ? ttsWordIndex : -1;
                                        return (
                                        <motion.span
                                          key={idx}
                                          initial={idx === activeIdx ? { opacity: 0.5 } : false}
                                          animate={{
                                            opacity: idx === activeIdx ? 1 : idx < activeIdx ? 0.7 : 0.85,
                                            color: idx === activeIdx ? glowColor : 'rgba(255,255,255,0.85)',
                                          }}
                                          transition={{ duration: prefersReducedMotion ? 0 : 0.1 }}
                                        >
                                          {word}{' '}
                                        </motion.span>
                                        );
                                      }) : message.text
                                    ) : (
                                      message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT) + '...'
                                    )}
                                  </div>
                                  {!isExpanded && (
                                    <div 
                                      className="absolute bottom-0 left-0 right-0 h-6 pointer-events-none"
                                      style={{ background: 'linear-gradient(to bottom, transparent, rgba(10,10,20,0.95))' }}
                                    />
                                  )}
                                </div>
                                <button
                                  onClick={() => toggleMessageExpanded(message.id)}
                                  className="mt-1 flex items-center gap-1 text-[10px] font-medium transition-colors"
                                  style={{ color: glowColor }}
                                  aria-expanded={isExpanded}
                                >
                                  {isExpanded ? (
                                    <>Show less <ChevronUp size={12} /></>
                                  ) : (
                                    <>Show more <ChevronDown size={12} /></>
                                  )}
                                </button>
                                {isExpanded && (
                                  <div className="flex gap-2 mt-2 pt-2 border-t border-white/10">
                                    <button
                                      onClick={() => handleShareMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Share"
                                    >
                                      <Share size={14} />
                                    </button>
                                    <button
                                      onClick={() => handleDownloadMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Download"
                                    >
                                      <Download size={14} />
                                    </button>
                                  </div>
                                )}
                              </div>
                            ) : (
                              // Short message - display fully with TTS highlighting
                              <div className="text-[13px] leading-relaxed text-white/85 prose prose-invert prose-sm max-w-none">
                                {message.words ? message.words.map((word, idx) => {
                                  const activeIdx = message.id === currentTtsMessageId ? ttsWordIndex : -1;
                                  return (
                                  <motion.span
                                    key={idx}
                                    initial={idx === activeIdx ? { opacity: 0.5 } : false}
                                    animate={{
                                      opacity: idx === activeIdx ? 1 : idx < activeIdx ? 0.7 : 0.85,
                                      color: idx === activeIdx ? glowColor : 'rgba(255,255,255,0.85)',
                                    }}
                                    transition={{ duration: prefersReducedMotion ? 0 : 0.1 }}
                                  >
                                    {word}{' '}
                                  </motion.span>
                                  );
                                }) : renderWithLinks(message.text)}
                              </div>
                            )}
                            
                            {/* Feedback action bar */}
                            <div className="flex items-center gap-2 mt-2 pt-2 border-t border-white/5">
                              <button
                                onClick={() => handleCopyMessage(message.text, message.id)}
                                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] transition-colors hover:bg-white/5 text-white/40 hover:text-white/70"
                                title="Copy to clipboard"
                              >
                                <Copy size={12} />
                                {copiedMessageId === message.id ? 'Copied!' : 'Copy'}
                              </button>
                              
                              <button
                                onClick={() => handlePlayTTS(message.text)}
                                className="p-1.5 rounded transition-colors hover:bg-white/5 text-white/40 hover:text-white/70"
                                title="Play text-to-speech"
                              >
                                <Volume2 size={12} />
                              </button>
                              
                              <div className="flex items-center gap-1 ml-auto">
                                <button
                                  onClick={() => handleFeedback(message.id, 'positive')}
                                  className={`p-1.5 rounded transition-colors ${
                                    message.feedback === 'positive' 
                                      ? 'text-green-400 bg-green-400/10' 
                                      : 'text-white/40 hover:text-white/70 hover:bg-white/5'
                                  }`}
                                  title="Helpful response"
                                >
                                  <ThumbsUp size={12} className={message.feedback === 'positive' ? 'fill-current' : ''} />
                                </button>
                                <button
                                  onClick={() => handleFeedback(message.id, 'negative')}
                                  className={`p-1.5 rounded transition-colors ${
                                    message.feedback === 'negative' 
                                      ? 'text-red-400 bg-red-400/10' 
                                      : 'text-white/40 hover:text-white/70 hover:bg-white/5'
                                  }`}
                                  title="Not helpful"
                                >
                                  <ThumbsDown size={12} className={message.feedback === 'negative' ? 'fill-current' : ''} />
                                </button>
                              </div>
                            </div>
                          </motion.div>
                        ) : (
                          // Error message
                          <motion.div
                            initial={{ opacity: prefersReducedMotion ? 1 : 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
                            className="max-w-[90%] py-2"
                          >
                            <div className="flex items-center gap-1.5 mb-1">
                              <AlertCircle size={10} className="text-red-400" />
                              <span className="text-[9px] font-semibold text-red-400">
                                {message.errorType === 'voice' ? 'Voice Error' : 
                                 message.errorType === 'validation' ? 'Validation' : 'Error'}
                              </span>
                              <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                                {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                              </span>
                            </div>
                            <p className="text-[12px] text-red-200/90 leading-relaxed">{message.text}</p>
                          </motion.div>
                        )}
                      </div>
                    </div>
                  );
                })}

                  {/* Typing Indicator */}
                  {isTyping && (
                    <div>
                      <div 
                        className="h-px w-full my-3"
                        style={{ backgroundColor: `${glowColor}10` }}
                      />
                      <div className="flex justify-start">
                        <motion.div
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className="py-2"
                        >
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="text-[9px] font-semibold" style={{ color: glowColor }}>
                              IRIS
                            </span>
                            <span className="text-[8px] text-white/40">thinking...</span>
                          </div>
                          <div className="flex gap-1">
                            <motion.div 
                              className="w-1 h-1 rounded-full"
                              style={{ backgroundColor: glowColor }}
                              animate={prefersReducedMotion ? {} : { opacity: [0.3, 1, 0.3] }}
                              transition={{ duration: 1, repeat: Infinity }}
                            />
                            <motion.div 
                              className="w-1 h-1 rounded-full"
                              style={{ backgroundColor: glowColor }}
                              animate={prefersReducedMotion ? {} : { opacity: [0.3, 1, 0.3] }}
                              transition={{ duration: 1, repeat: Infinity, delay: 0.2 }}
                            />
                            <motion.div 
                              className="w-1 h-1 rounded-full"
                              style={{ backgroundColor: glowColor }}
                              animate={prefersReducedMotion ? {} : { opacity: [0.3, 1, 0.3] }}
                              transition={{ duration: 1, repeat: Infinity, delay: 0.4 }}
                            />
                          </div>
                        </motion.div>
                      </div>
                    </div>
                  )}

                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>

            {/* Document View Modal */}
            <AnimatePresence>
              {documentModalMessage && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
                  className="absolute inset-0 z-50 flex flex-col"
                  style={{ 
                    background: 'linear-gradient(135deg, rgba(10,10,20,0.99) 0%, rgba(5,5,10,0.98) 100%)'
                  }}
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="document-modal-title"
                >
                  <motion.div
                    initial={{ scale: 0.98, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.98, opacity: 0 }}
                    transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
                    className="w-full h-full flex flex-col overflow-hidden"
                  >
                    {/* Modal header - compact */}
                    <div 
                      className="px-2 py-1.5 flex items-center justify-between border-b flex-shrink-0"
                      style={{ borderColor: `${glowColor}20` }}
                    >
                      <div className="flex items-center gap-1.5" id="document-modal-title">
                        {(() => {
                          const type = getContentType(documentModalMessage);
                          const Icon = type === 'markdown' ? FileText :
                                      type === 'email' ? Mail :
                                      type === 'video' ? Video :
                                      type === 'picture' ? Image : File;
                          return <Icon size={10} style={{ color: glowColor }} />;
                        })()}
                        <span className="text-[10px] font-medium" style={{ color: fontColor }}>
                          {ContentTypeLabels[getContentType(documentModalMessage)]}
                        </span>
                        <span className="text-[8px] text-white/40">
                          ({documentModalMessage.text.length.toLocaleString()})
                        </span>
                      </div>
                      <button
                        onClick={() => setDocumentModalMessage(null)}
                        className="p-1 rounded transition-all"
                        style={{ color: `${fontColor}60` }}
                        onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; }}
                        onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; }}
                        aria-label="Close"
                      >
                        <X size={12} />
                      </button>
                    </div>
                    
                    {/* Modal content - compact */}
                    <div 
                      className="p-2 overflow-y-auto flex-1"
                    >
                      <pre 
                        className="text-[10px] leading-snug whitespace-pre-wrap font-mono"
                        style={{ color: 'rgba(255,255,255,0.85)' }}
                      >
                        {documentModalMessage.text}
                      </pre>
                    </div>
                    
                    {/* Modal action bar - compact */}
                    <div 
                      className="px-2 py-1.5 flex gap-1.5 border-t flex-shrink-0"
                      style={{ borderColor: `${glowColor}20` }}
                    >
                      <button
                        onClick={() => handleDownloadMessage(documentModalMessage)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors"
                        style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}30`; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}20`; }}
                      >
                        <Download size={10} />
                        Save
                      </button>
                      <button
                        onClick={() => handleShareMessage(documentModalMessage)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors"
                        style={{ backgroundColor: 'rgba(255,255,255,0.08)', color: fontColor }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.12)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)'; }}
                      >
                        <Share size={10} />
                        Share
                      </button>
                      <button
                        onClick={() => handleCopyMessage(documentModalMessage.text, documentModalMessage.id)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors"
                        style={{ backgroundColor: 'rgba(255,255,255,0.08)', color: fontColor }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.12)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)'; }}
                      >
                        <Copy size={10} />
                        {copiedMessageId === documentModalMessage.id ? '✓' : 'Copy'}
                      </button>
                      
                      {/* Close button */}
                      <button
                        onClick={() => setDocumentModalMessage(null)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors ml-auto"
                        style={{ color: `${fontColor}70` }}
                        onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; }}
                        onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}70`; }}
                      >
                        <X size={10} />
                      </button>
                    </div>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Input Area - Command Line Style with Drag & Drop */}
            <div
              className="px-3 pb-3 pt-4 flex-shrink-0 relative z-30 bg-black/60 border-t"
              style={{ borderColor: 'rgba(255,255,255,0.05)' }}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              {/* Drag overlay with smile/file icon */}
              <AnimatePresence>
                {isDraggingFile && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="absolute bottom-12 left-3 flex items-center gap-1.5 pointer-events-none z-40"
                  >
                    {draggedFileType === 'image' ? (
                      <Image size={14} style={{ color: glowColor }} />
                    ) : draggedFileType === 'video' ? (
                      <Video size={14} style={{ color: glowColor }} />
                    ) : (
                      <Smile size={14} style={{ color: glowColor }} />
                    )}
                    <span className="text-[10px]" style={{ color: fontColor }}>
                      Drop file here
                    </span>
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="relative flex items-end gap-6" style={{ marginRight: '12px' }}>
                <div className="flex-1 relative">
                  <textarea
                    ref={inputRef as any}
                    value={inputText}
                    onChange={(e) => {
                      setInputText(e.target.value);
                      // Auto-expand height
                      e.target.style.height = 'auto';
                      e.target.style.height = `${e.target.scrollHeight}px`;
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSendMessage();
                        // Reset height
                        if (inputRef.current) inputRef.current.style.height = 'auto';
                      }
                    }}
                    onFocus={() => setIsInputFocused(true)}
                    onBlur={() => setIsInputFocused(false)}
                    placeholder={voiceState === 'listening' ? 'Listening...' : 'Type command or drop file...'}
                    disabled={voiceState === 'listening'}
                    className="w-full bg-transparent border-0 border-b py-2 pr-2 text-[13px] focus:outline-none transition-all placeholder:text-white/30 disabled:opacity-50 resize-none min-h-[36px] max-h-[120px] scrollbar-hide"
                    rows={1}
                    style={{
                      borderColor: isDraggingFile ? glowColor : inputText ? glowColor : `${glowColor}30`,
                      color: fontColor,
                      borderBottomWidth: '1px',
                      boxShadow: isDraggingFile ? `0 0 8px ${glowColor}40` : inputText ? `0 1px 0 0 ${glowColor}` : 'none',
                    }}
                  />
                  
                  {/* Voice indicator */}
                  {voiceState === 'listening' && (
                    <motion.div 
                      className="absolute left-0 bottom-0 h-[1px]"
                      style={{ backgroundColor: glowColor }}
                      animate={{ width: [`${audioLevel * 100}%`, `${Math.min(100, audioLevel * 150)}%`] }}
                      transition={{ duration: 0.1 }}
                    />
                  )}
                </div>

                {/* Compact Action Group */}
                <div className="flex items-center gap-2 mb-2">
                  {/* Send button */}
                  <motion.button
                    onClick={handleSendMessage}
                    disabled={!inputText.trim() || isTyping || voiceState === 'listening'}
                    className="p-2 transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
                    style={{
                      color: inputText.trim() ? glowColor : `${fontColor}40`,
                    }}
                    whileHover={inputText.trim() ? { scale: 1.1 } : {}}
                    whileTap={inputText.trim() ? { scale: 0.9 } : {}}
                    title="Send message"
                  >
                    <Send size={18} />
                  </motion.button>

                  {/* Liquid Metal Divider - between buttons */}
                  <div 
                    className="w-px h-8 opacity-30"
                    style={{
                      background: `linear-gradient(to bottom, transparent, ${glowColor}, transparent)`,
                    }}
                  />
                  
                  {/* Hidden file input */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    onChange={handleFileInputChange}
                    className="hidden"
                    accept="*/*"
                  />

                  {/* Plus button for file upload */}
                  <motion.button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={voiceState === 'listening'}
                    className="p-2 transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
                    style={{
                      color: `${fontColor}60`,
                    }}
                    whileHover={{ scale: 1.1, color: fontColor }}
                    whileTap={{ scale: 0.9 }}
                    title="Upload file"
                  >
                    <Plus size={18} />
                  </motion.button>

                  {/* Conversation chips — inline with action buttons, panel opens via portal */}
                  <ConversationChips
                    chips={conversationChips}
                    glowColor={glowColor}
                    onChipClick={handleChipClick}
                    containerRef={chatPanelRef}
                  />

                </div>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// Note: Component renamed to ChatWing but file kept as chat-view.tsx to avoid breaking imports
export default ChatWing