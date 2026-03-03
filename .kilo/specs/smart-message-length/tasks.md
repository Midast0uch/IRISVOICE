# Implementation Plan: Smart Message Length Handling (Simplified)

All implementation is inline within [`chat-view.tsx`](IRISVOICE/components/chat-view.tsx:1) - no new component files.

---

## Phase 1: Content Type Detection Setup

### Task 1.1: Add Content Type Types and Constants
**What to build:** Type definitions and detection patterns
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (top of file, after imports)
**_Requirements: 2.1, 2.2, 2.3, 2.4_

**Add:**
```typescript
// Content type definitions
export type ContentType = 'markdown' | 'email' | 'video' | 'picture' | 'text';

const MESSAGE_THRESHOLDS = {
  TRUNCATE_AT: 150,
  DOCUMENT_MODE_AT: 300,
  WARNING_AT: 1000
} as const;

const ContentTypePatterns = {
  video: /(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov)/i,
  picture: /\.(jpg|jpeg|png|gif|webp|svg|bmp)(?:\?.*)?$/i,
  markdown: /(?:^#{1,6}\s|\*\*|__|\[.+?\]\(.+?\)|```)/m,
  email: /(?:^From:|^To:|^Subject:|\S+@\S+\.\S+)/m
};

const ContentTypeLabels: Record<ContentType, string> = {
  markdown: 'Markdown Document',
  email: 'Email',
  video: 'Video',
  picture: 'Image',
  text: 'Text Document'
};
```

**Test:** TypeScript compiles without errors

---

### Task 1.2: Add Icon Imports
**What to build:** Import additional icons from lucide-react
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (import statement)
**_Requirements: 2.2_

**Modify existing import:**
```typescript
// From:
import { Send, X, BarChart3, Plus, Trash2, AlertCircle, Bell, AlertTriangle, Shield, Loader, CheckCircle, Info, History, Pin, Copy, ThumbsUp, ThumbsDown, Volume2 } from 'lucide-react';

// To:
import { Send, X, BarChart3, Plus, Trash2, AlertCircle, Bell, AlertTriangle, Shield, Loader, CheckCircle, Info, History, Pin, Copy, ThumbsUp, ThumbsDown, Volume2, ChevronDown, ChevronUp, Download, Share, FileText, Mail, Video, Image, File } from 'lucide-react';
```

---

### Task 1.3: Add Content Type Detection State
**What to build:** State to cache content type per message
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (inside ChatWing component)
**_Requirements: 2.1, 2.4_

**Add state after existing useState declarations:**
```typescript
// Content type detection state
const [messageContentTypes, setMessageContentTypes] = useState<Record<string, ContentType>>({});

// Content type detection function
const detectContentType = useCallback((text: string): ContentType => {
  if (ContentTypePatterns.video.test(text)) return 'video';
  if (ContentTypePatterns.picture.test(text)) return 'picture';
  if (ContentTypePatterns.markdown.test(text)) return 'markdown';
  if (ContentTypePatterns.email.test(text)) return 'email';
  return 'text';
}, []);

// Get content type for message (with caching)
const getContentType = useCallback((message: Message): ContentType => {
  if (!messageContentTypes[message.id]) {
    const detected = detectContentType(message.text);
    setMessageContentTypes(prev => ({ ...prev, [message.id]: detected }));
    return detected;
  }
  return messageContentTypes[message.id];
}, [messageContentTypes, detectContentType]);
```

---

## Phase 2: Message Expansion State

### Task 2.1: Add Expanded Messages State
**What to build:** Track which messages are expanded
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**_Requirements: 3.1, 3.4, 3.5_

**Add state:**
```typescript
// Track expanded messages
const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());

// Toggle expansion
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

