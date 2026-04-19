# IRIS Chat Interface Implementation Plan

## Vision Summary
Create a futuristic chat interface that integrates seamlessly with the existing hexagonal control center, maintaining the dark glass aesthetic while providing direct model communication capabilities.

## Core Design Principles
- **Glass Morphism**: Semi-transparent backgrounds with backdrop blur
- **Minimal Distraction**: Clean transitions that don't interrupt workflow
- **Existing Architecture**: Leverage current components, state management, and styling
- **Non-intrusive**: Background nodes visible but dimmed/non-interactive during chat
- **Menu Integration**: Dark glass dashboard accessible as "Menu Window" within chat overlay

## Implementation Phases

### Phase 1: Foundation & State Management
**Files to Modify:**
- `components/hexagonal-control-center.tsx`
- `contexts/NavigationContext.tsx`

**Clarified Approach:**
- `isChatActive` state will override existing navigation context
- When chat is active, navigation state will be paused
- When chat is closed, previous navigation state will be restored

**Tasks:**
- [ ] Add chat active state: `const [isChatActive, setIsChatActive] = useState(false)`
- [ ] Create chat toggle handler function
- [ ] Integrate with existing navigation context for seamless state management
- [ ] Ensure chat state takes precedence over navigation levels

### Phase 2: Text Area Transformation
**Files to Modify:**
- `components/hexagonal-control-center.tsx`

**Clarified Approach:**
- The "text area" is actually the `centerLabel` prop passed to IrisOrb
- We will add an invisible clickable div positioned below the IrisOrb
- This div will capture clicks to activate chat without interfering with orb functionality

**Tasks:**
- [ ] Add invisible clickable div below IrisOrb component
- [ ] Position div to align with current text display area
- [ ] Implement click handler for chat activation
- [ ] Create smooth fade transition for text display
- [ ] Ensure chat activation doesn't interfere with orb expansion/collapse

### Phase 3: Chat Overlay Component
**Files to Create:**
- `components/chat-view.tsx`

**Design Specifications:**
- **Glass Background**: `bg-black/30 backdrop-blur-lg border border-white/10`
- **Position**: Fixed bottom of screen with max-width container
- **Animation**: Slide up from bottom with spring physics
- **Backdrop**: Semi-transparent overlay with blur effect
- **Header**: Status indicator + close button
- **Messages**: User/assistant message bubbles with timestamps
- **Input**: Text input with send button, Enter key support

**Component Structure:**
```tsx
<ChatView>
  <Backdrop />           // Blur overlay
  <ChatContainer>        // Main chat window
    <Header />           // Status + close
    <MessageArea />      // Scrollable messages
    <InputArea />        // Text input + send
  </ChatContainer>
</ChatView>
```

### Phase 4: Background Node Management
**Files to Modify:**
- `components/hexagonal-control-center.tsx`
- `components/iris/prism-node.tsx` (existing node component)

**Tasks:**
- [ ] Pass `isChatActive` state to all hexagonal nodes
- [ ] Implement dimming effect for non-interactive nodes
- [ ] Add visual indicators that nodes are in "view only" mode
- [ ] Ensure nodes don't respond to clicks during chat mode
- [ ] Maintain visibility for aesthetic continuity

### Phase 5: Menu Window Integration
**Files to Leverage:**
- `components/dark-glass-dashboard.tsx` (existing menu window at level 4)

**Integration Strategy:**
- [ ] Reuse existing DarkGlassDashboard component within chat view
- [ ] Position as toggleable overlay within chat interface
- [ ] Label clearly as "Menu Window" for user clarity
- [ ] Use same glass styling as chat interface (consistent theming)
- [ ] Add toggle button in chat header for easy access
- [ ] Pass appropriate props (fieldValues, updateField) from chat context

**Menu Window Features:**
- All existing node configurations from DarkGlassDashboard
- Theme settings
- Voice settings  
- System preferences
- Quick access during chat sessions without leaving chat view

### Phase 6: WebSocket Integration
**Files to Modify:**
- `components/chat-view.tsx`
- Existing WebSocket connection logic

**Tasks:**
- [ ] Connect chat messages to existing WebSocket infrastructure
- [ ] Implement message sending via WebSocket
- [ ] Handle AI response streaming
- [ ] Add typing indicators during AI processing
- [ ] Integrate with existing message handling patterns

### Phase 7: Styling & Animations
**Files to Modify:**
- `components/chat-view.tsx`
- Global CSS for consistent theming

**Animation Specifications:**
- **Chat Activation**: 300ms fade in with spring slide up
- **Text Transition**: "tap to expand" fades out, input fades in
- **Message Bubbles**: Smooth appearance with slight bounce
- **Typing Indicator**: Pulsing dots animation
- **Menu Window**: Slide from side with glass effect

**Color Scheme:**
- Background: `rgba(0, 0, 0, 0.3)` with backdrop blur
- Borders: `rgba(255, 255, 255, 0.1)`
- User Messages: `bg-blue-500/80`
- Assistant Messages: `bg-white/10`
- Text: `text-white/90` for primary, `text-white/60` for secondary

### Phase 8: Testing & Polish
**Testing Areas:**
- [ ] Chat activation/deactivation smoothness
- [ ] Message sending/receiving functionality
- [ ] Background node interaction blocking
- [ ] Menu window accessibility during chat
- [ ] Responsive design for different screen sizes
- [ ] Performance with animations and backdrop filters

**Polish Items:**
- [ ] Smooth scroll to bottom for new messages
- [ ] Auto-focus on input when chat opens
- [ ] Keyboard navigation support
- [ ] Escape key to close chat
- [ ] Visual feedback for all interactions

## Architecture Integration

### State Management
- Use existing React state in `hexagonal-control-center.tsx`
- Leverage current navigation context for consistency
- Maintain separation of concerns between chat and main interface

### Component Hierarchy
```
HexagonalControlCenter
├── IrisOrb
├── TextArea (clickable for chat)
├── HexagonalNodes (dimmed when chat active)
└── ChatView (overlay when active)
    ├── Backdrop
    ├── ChatWindow
    └── MenuWindow (toggleable)
```

### Existing Resources to Leverage
- **Framer Motion**: Already used for animations
- **WebSocket Connection**: Existing infrastructure
- **Glass Styling**: Current dark glass dashboard patterns
- **Color Context**: Existing theme management
- **Icon System**: Lucide React icons already in use

## Success Criteria
- [ ] Chat interface activates smoothly without jarring transitions
- [ ] Background nodes remain visible but clearly non-interactive
- [ ] Menu window is easily accessible and clearly labeled
- [ ] All animations maintain 60fps performance
- [ ] Interface maintains futuristic, glass-like aesthetic
- [ ] No new dependencies added beyond existing stack
- [ ] WebSocket integration works seamlessly with backend

## Risk Mitigation
- **Performance**: Test backdrop-filter performance on lower-end systems
- **Accessibility**: Ensure keyboard navigation works properly
- **State Conflicts**: Verify chat state doesn't interfere with navigation
- **Mobile Responsiveness**: Test on various screen sizes
- **WebSocket Reliability**: Handle connection drops gracefully

## Next Steps
1. Create `ChatView` component with basic structure
2. Integrate chat state into main control center
3. Implement text area click handler and transitions
4. Add backdrop and glass styling
5. Integrate menu window component
6. Connect to WebSocket infrastructure
7. Test and polish all interactions