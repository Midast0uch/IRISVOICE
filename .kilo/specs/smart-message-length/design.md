# Design: Smart Message Length Handling (Simplified)

## Overview

This design implements a simplified two-tier message display system with content type detection. All implementation is inline within chat-view.tsx to maintain consistency with the existing codebase.

## Architecture

### Simplified Two-Tier System

```
MessagesContainer
└── MessageItem (inline rendering in chat-view.tsx)
    ├── Short Message (≤150 chars)
    │   └── Full text display (unchanged)
    ├── Truncated Message (151-300 chars)
    │   ├── 150 char preview with fade gradient
    │   ├── Content type icon
    │   ├── "Show more" button
    │   └── Expanded: Full text + Share/Download icons
    └── Document Mode (>300 chars)
        ├── 150 char preview
        ├── Content type icon (prominent)
        ├── Character count badge
        ├── "View full document" button
        ├── Share icon button
        └── Download icon button
            └── DocumentViewModal
                ├── Header (content type + close)
                ├── Full content with proper formatting
                └── Action bar (Download, Share, Copy)
```

### Content Type Detection

```typescript
// Detection priority: Video > Picture > Markdown > Email > Text

const ContentTypePatterns = {
  video: /(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov)/i,
  picture: /\.(jpg|jpeg|png|gif|webp|svg|bmp)(?:\?.*)?$/i,
  markdown: /(?:^#{1,6}\s|\*\*|__|\[.+?\]\(.+?\)|```)/m,
  email: /(?:^From:|^To:|^Subject:|\S+@\S+\.\S+)/m
};

function detectContentType(text: string): ContentType {
  if (ContentTypePatterns.video.test(text)) return 'video';
  if (ContentTypePatterns.picture.test(text)) return 'picture';
  if (ContentTypePatterns.markdown.test(text)) return 'markdown';
  if (ContentTypePatterns.email.test(text)) return 'email';
  return 'text';
}
```

### State Management

```typescript
// Add to chat-view.tsx state
const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
const [documentModalMessage, setDocumentModalMessage] = useState<Message | null>(null);
const [messageContentTypes, setMessageContentTypes] = useState<Record<string, ContentType>>({});

// Helper functions
const isMessageExpanded = (messageId: string) => expandedMessages.has(messageId);
const toggleMessageExpanded = (messageId: string) => { /* ... */ };
const getContentType = (message: Message) => messageContentTypes[message.id] || 'text';
```

## Implementation Details

### Constants

```typescript
const MESSAGE_THRESHOLDS = {
  TRUNCATE_AT: 150,
  DOCUMENT_MODE_AT: 300,
  WARNING_AT: 1000
} as const;

const ContentTypeIcons = {
  markdown: FileText,
  email: Mail,
  video: Video,
  picture: Image,
  text: File
};

const ContentTypeLabels = {
  markdown: 'Markdown Document',
  email: 'Email',
  video: 'Video',
  picture: 'Image',
  text: 'Text Document'
};
```

### Inline Message Rendering

```tsx
// Inside messages.map() in chat-view.tsx
const charCount = message.text.length;
const contentType = getContentType(message);
const isExpanded = isMessageExpanded(message.id);
const shouldTruncate = charCount > MESSAGE_THRESHOLDS.TRUNCATE_AT;
const isDocumentMode = charCount > MESSAGE_THRESHOLDS.DOCUMENT_MODE_AT;

// Determine display text
const displayText = isExpanded || !shouldTruncate 
  ? message.text 
  : message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT) + '...';