// Check if message is expanded
const isMessageExpanded = useCallback((messageId: string) => {
  return expandedMessages.has(messageId);
}, [expandedMessages]);
```

---

### Task 2.2: Add Document Modal State
**What to build:** State for document view modal
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**_Requirements: 4.2, 5.3, 5.4_

**Add state:**
```typescript
// Document modal state
const [documentModalMessage, setDocumentModalMessage] = useState<Message | null>(null);
```

---

## Phase 3: Action Handlers

### Task 3.1: Add Download Handler
**What to build:** Generate and download text file
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**_Requirements: 4.3, 6.1, 6.2_

**Add handler:**
```typescript
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
```

---

### Task 3.2: Add Share Handler
**What to build:** Copy message to clipboard
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**_Requirements: 4.4, 4.5_

**Add handler:**
```typescript
const handleShareMessage = useCallback(async (message: Message) => {
  try {
    await navigator.clipboard.writeText(message.text);
    // Show notification using existing system
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
```

---

## Phase 4: Message Rendering Updates

### Task 4.1: Create Content Type Icon Helper
**What to build:** Function to render appropriate icon
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (inside messages.map())
**_Requirements: 2.2_

**Add helper inside messages.map() before return:**
```typescript
const ContentTypeIcon = ({ type, size = 12 }: { type: ContentType; size?: number }) => {
  const style = { color: glowColor };
  switch (type) {
    case 'markdown': return <FileText size={size} style={style} />;
    case 'email': return <Mail size={size} style={style} />;
    case 'video': return <Video size={size} style={style} />;
    case 'picture': return <Image size={size} style={style} />;
    default: return <File size={size} style={style} />;
  }
};
```

---

### Task 4.2: Update Message Rendering Logic
**What to build:** Modify existing message rendering to support truncation
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (in messages.map())
**_Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2_

**Replace existing message text rendering with:**
```typescript
// Inside messages.map(), after message variable definition:
const charCount = message.text.length;
const contentType = getContentType(message);
const isExpanded = isMessageExpanded(message.id);
const shouldTruncate = charCount > MESSAGE_THRESHOLDS.TRUNCATE_AT;
const isDocumentMode = charCount > MESSAGE_THRESHOLDS.DOCUMENT_MODE_AT;

// Determine display text
const displayText = isExpanded || !shouldTruncate 
  ? message.text 
  : message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT) + '...';
```

---

### Task 4.3: Add Truncated Message UI
**What to build:** UI for 151-300 char messages
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**_Requirements: 3.1, 3.2, 3.3, 3.5, 3.6_

**Add conditional rendering for truncated messages:**
```typescript
{shouldTruncate && !isDocumentMode && (
  <div className="mt-2">
    {/* Content type indicator */}
    <div className="flex items-center gap-1 mb-1">
      <ContentTypeIcon type={contentType} size={12} />
      <span className="text-[9px] text-white/50 uppercase tracking-wide">{contentType}</span>
    </div>
    
    {/* Text with fade gradient when collapsed */}
    <div className="relative">
      <p className="text-[13px] leading-relaxed text-white/85">
        {displayText}
      </p>
      {!isExpanded && (
        <div 
          className="absolute bottom-0 left-0 right-0 h-6 pointer-events-none"
          style={{
            background: 'linear-gradient(to bottom, transparent, rgba(10,10,20,0.95))'
          }}
        />
      )}
    </div>
    
    {/* Show more/less button */}
    <button
      onClick={() => toggleMessageExpanded(message.id)}
      className="mt-1 flex items-center gap-1 text-[10px] font-medium transition-colors"
      style={{ color: glowColor }}
      aria-expanded={isExpanded}
      aria-label={isExpanded ? 'Show less' : `Show more, ${charCount} characters total`}
    >
      {isExpanded ? (
        <>Show less <ChevronUp size={12} /></>
      ) : (
        <>Show more <ChevronDown size={12} /></>
      )}
    </button>
    
    {/* Share/Download in expanded view */}
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
)}
```

---

### Task 4.4: Add Document Mode UI
**What to build:** UI for >300 char messages
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**_Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

**Add conditional rendering for document mode:**
```typescript
{isDocumentMode && (
  <div className="mt-2">
    {/* Document header */}
    <div className="flex items-center gap-2 mb-2">
      <ContentTypeIcon type={contentType} size={16} />
      <span className="text-[10px] font-medium" style={{ color: fontColor }}>
        {ContentTypeLabels[contentType]}
      </span>
      {charCount > MESSAGE_THRESHOLDS.WARNING_AT && (
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">
          Large
        </span>
      )}
    </div>
    
    {/* Preview text (truncated) */}
    <p className="text-[13px] leading-relaxed text-white/85 line-clamp-3">
      {message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT)}...
    </p>
    
    {/* Character count */}
    <p className="text-[9px] text-white/40 mt-1">
      {charCount.toLocaleString()} characters
    </p>
    
    {/* Action buttons */}
    <div className="flex gap-2 mt-3">
      <button
        onClick={() => setDocumentModalMessage(message)}
        className="flex-1 py-1.5 px-3 rounded text-[10px] font-medium transition-all"
        style={{ 
          backgroundColor: `${glowColor}20`,
          color: glowColor 
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = `${glowColor}30`;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = `${glowColor}20`;
        }}
      >
        View full document
      </button>
      <button
        onClick={() => handleShareMessage(message)}
        className="p-1.5 rounded transition-colors"
        style={{ color: `${fontColor}60` }}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = fontColor;
          e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = `${fontColor}60`;
          e.currentTarget.style.backgroundColor = 'transparent';
        }}
        title="Share"
      >
        <Share size={14} />
      </button>
      <button
        onClick={() => handleDownloadMessage(message)}
        className="p-1.5 rounded transition-colors"
        style={{ color: `${fontColor}60` }}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = fontColor;
          e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = `${fontColor}60`;
          e.currentTarget.style.backgroundColor = 'transparent';
        }}
        title="Download"
      >
        <Download size={14} />
      </button>
    </div>
  </div>
)}

