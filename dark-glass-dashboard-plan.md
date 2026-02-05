# Dark Glassmorphic Dashboard Widget - Implementation Plan

**Created:** February 5, 2026  
**Status:** In Progress  
**PRD Reference:** `dark-glass-dashboard-prd.md`

---

## Clarifying Questions for User

1. **Widget Location**: Should the widget appear as a modal overlay, a floating panel, or slide-in drawer when triggered?
2. **Theme Detection**: Should the theme auto-detect from system preferences, or default to a specific theme (e.g., "nebula")?
3. **Initial Data**: Should the widget load with sample course data, or start empty?
4. **Persistence**: Should user progress on tree expansion be persisted?
5. **Integration**: Should this integrate with existing IRIS navigation nodes, or be completely separate?

---

## Phase 1: Core Structure (Files 1-3)

### Step 1.1: Create Theme Context
**File:** `contexts/ThemeContext.tsx`  
**Purpose:** Provide theme configuration to all dashboard components

**Implementation Notes:**
- Define Theme type and ThemeConfig interface
- Create themes object with all 6 theme variations
- Export ThemeContext and useTheme hook

### Step 1.2: Create Menu Window Button
**File:** `components/menu-window-button.tsx`  
**Purpose:** Button to toggle the dashboard widget visibility

**Implementation Notes:**
- Simple button with "Menu Window" text
- Position outside main UI (absolute positioning)
- Call onToggle prop when clicked
- Style: subtle, doesn't interfere with testing components

### Step 1.3: Create Tilt Container
**File:** `components/tilt-container.tsx`  
**Purpose:** 3D tilt effect wrapper with mouse tracking

**Implementation Notes:**
- Use Framer Motion useMotionValue, useSpring, useTransform
- Handle mouse move/leave events
- Apply perspective 2000px
- Include ambient glow div based on theme
- Wrap children with motion.div for 3D transforms

---

## Phase 2: Dashboard Components (Files 4-8)

### Step 2.1: Create Sidebar
**File:** `components/dashboard-sidebar.tsx`  
**Purpose:** Navigation panel with logo, nav items, user profile

**Implementation Notes:**
- Fixed width 240px
- Background: bg-black/40
- Logo "Labs." with animated status dot
- Navigation items: Dashboard, Courses, Content, Media, My Tasks, Settings, Log Out
- User profile section at bottom
- Use lucide-react icons

### Step 2.2: Create Header
**File:** `components/dashboard-header.tsx`  
**Purpose:** Top header with back button and action icons

**Implementation Notes:**
- Height 64px
- Back to All Courses button (left)
- Help and Notification icons (right)
- Notification dot uses theme primary color

### Step 2.3: Create Glass Row
**File:** `components/glass-row.tsx`  
**Purpose:** Collapsible hierarchical row component

**Implementation Notes:**
- 4 levels of depth with different opacity/blur
- Icon button for expand/collapse
- Label with optional warning badge
- Action buttons: chevron, trash, edit
- Group hover for action visibility
- Warning badge with amber color

### Step 2.4: Create Content Area
**File:** `components/dashboard-content.tsx`  
**Purpose:** Main content with hierarchical tree

**Implementation Notes:**
- Course title "Classical Latin (Pilot)" with Draft badge
- Warning banner for issues
- Status buttons: Ready for Review, Save Course
- Render units -> chapters -> lessons -> activities
- Handle expand/collapse state
- Use GlassRow component for each level

### Step 2.5: Create Main Dashboard
**File:** `components/dark-glass-dashboard.tsx`  
**Purpose:** Main widget container composing all parts

**Implementation Notes:**
- Props: theme, isOpen, onClose
- 1000x700px dimensions
- Use TiltContainer for 3D effect
- Include Sidebar, Header, ContentArea
- Sample course data (from PRD)
- AnimatePresence for open/close

---

## Phase 3: Integration (Files 9-10)

### Step 3.1: Create Isolated Test Page
**File:** `app/menu-window/page.tsx`  
**Purpose:** Standalone page for testing the widget

**Implementation Notes:**
- Full screen black background
- Menu Window Button positioned in corner
- DarkGlassDashboard component
- Not integrated with main hexagonal UI

### Step 3.2: Update Navigation (Optional)
**File:** TBD  
**Purpose:** Add route or link to access the widget

**Implementation Notes:**
- Keep separate from main IRIS navigation
- Only accessible via explicit button or URL

---

## Implementation Log

### 2026-02-05 - Implementation Complete
**Files Created:**
1. `contexts/DashboardThemeContext.tsx` - Theme provider with 6 theme variants
2. `components/tilt-container.tsx` - 3D tilt effect with mouse tracking
3. `components/menu-window-button.tsx` - Toggle button positioned top-right
4. `components/dashboard-sidebar.tsx` - Navigation sidebar with logo, nav items, user profile
5. `components/dashboard-header.tsx` - Top header with back button and notifications
6. `components/glass-row.tsx` - Hierarchical glassmorphic row component
7. `components/dashboard-content.tsx` - Content area with expandable tree
8. `components/dark-glass-dashboard.tsx` - Main widget container
9. `app/menu-window/page.tsx` - Isolated test page

**Status:** Ready for testing at `/menu-window` route

### 2026-02-05 - Initial Setup
- Created PRD document at `.windsurf/plans/dark-glass-dashboard-prd.md`
- Created this implementation plan
- Status: Awaiting user clarification on questions above

### Next Steps
1. Get answers to clarifying questions
2. Begin Phase 1 implementation
3. Log progress and any fixes encountered

---

## Dependencies to Verify

```bash
# Check if already installed
npm list framer-motion lucide-react

# Install if needed
npm install framer-motion@^11.0.0 lucide-react@^0.400.0
```

---

## Testing Checklist

- [ ] Widget opens via Menu Window button
- [ ] 3D tilt effect responds to mouse movement
- [ ] All 6 themes render correctly
- [ ] Hierarchical tree expands/collapses
- [ ] Warning badges appear for activities with issues
- [ ] Action buttons (edit, trash) work
- [ ] Animation performance at 60fps
- [ ] Reduced motion respected