// Get icon component
const ContentIcon = ContentTypeIcons[contentType];
```

### Truncated Message UI (151-300 chars)

```tsx
{shouldTruncate && !isDocumentMode && (
  <div className="relative">
    {/* Content type icon */}
    <div className="flex items-center gap-1 mb-1">
      <ContentIcon size={12} style={{ color: glowColor }} />
      <span className="text-[9px] text-white/50 uppercase">{contentType}</span>
    </div>
    
    {/* Truncated text with fade */}
    <div className="relative">
      <p className="text-[13px] leading-relaxed text-white/85">
        {displayText}
      </p>
      {!isExpanded && (
        <div 
          className="absolute bottom-0 left-0 right-0 h-8"
          style={{
            background: 'linear-gradient(transparent, rgba(10,10,20,0.9))'
          }}
        />
      )}
    </div>
    
    {/* Show more/less button */}
    <button
      onClick={() => toggleMessageExpanded(message.id)}
      className="mt-2 text-[10px] flex items-center gap-1"
      style={{ color: glowColor }}
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
        <button onClick={() => handleShare(message)} className="...">
          <Share size={14} />
        </button>
        <button onClick={() => handleDownload(message)} className="...">
          <Download size={14} />
        </button>
      </div>
    )}
  </div>
)}
```

### Document Mode UI (>300 chars)

```tsx
{isDocumentMode && (
  <div className="relative">
    {/* Document header */}
    <div className="flex items-center gap-2 mb-2">
      <ContentIcon size={16} style={{ color: glowColor }} />
      <span className="text-[10px] font-medium" style={{ color: fontColor }}>
        {ContentTypeLabels[contentType]}
      </span>
      {charCount > MESSAGE_THRESHOLDS.WARNING_AT && (
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">
          Large
        </span>
      )}
    </div>
    
    {/* Preview text */}
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
        className="flex-1 py-1.5 px-3 rounded text-[10px] font-medium"
        style={{ 
          backgroundColor: `${glowColor}20`,
          color: glowColor 
        }}
      >
        View full document
      </button>
      <button
        onClick={() => handleShare(message)}
        className="p-1.5 rounded"
        style={{ color: fontColor }}
        title="Share"
      >
        <Share size={14} />
      </button>
      <button
        onClick={() => handleDownload(message)}
        className="p-1.5 rounded"
        style={{ color: fontColor }}
        title="Download"
      >
        <Download size={14} />
      </button>
    </div>
  </div>
)}
```

### Document View Modal

```tsx
// Add to JSX in chat-view.tsx
<AnimatePresence>
  {documentModalMessage && (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(8px)' }}
      onClick={() => setDocumentModalMessage(null)}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        className="w-full max-w-2xl max-h-[80vh] rounded-lg overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, rgba(15,15,25,0.98) 0%, rgba(10,10,20,0.99) 100%)',
          border: `1px solid ${glowColor}30`
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Modal header */}
        <div 
          className="px-4 py-3 flex items-center justify-between border-b"
          style={{ borderColor: `${glowColor}20` }}
        >
          <div className="flex items-center gap-2">
            {(() => {
              const Icon = ContentTypeIcons[getContentType(documentModalMessage)];
              return <Icon size={16} style={{ color: glowColor }} />;
            })()}
            <span className="text-sm font-medium" style={{ color: fontColor }}>
              {ContentTypeLabels[getContentType(documentModalMessage)]}
            </span>
          </div>
          <button
            onClick={() => setDocumentModalMessage(null)}
            className="p-1 rounded"
            style={{ color: `${fontColor}60` }}
          >
            <X size={18} />
          </button>
        </div>
        
        {/* Modal content */}
        <div className="p-4 overflow-y-auto" style={{ maxHeight: 'calc(80vh - 120px)' }}>
          <pre className="text-[14px] leading-relaxed whitespace-pre-wrap font-mono text-white/90">
            {documentModalMessage.text}
          </pre>
        </div>
        
        {/* Modal action bar */}
        <div 
          className="px-4 py-3 flex gap-3 border-t"
          style={{ borderColor: `${glowColor}20` }}
        >
          <button
            onClick={() => handleDownload(documentModalMessage)}
            className="flex items-center gap-2 px-4 py-2 rounded text-[11px] font-medium"
            style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
          >
            <Download size={14} />
            Download
          </button>
          <button
            onClick={() => handleShare(documentModalMessage)}
            className="flex items-center gap-2 px-4 py-2 rounded text-[11px] font-medium"
            style={{ backgroundColor: 'rgba(255,255,255,0.1)', color: fontColor }}
          >
            <Share size={14} />
            Share
          </button>
          <button
            onClick={() => handleCopyMessage(documentModalMessage.text, documentModalMessage.id)}
            className="flex items-center gap-2 px-4 py-2 rounded text-[11px] font-medium"
            style={{ backgroundColor: 'rgba(255,255,255,0.1)', color: fontColor }}
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

## Helper Functions

```typescript
// Content type detection
function detectContentType(text: string): ContentType {
  if (/youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov/i.test(text)) {
    return 'video';
  }
  if (/\.(jpg|jpeg|png|gif|webp|svg|bmp)(\?.*)?$/i.test(text)) {
    return 'picture';
  }
  if (/(?:^#{1,6}\s|\*\*|__|\[.+?\]\(.+?\)|```)/m.test(text)) {
    return 'markdown';
  }
  if (/(?:^From:|^To:|^Subject:|\S+@\S+\.\S+)/m.test(text)) {
    return 'email';
  }
  return 'text';
}

// Download handler
function handleDownload(message: Message) {
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
  
  // Send to backend for analytics/logging
  sendMessage?.('message_exported', { 
    message_id: message.id,
    content_type: contentType 
  });
}

// Share handler
async function handleShare(message: Message) {
  try {
    await navigator.clipboard.writeText(message.text);
    // Show toast notification (can use existing notification system)
  } catch (err) {
    console.error('Failed to share:', err);
  }
}
```

## Icon Imports

```typescript
// Add to existing imports in chat-view.tsx
import { 
  ChevronDown, 
  ChevronUp, 
  Download, 
  Share, 
  FileText, 
  Mail, 
  Video, 
  Image, 
  File 
} from 'lucide-react';
```

## Styling Consistency

All styling follows existing patterns in chat-view.tsx:
- Font sizes: 9px, 10px, 11px, 13px, 14px (matching existing text-[13px], etc.)
- Colors: Use `glowColor`, `fontColor`, `primaryColor` from theme
- Opacity values: 40%, 50%, 60%, 85%, 90% (matching existing patterns)
- Spacing: Uses Tailwind classes (gap-1, gap-2, p-2, px-3, py-2, etc.)
- Borders: Use `${glowColor}20`, `${glowColor}30` for subtle borders
- Backgrounds: Use rgba() values consistent with dark glass theme

## Testing

### Unit Test Cases
1. Content type detection for each type
2. Truncation at exactly 150 chars
3. Document mode trigger at 301 chars
4. Expand/collapse state toggle
5. Download filename generation

### Manual QA
1. Messages at boundaries (150, 151, 300, 301 chars)
2. Each content type (Markdown, email, video URL, image URL)
3. Keyboard navigation (Tab, Enter, Escape)
4. Reduced motion preference
5. Download and share functionality