{/* Short message (no truncation) */}
{!shouldTruncate && (
  <p className="text-[13px] leading-relaxed text-white/85 mt-1">
    {message.text}
  </p>
)}
```

---

## Phase 5: Document View Modal

### Task 5.1: Add Document Modal JSX
**What to build:** Modal for viewing full documents
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (before closing AnimatePresence)
**_Requirements: 4.2, 5.1, 5.2, 5.3, 5.4, 5.5_

**Add modal JSX:**
```tsx
{/* Document View Modal */}
<AnimatePresence>
  {documentModalMessage && (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(10px)' }}
      onClick={() => setDocumentModalMessage(null)}
      role="dialog"
      aria-modal="true"
      aria-labelledby="document-modal-title"
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
        className="w-full max-w-2xl max-h-[80vh] rounded-lg overflow-hidden flex flex-col"
        style={{
          background: 'linear-gradient(135deg, rgba(15,15,25,0.98) 0%, rgba(10,10,20,0.99) 100%)',
          border: `1px solid ${glowColor}30`,
          boxShadow: `0 25px 50px -12px rgba(0,0,0,0.5), 0 0 30px ${glowColor}10`
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Modal header */}
        <div 
          className="px-4 py-3 flex items-center justify-between border-b flex-shrink-0"
          style={{ borderColor: `${glowColor}20` }}
        >
          <div className="flex items-center gap-2" id="document-modal-title">
            {(() => {
              const type = getContentType(documentModalMessage);
              const Icon = type === 'markdown' ? FileText :
                          type === 'email' ? Mail :
                          type === 'video' ? Video :
                          type === 'picture' ? Image : File;
              return <Icon size={16} style={{ color: glowColor }} />;
            })()}
            <span className="text-sm font-medium" style={{ color: fontColor }}>
              {ContentTypeLabels[getContentType(documentModalMessage)]}
            </span>
            <span className="text-[10px] text-white/40">
              ({documentModalMessage.text.length.toLocaleString()} chars)
            </span>
          </div>
          <button
            onClick={() => setDocumentModalMessage(null)}
            className="p-1 rounded transition-colors"
            style={{ color: `${fontColor}60` }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = fontColor;
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = `${fontColor}60`;
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            aria-label="Close document view"
          >
            <X size={18} />
          </button>
        </div>
        
        {/* Modal content */}
        <div 
          className="p-5 overflow-y-auto flex-1"
          style={{ maxHeight: 'calc(80vh - 140px)' }}
        >
          <pre 
            className="text-[14px] leading-relaxed whitespace-pre-wrap font-mono"
            style={{ color: 'rgba(255,255,255,0.9)' }}
          >
            {documentModalMessage.text}
          </pre>
        </div>
        
        {/* Modal action bar */}
        <div 
          className="px-4 py-3 flex gap-3 border-t flex-shrink-0"
          style={{ borderColor: `${glowColor}20` }}
        >
          <button
            onClick={() => handleDownloadMessage(documentModalMessage)}
            className="flex items-center gap-2 px-4 py-2 rounded text-[11px] font-medium transition-colors"
            style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = `${glowColor}30`;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = `${glowColor}20`;
            }}
          >
            <Download size={14} />
            Download
          </button>
          <button
            onClick={() => handleShareMessage(documentModalMessage)}
            className="flex items-center gap-2 px-4 py-2 rounded text-[11px] font-medium transition-colors"
            style={{ backgroundColor: 'rgba(255,255,255,0.08)', color: fontColor }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.12)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)';
            }}
          >
            <Share size={14} />
            Share
          </button>
          <button
            onClick={() => handleCopyMessage(documentModalMessage.text, documentModalMessage.id)}
            className="flex items-center gap-2 px-4 py-2 rounded text-[11px] font-medium transition-colors"
            style={{ backgroundColor: 'rgba(255,255,255,0.08)', color: fontColor }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.12)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)';
            }}
          >
            <Copy size={14} />
            {copiedMessageId === documentModalMessage.id ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )}
