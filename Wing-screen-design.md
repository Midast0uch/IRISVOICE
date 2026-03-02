```markdown
# IRIS Wings Design Implementation Spec

## Critical Constraints
- ChatWing: 255px width, 50vh height, left: 3%, rotateY: 15deg
- DashboardWing: 280px width, 50vh height, right: 3%, rotateY: -15deg
- NO dimension changes beyond these values
- Work within existing components: ChatWing, DashboardWing, DarkGlassDashboard
- NO new component files unless absolutely necessary
- Configuration structure is being refactored - keep implementation flexible

---

## 1. Universal Notification System

### 1.1 Notification Icon Placement

**ChatWing Header**: Between History and Dashboard icons
**DashboardWing Header**: Between title and Close button

### 1.2 Notification State Management

Add to both components:
```tsx
const [notifications, setNotifications] = useState<Array<{
  id: string;
  type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
}>>([]);

const [showNotifications, setShowNotifications] = useState(false);
const [unreadCount, setUnreadCount] = useState(0);

// Calculate unread on notifications change
useEffect(() => {
  setUnreadCount(notifications.filter(n => !n.read).length);
}, [notifications]);

// Mark as read when panel opened
useEffect(() => {
  if (showNotifications) {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  }
}, [showNotifications]);
```

### 1.3 Notification Icon Component (Inline)

```tsx
// Notification bell with unread badge
<button
  onClick={() => setShowNotifications(!showNotifications)}
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
  
  {/* Unread badge */}
  {unreadCount > 0 && (
    <motion.span
      initial={{ scale: 0 }}
      animate={{ scale: 1 }}
      className="absolute top-1 right-1 w-2 h-2 rounded-full"
      style={{ backgroundColor: glowColor }}
    />
  )}
</button>
```

### 1.4 Notification Dropdown Panel

**Insert after header in both wings**:
```tsx
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
                borderLeft: `2px solid ${getNotificationColor(notif.type)}`
              }}
            >
              {/* Type indicator glow */}
              <div 
                className="absolute top-0 right-0 w-16 h-16 opacity-10 blur-xl rounded-full -translate-y-1/2 translate-x-1/2"
                style={{ backgroundColor: getNotificationColor(notif.type) }}
              />
              
              <div className="flex items-start justify-between relative">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 mb-1">
                    {getNotificationIcon(notif.type)}
                    <span 
                      className="text-[9px] font-semibold tracking-wide uppercase"
                      style={{ color: getNotificationColor(notif.type) }}
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
```

### 1.5 Notification Helpers

```tsx
const getNotificationColor = (type: string) => {
  switch (type) {
    case 'alert': return '#fbbf24'; // amber
    case 'permission': return '#3b82f6'; // blue
    case 'error': return '#ef4444'; // red
    case 'task': return '#a855f7'; // purple
    case 'completion': return '#22c55e'; // green
    default: return glowColor;
  }
};

const getNotificationIcon = (type: string) => {
  const iconProps = { size: 10, style: { color: getNotificationColor(type) } };
  switch (type) {
    case 'alert': return <AlertTriangle {...iconProps} />;
    case 'permission': return <Shield {...iconProps} />;
    case 'error': return <AlertCircle {...iconProps} />;
    case 'task': return <Loader {...iconProps} className="animate-spin" />;
    case 'completion': return <CheckCircle {...iconProps} />;
    default: return <Info {...iconProps} />;
  }
};
```

---

## 2. ChatWing (chat-view.tsx) Implementation

### 2.1 Header Redesign (48px height)

**Icon order**: Pulse indicator | Title | History | Notifications | Dashboard | Close

```tsx
<div 
  className="h-12 px-3 flex items-center justify-between flex-shrink-0 border-b relative"
  style={{ borderColor: `${glowColor}15` }}
>
  {/* Global error line */}
  {globalError && (
    <motion.div
      className="absolute top-0 left-0 right-0 h-[1px] z-30"
      style={{ background: 'rgba(239,68,68,0.8)' }}
      animate={{ opacity: [1, 0.3, 1] }}
      transition={{ duration: 2, repeat: Infinity }}
    />
  )}
  
  <div className="flex items-center gap-2">
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
      IRIS Assistant
    </span>
  </div>
  
  <div className="flex items-center gap-0.5">
    {/* History */}
    <button
      onClick={() => {
        setShowHistory(!showHistory);
        setShowNotifications(false);
      }}
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
    
    {/* Notifications - UNIVERSAL */}
    <button
      onClick={() => {
        setShowNotifications(!showNotifications);
        setShowHistory(false);
      }}
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
    
    {/* Dashboard */}
    <button
      onClick={() => {
        onDashboardClick();
        setShowNotifications(false);
        setShowHistory(false);
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
      title="Open Dashboard"
    >
      <BarChart3 size={16} />
    </button>
    
    {/* Close */}
    <button
      onClick={() => {
        onClose();
        setShowNotifications(false);
        setShowHistory(false);
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
```

### 2.2 Dropdown Management

Only one dropdown open at a time:
```tsx
// When opening history, close notifications
setShowHistory(!showHistory);
setShowNotifications(false);

// When opening notifications, close history
setShowNotifications(!showNotifications);
setShowHistory(false);

// When opening dashboard or closing, close both
setShowNotifications(false);
setShowHistory(false);
```

### 2.3 Message Bubbles (Convergent Corners)

**User bubble** (sharp left toward Orb):
```tsx
<motion.div
  initial={{ opacity: 0, y: 10, scale: 0.95 }}
  animate={{ opacity: 1, y: 0, scale: 1 }}
  transition={{ duration: 0.2 }}
  className="max-w-[85%] px-3 py-2.5 text-white relative overflow-hidden"
  style={{
    backgroundColor: `${primaryColor}cc`,
    borderRadius: '16px 16px 4px 16px',
    boxShadow: '0 4px 20px rgba(0,0,0,0.3)'
  }}
>
  {/* Subtle glow on send */}
  <div 
    className="absolute inset-0 opacity-0 transition-opacity duration-300"
    style={{ 
      background: `radial-gradient(circle at center, ${primaryColor}40 0%, transparent 70%)`,
      opacity: justSent ? 0.5 : 0
    }}
  />
  
  <p className="text-[13px] leading-relaxed relative z-10">{message.text}</p>
  <p className="text-[9px] mt-1.5 text-right opacity-70 tabular-nums relative z-10">
    {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
  </p>
</motion.div>
```

**IRIS bubble** (sharp right toward Orb, live TTS):
```tsx
<motion.div
  initial={{ opacity: 0, y: 10, scale: 0.95 }}
  animate={{ opacity: 1, y: 0, scale: 1 }}
  transition={{ duration: 0.2 }}
  className="max-w-[85%] px-3 py-2.5 relative overflow-hidden"
  style={{
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: '16px 16px 16px 4px',
    borderLeft: `2px solid ${glowColor}50`,
    boxShadow: '0 4px 20px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.05)'
  }}
>
  <div className="flex items-center gap-1.5 mb-1.5">
    <span 
      className="text-[10px] font-semibold tracking-wide"
      style={{ color: glowColor }}
    >
      IRIS
    </span>
    {isSpeaking && (
      <span className="text-[9px] text-white/40 animate-pulse flex items-center gap-1">
        <span className="w-1 h-1 rounded-full bg-current animate-bounce" style={{ animationDelay: '0ms' }} />
        <span className="w-1 h-1 rounded-full bg-current animate-bounce" style={{ animationDelay: '150ms' }} />
        <span className="w-1 h-1 rounded-full bg-current animate-bounce" style={{ animationDelay: '300ms' }} />
      </span>
    )}
  </div>
  
  {/* Live TTS word highlighting */}
  <p className="text-[13px] leading-relaxed text-white/85">
    {message.words ? message.words.map((word, idx) => (
      <motion.span
        key={idx}
        initial={idx === currentWordIndex ? { opacity: 0.5, y: 2 } : false}
        animate={{ 
          opacity: idx === currentWordIndex ? 1 : idx < currentWordIndex ? 0.7 : 0.85,
          y: 0,
          color: idx === currentWordIndex ? glowColor : 'rgba(255,255,255,0.85)',
          textShadow: idx === currentWordIndex ? `0 0 12px ${glowColor}60` : 'none'
        }}
        transition={{ duration: 0.15 }}
      >
        {word}{' '}
      </motion.span>
    )) : message.text}
  </p>
  
  <p className="text-[9px] mt-1.5 text-right opacity-50 tabular-nums">
    {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
  </p>
</motion.div>
```

### 2.4 Input Area (Border-Only, Floating Send)

```tsx
<div 
  className="px-3 pb-3 pt-2 flex-shrink-0 relative"
  style={{
    background: 'linear-gradient(0deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.5) 50%, transparent 100%)'
  }}
>
  <div className="relative flex items-end gap-2">
    <div className="flex-1 relative">
      <input
        ref={inputRef}
        type="text"
        value={voiceState === 'listening' ? interimTranscript || '' : inputText}
        onChange={(e) => voiceState !== 'listening' && setInputText(e.target.value)}
        onKeyPress={handleKeyPress}
        placeholder={voiceState === 'listening' ? 'Listening...' : 'Type your message...'}
        disabled={isTyping}
        className="w-full bg-transparent border-0 border-b-2 px-1 py-2.5 pr-12 text-[13px] focus:outline-none transition-all duration-200"
        style={{
          borderColor: voiceState === 'listening' 
            ? `${glowColor}${Math.round((audioLevel || 0.5) * 255).toString(16).padStart(2, '0')}`
            : inputText 
              ? `${glowColor}80` 
              : 'rgba(255,255,255,0.15)',
          color: voiceState === 'listening' ? 'rgba(255,255,255,0.5)' : fontColor,
          fontStyle: voiceState === 'listening' ? 'italic' : 'normal',
          caretColor: glowColor
        }}
      />
      
      {/* Character count / voice indicator */}
      <div className="absolute right-0 top-0 text-[9px] text-white/30 tabular-nums pointer-events-none">
        {voiceState === 'listening' ? (
          <span style={{ color: glowColor }}>● REC</span>
        ) : inputText.length > 0 ? (
          `${inputText.length}`
        ) : ''}
      </div>
    </div>
    
    {/* Floating send button - no clipping */}
    <motion.button
      onClick={handleSendMessage}
      disabled={!inputText.trim() || isTyping || voiceState === 'listening'}
      className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed relative"
      style={{
        backgroundColor: inputText.trim() ? `${primaryColor}dd` : 'rgba(255,255,255,0.1)',
        marginBottom: '2px',
        boxShadow: inputText.trim() ? `0 0 20px ${primaryColor}40` : 'none'
      }}
      whileHover={inputText.trim() ? { 
        scale: 1.08,
        boxShadow: `0 0 30px ${primaryColor}60`
      } : {}}
      whileTap={inputText.trim() ? { scale: 0.92 } : {}}
    >
      <Send size={15} className="text-white ml-0.5" />
      
      {/* Chromatic aberration on active */}
      {inputText.trim() && (
        <div 
          className="absolute inset-0 rounded-full opacity-0 hover:opacity-100 transition-opacity duration-75 pointer-events-none"
          style={{
            boxShadow: 'inset -1px 0 0 rgba(255,0,0,0.3), inset 1px 0 0 rgba(0,0,255,0.3)'
          }}
        />
      )}
    </motion.button>
  </div>
  
  {/* Voice waveform visualization */}
  {voiceState === 'listening' && (
    <div className="flex items-center justify-center gap-0.5 mt-2 h-3">
      {[...Array(12)].map((_, i) => (
        <motion.div
          key={i}
          className="w-0.5 rounded-full"
          style={{ backgroundColor: glowColor }}
          animate={{
            height: [4, 4 + (audioLevel || 0.5) * 8, 4],
            opacity: [0.3, 1, 0.3]
          }}
          transition={{
            duration: 0.5,
            repeat: Infinity,
            delay: i * 0.05,
            ease: "easeInOut"
          }}
        />
      ))}
    </div>
  )}
</div>
```

### 2.5 Scanline & Texture Overlay

```tsx
{/* Scanline texture */}
<div 
  className="absolute inset-0 pointer-events-none z-10 rounded-2xl overflow-hidden"
  style={{
    background: 'linear-gradient(transparent 50%, rgba(0,0,0,0.02) 50%)',
    backgroundSize: '100% 4px',
    opacity: 0.6,
    mixBlendMode: 'overlay'
  }}
/>

{/* Subtle noise texture */}
<div 
  className="absolute inset-0 pointer-events-none z-10 rounded-2xl overflow-hidden opacity-[0.03]"
  style={{
    backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`
  }}
/>
```

---

## 3. DashboardWing (dashboard-wing.tsx) Implementation

### 3.1 Container with Inner Glow

```tsx
<motion.div
  className="fixed z-[10]"
  initial={{ x: 120, opacity: 0, scale: 0.95 }}
  animate={{ x: 0, opacity: 1, scale: 1 }}
  exit={{ x: 120, opacity: 0, scale: 0.95 }}
  transition={{ 
    type: "spring", 
    stiffness: 280, 
    damping: 25,
    mass: 0.8
  }}
  style={{ 
    right: '3%',
    top: '50%',
    width: '280px',
    height: '50vh',
    perspective: '800px',
  }}
>
  <div 
    className="h-full relative overflow-hidden rounded-2xl flex flex-col"
    style={{
      transform: 'translateY(-50%) rotateY(-15deg) rotateX(2deg)',
      transformOrigin: 'right center',
      transformStyle: 'preserve-3d',
      background: 'linear-gradient(225deg, rgba(12,12,24,0.95) 0%, rgba(8,8,16,0.98) 100%)',
      backdropFilter: 'blur(24px)',
      border: '1px solid rgba(255,255,255,0.08)',
      boxShadow: `
        inset 8px 0 32px ${glowColor}15,
        -24px 0 60px rgba(0,0,0,0.5),
        0 0 0 1px rgba(255,255,255,0.03)
      `
    }}
  >
    {/* Edge Fresnel effect */}
    <div 
      className="absolute left-0 top-0 bottom-0 w-px pointer-events-none"
      style={{
        background: `linear-gradient(180deg, transparent 0%, ${glowColor}40 20%, ${glowColor}60 50%, ${glowColor}40 80%, transparent 100%)`
      }}
    />
```

### 3.2 Header with Notification

**Icon order**: Pulse | Title | Notifications | Close

```tsx
<div 
  className="h-11 px-3 flex items-center justify-between flex-shrink-0 border-b relative z-10"
  style={{ borderColor: `${glowColor}12` }}
>
  <div className="flex items-center gap-2">
    <div 
      className="w-1.5 h-1.5 rounded-full animate-pulse" 
      style={{ backgroundColor: glowColor }}
    />
    <span 
      className="text-[13px] font-semibold tracking-wide"
      style={{ color: fontColor, opacity: 0.9 }}
    >
      IRIS Dashboard
    </span>
  </div>
  
  <div className="flex items-center gap-0.5">
    {/* Notifications - UNIVERSAL */}
    <button
      onClick={() => setShowNotifications(!showNotifications)}
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
    
    <button
      onClick={() => {
        onClose();
        setShowNotifications(false);
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
      title="Close Dashboard"
    >
      <X size={16} />
    </button>
  </div>
</div>

{/* Notification dropdown - same as ChatWing */}
<AnimatePresence>
  {showNotifications && (
    // ... same notification panel code ...
  )}
</AnimatePresence>
```

### 3.3 Content Area

```tsx
<div className="flex-1 overflow-hidden relative">
  <DarkGlassDashboard 
    fieldValues={fieldValues}
    updateField={updateField}
    confirmChanges={confirmChanges}
    notifications={notifications}
    onNotificationClick={() => setShowNotifications(true)}
  />
</div>
```

---

## 4. DarkGlassDashboard Component

### 4.1 Flexible Structure

Accept configuration dynamically without hardcoded IDs:

```tsx
interface DarkGlassDashboardProps {
  categories: Array<{
    id: string;
    label: string;
    icon: React.ComponentType;
  }>;
  activeCategory: string;
  onCategoryChange: (id: string) => void;
  fields: Array<{
    id: string;
    type: string;
    label: string;
    // ... other field properties
  }>;
  values: Record<string, any>;
  onFieldChange: (fieldId: string, value: any) => void;
  onConfirm: () => void;
  errors?: Record<string, string>;
  glowColor: string;
}
```

### 4.2 Tab Bar with Collapse

```tsx
const [showMore, setShowMore] = useState(false);
const visibleCount = 5;
const visibleTabs = categories.slice(0, visibleCount);
const moreTabs = categories.slice(visibleCount);

<div className="flex relative z-10" style={{ borderBottom: `1px solid ${glowColor}10` }}>
  {visibleTabs.map((cat) => {
    const Icon = cat.icon;
    const isActive = activeCategory === cat.id && !showMore;
    return (
      <button
        key={cat.id}
        onClick={() => {
          onCategoryChange(cat.id);
          setShowMore(false);
        }}
        className="flex-1 flex flex-col items-center gap-1 py-2.5 transition-all duration-200 relative group"
        style={{
          color: isActive ? glowColor : 'rgba(255,255,255,0.35)',
          background: isActive ? `${glowColor}08` : 'transparent'
        }}
      >
        <Icon className="w-[18px] h-[18px] transition-transform duration-200 group-hover:scale-110" />
        <span className="text-[6px] font-semibold tracking-wider uppercase">{cat.label}</span>
        {isActive && (
          <motion.div
            layoutId="dashboard-tab"
            className="absolute bottom-0 left-1/4 right-1/4 h-[2px] rounded-full"
            style={{ background: glowColor }}
          />
        )}
      </button>
    );
  })}
  
  {moreTabs.length > 0 && (
    <button
      onClick={() => setShowMore(!showMore)}
      className="flex-1 flex flex-col items-center gap-1 py-2.5 transition-all duration-200 relative"
      style={{
        color: showMore ? glowColor : 'rgba(255,255,255,0.35)',
        background: showMore ? `${glowColor}08` : 'transparent'
      }}
    >
      <MoreHorizontal className="w-[18px] h-[18px]" />
      <span className="text-[6px] font-semibold tracking-wider uppercase">
        {showMore ? 'LESS' : 'MORE'}
      </span>
    </button>
  )}
  
  {/* More dropdown */}
  <AnimatePresence>
    {showMore && moreTabs.length > 0 && (
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        className="absolute top-full left-0 right-0 z-20 border-b"
        style={{
          background: 'rgba(10,10,20,0.98)',
          borderColor: `${glowColor}15`,
          backdropFilter: 'blur(20px)'
        }}
      >
        {moreTabs.map((cat) => {
          const Icon = cat.icon;
          return (
            <button
              key={cat.id}
              onClick={() => {
                onCategoryChange(cat.id);
                setShowMore(false);
              }}
              className="w-full flex items-center justify-center gap-3 py-3 hover:bg-white/5 transition-colors"
              style={{ color: activeCategory === cat.id ? glowColor : 'rgba(255,255,255,0.6)' }}
            >
              <Icon className="w-5 h-5" />
              <span className="text-[10px] font-semibold tracking-widest uppercase">{cat.label}</span>
            </button>
          );
        })}
      </motion.div>
    )}
  </AnimatePresence>
</div>
```

### 4.3 Category Header

```tsx
const activeCat = categories.find(c => c.id === activeCategory);
const Icon = activeCat?.icon;

<div 
  className="sticky top-0 z-10 flex items-center justify-between px-4 py-3 border-b backdrop-blur-md"
  style={{ 
    background: `linear-gradient(90deg, ${glowColor}10 0%, rgba(10,10,20,0.95) 60%)`,
    borderColor: `${glowColor}12`
  }}
>
  <div className="flex items-center gap-3">
    <div className="p-2 rounded-lg" style={{ background: `${glowColor}15` }}>
      <Icon className="w-5 h-5" style={{ color: glowColor }} />
    </div>
    <div>
      <span className="text-[13px] font-semibold tracking-wide text-white/90 block">
        {activeCat?.label}
      </span>
      <span className="text-[9px] text-white/40 tracking-wide">
        {fields.length} settings
      </span>
    </div>
  </div>
  
  <button 
    onClick={onReset}
    className="p-2 rounded-lg text-white/40 hover:text-white/70 hover:bg-white/5 transition-all"
    title="Reset to defaults"
  >
    <RotateCcw size={14} />
  </button>
</div>
```

### 4.4 Fields Panel (Full Width)

```tsx
<div className="flex-1 overflow-y-auto">
  <div className="px-4 py-4 space-y-2">
    {fields.map((field, idx) => (
      <FieldRow
        key={field.id}
        field={field}
        value={values[field.id]}
        onChange={(value) => onFieldChange(field.id, value)}
        error={errors?.[field.id]}
        glowColor={glowColor}
        delay={idx * 0.02}
      />
    ))}
  </div>
  <div className="h-20" />
</div>
```

### 4.5 FieldRow Component

```tsx
interface FieldRowProps {
  field: any;
  value: any;
  onChange: (value: any) => void;
  error?: string;
  glowColor: string;
  delay?: number;
}

const FieldRow = memo(function FieldRow({ field, value, onChange, error, glowColor, delay = 0 }: FieldRowProps) {
  // Section divider
  if (field.type === 'section') {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay }}
        className="pt-5 pb-2 border-t border-white/[0.06] first:border-0 first:pt-0"
      >
        <span className="text-[9px] font-semibold tracking-[0.15em] uppercase text-white/35">
          {field.label}
        </span>
      </motion.div>
    );
  }
  
  return (
    <motion.div
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.2 }}
      className="py-3 px-1 rounded-lg transition-colors duration-150 hover:bg-white/[0.02] group"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex-1 min-w-0">
          <span className="text-[11px] font-medium tracking-wide text-white/60 group-hover:text-white/75 transition-colors block truncate">
            {field.label}
          </span>
          {field.description && (
            <span className="text-[9px] text-white/30 truncate block mt-0.5">
              {field.description}
            </span>
          )}
        </div>
        
        <div className="flex-shrink-0">
          <FieldControl field={field} value={value} onChange={onChange} glowColor={glowColor} />
        </div>
      </div>
      
      {error && (
        <motion.div 
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="mt-2 flex items-start gap-1.5"
        >
          <AlertCircle size={10} className="text-red-400 mt-0.5 flex-shrink-0" />
          <span className="text-[9px] text-red-300/90 leading-tight">{error}</span>
        </motion.div>
      )}
    </motion.div>
  );
});
```

### 4.6 FieldControl Component

```tsx
function FieldControl({ field, value, onChange, glowColor }: any) {
  switch (field.type) {
    case 'toggle':
      return (
        <button
          onClick={() => onChange(!value)}
          className="relative w-10 h-5 rounded-full transition-colors duration-200"
          style={{ backgroundColor: value ? glowColor : 'rgba(255,255,255,0.12)' }}
        >
          <motion.span
            className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-md"
            animate={{ left: value ? '22px' : '2px' }}
            transition={{ type: 'spring', stiffness: 500, damping: 30 }}
          />
        </button>
      );
      
    case 'dropdown':
      return (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="text-[12px] bg-white/[0.06] border border-white/[0.08] rounded-md px-3 py-2 text-white outline-none min-w-[140px] transition-all duration-200 hover:border-white/[0.12] focus:border-[glowColor]40 focus:bg-white/[0.08]"
        >
          {field.options?.map((opt: string) => (
            <option key={opt} value={opt} className="bg-zinc-900 text-[12px]">{opt}</option>
          ))}
        </select>
      );
      
    case 'slider':
      const min = field.min ?? 0;
      const max = field.max ?? 100;
      const pct = ((Number(value) - min) / (max - min)) * 100;
      return (
        <div className="flex items-center gap-3 min-w-[140px]">
          <div 
            className="relative flex-1 h-1.5 bg-white/[0.08] rounded-full cursor-pointer overflow-hidden"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
              onChange(min + p * (max - min));
            }}
          >
            <div 
              className="absolute left-0 top-0 h-full rounded-full transition-all duration-150"
              style={{ 
                width: `${pct}%`,
                background: `linear-gradient(90deg, ${glowColor}80, ${glowColor})`,
                boxShadow: `0 0 8px ${glowColor}50`
              }} 
            />
          </div>
          <span className="text-[12px] tabular-nums font-medium min-w-[40px] text-right" style={{ color: glowColor }}>
            {Math.round(Number(value))}{field.unit}
          </span>
        </div>
      );
      
    case 'text':
    case 'password':
      return (
        <input
          type={field.type}
          value={value}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
          className="text-[12px] bg-white/[0.06] border border-white/[0.08] rounded-md px-3 py-2 text-white outline-none min-w-[140px] transition-all duration-200 hover:border-white/[0.12] focus:border-[glowColor]40 focus:bg-white/[0.08]"
        />
      );
      
    case 'button':
      return (
        <button
          onClick={field.onClick}
          className="px-4 py-2 rounded-md text-[11px] font-medium tracking-wide transition-all duration-200"
          style={{
            background: `${glowColor}15`,
            color: glowColor,
            border: `1px solid ${glowColor}35`
          }}
        >
          {field.label}
        </button>
      );
      
    default:
      return <span className="text-[12px] text-white/40">-</span>;
  }
}
```

### 4.7 Confirm Bar

```tsx
<div 
  className="absolute bottom-0 left-0 right-0 p-3 border-t backdrop-blur-md z-10"
  style={{ 
    background: 'linear-gradient(0deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
    borderColor: `${glowColor}10`
  }}
>
  <motion.button
    onClick={onConfirm}
    className="w-full py-2.5 rounded-lg text-[10px] font-semibold tracking-widest uppercase transition-all duration-200 relative overflow-hidden group"
    style={{
      background: `${glowColor}12`,
      color: glowColor,
      border: `1px solid ${glowColor}30`,
      boxShadow: `0 0 20px ${glowColor}08`
    }}
    whileHover={{ 
      background: `${glowColor}20`,
      borderColor: `${glowColor}50`,
      boxShadow: `0 0 30px ${glowColor}20`
    }}
    whileTap={{ scale: 0.98 }}
  >
    <div 
      className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
      style={{
        background: 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.1) 50%, transparent 100%)',
        animation: 'shine 2s infinite'
      }}
    />
    <span className="relative z-10">Confirm</span>
  </motion.button>
</div>
```

---

## 5. Color & Effects System

### 5.1 Holographic Monochrome

```tsx
// Background layers
const bgDeep = 'rgba(10, 10, 20, 0.98)';
const bgSurface = 'rgba(255, 255, 255, 0.03)';
const bgElevated = 'rgba(255, 255, 255, 0.06)';

// Text
const textMuted = 'rgba(255, 255, 255, 0.35)';
const textSecondary = 'rgba(255, 255, 255, 0.55)';
const textBody = 'rgba(255, 255, 255, 0.85)';
const textBright = 'rgba(255, 255, 255, 0.95)';

// Accent
const accentGlow = glowColor;
```

### 5.2 Effects

- **Chromatic aberration**: 0.3px RGB split on interaction
- **Edge glow**: 8px blur, 15% opacity, facing Orb
- **Scanlines**: 4px period, 2% opacity
- **Noise**: 3% opacity, SVG filter
- **Confirm shine**: 2s infinite sweep

---

## 6. Notification Type System

| Type | Color | Icon | Use Case |
|------|-------|------|----------|
| `alert` | `#fbbf24` | AlertTriangle | Warnings |
| `permission` | `#3b82f6` | Shield | Access requests |
| `error` | `#ef4444` | AlertCircle | Failures |
| `task` | `#a855f7` | Loader | Background processes |
| `completion` | `#22c55e` | CheckCircle | Success |

---

## 7. Final Checklist

- [ ] Universal notification bell in both headers
- [ ] Notification dropdown with type colors and actions
- [ ] ChatWing: 255px, convergent corners, floating send
- [ ] DashboardWing: 280px, convergent corners, full-width fields
- [ ] Flexible category structure (no hardcoded IDs)
- [ ] Collapsible "More" tab for excess categories
- [ ] Full-width field panel (no sidebar)
- [ ] 48px row height, generous spacing
- [ ] Live TTS word highlighting
- [ ] Voice waveform visualization
- [ ] All effects: scanlines, noise, chromatic aberration, edge glow
- [ ] NO references to subnodes, mini-nodes, or specific IDs
- [ ] Implementation adaptable to refactored configuration structure
```