</AnimatePresence>
```

---

### Task 5.2: Add Escape Key Handler for Modal
**What to build:** Close modal on Escape key
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (in existing Escape handler)
**_Requirements: 5.4_

**Modify existing useEffect for Escape key:**
```typescript
useEffect(() => {
  const handleEscape = (e: KeyboardEvent) => {
    if (e.key === "Escape" && isOpen) {
      // Close document modal first if open
      if (documentModalMessage) {
        setDocumentModalMessage(null);
        return;
      }
      // Close dropdowns next
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
```

---

## Phase 6: Backend Integration

### Task 6.1: Add Backend Handler for Export Event
**What to build:** Log export events in backend
**Files to modify:** `IRISVOICE/backend/iris_gateway.py`
**_Requirements: 6.1, 6.2_

**Add to message type routing:**
```python
elif msg_type == "message_exported":
    await self._handle_message_exported(session_id, client_id, message)
```

**Add handler:**
```python
async def _handle_message_exported(self, session_id: str, client_id: str, message: dict) -> None:
    """Handle message export events for analytics."""
    payload = message.get("payload", {})
    message_id = payload.get("message_id")
    content_type = payload.get("content_type")
    
    self._logger.info(
        f"[Session: {session_id}] Message exported",
        extra={
            "session_id": session_id,
            "client_id": client_id,
            "message_id": message_id,
            "content_type": content_type
        }
    )
    
    # Could store in analytics DB here if needed
```

---

## Verification

### Requirements Coverage

| Req | Description | Tasks |
|-----|-------------|-------|
| 1.1-1.5 | Message thresholds (150/300) | 4.2, 4.3, 4.4 |
| 2.1-2.4 | Content type detection | 1.1, 1.2, 1.3, 4.1 |
| 3.1-3.6 | Truncated message UI | 2.1, 4.2, 4.3 |
| 4.1-4.5 | Document mode | 2.2, 3.1, 3.2, 4.4, 5.1 |
| 5.1-5.5 | Accessibility | 5.1, 5.2 |
| 6.1-6.2 | Backend integration | 6.1 |
| 7.1 | Inline implementation | All tasks |

**Total Tasks:** 15
**Estimated Effort:** 1-2 days
**All implementation in:** `IRISVOICE/components/chat-view.tsx`
