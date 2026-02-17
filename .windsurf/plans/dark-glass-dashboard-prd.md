# Dark Glassmorphic Dashboard Widget - PRD

**Version:** 1.0  
**Date:** February 5, 2026  
**Platform:** Desktop Widget (Next.js + React + Framer Motion)

---

## 1. Overview

A floating, tilted glassmorphic dashboard widget for desktop environments featuring a hierarchical course/content management interface. The widget uses pure transparency effects without background gradients, adapting its accent colors to match the host platform's theme system.

---

## 2. Design Analysis

### 2.1 Visual Hierarchy

| Layer | Opacity | Blur | Border | Purpose |
|-------|---------|------|--------|---------|
| **Main Container** | `bg-white/[0.08]` | `blur-2xl` | `border-white/10` | Primary widget frame |
| **Sidebar** | `bg-black/40` | `blur-xl` | `border-white/5` | Navigation panel |
| **Unit Level** | `bg-white/[0.08]` | `blur-lg` | `border-white/10` | Top hierarchy |
| **Chapter Level** | `bg-white/[0.05]` | `blur-md` | `border-white/5` | Nested content |
| **Lesson Level** | `bg-white/[0.03]` | `blur-md` | `border-white/5` | Deeper nesting |
| **Activity Level** | `bg-white/[0.02]` | `blur-sm` | `border-white/5` | Deepest level |

### 2.2 Typography Scale

| Element | Size | Weight | Opacity | Color |
|---------|------|--------|---------|-------|
| Logo | `text-xl` | `bold` | 100% | `text-white` |
| Nav Items | `text-sm` | `medium` | 60% -> 100% (hover) | `text-white` |
| Page Title | `text-3xl` | `semibold` | 90% | `text-white` |
| Tree Labels | `text-sm` | `medium` | 90% | `text-white` |
| Badges | `text-xs` | `medium` | 70% | Theme accent |
| Muted Text | `text-xs` | `regular` | 40% | `text-white` |

### 2.3 Spacing System

- **Widget padding:** `24px` (p-6)
- **Internal gaps:** `8px` (space-y-2)
- **Tree indentation:** `32px` per level (ml-8)
- **Border radius:** `24px` (rounded-3xl) main, `12px` (rounded-xl) rows
- **Row height:** `48px` (py-3)

---

## 3. Theme System

### 3.1 Platform-Dependent Color Mapping

> **Note:** Accent colors automatically adapt to the host platform's theme. The widget detects system preferences and applies the corresponding color palette.

| Theme ID | Platform Context | Primary Accent | Glow Effect | Status Color | Warning Color |
|----------|------------------|----------------|-------------|--------------|---------------|
| `aether` | macOS/iOS (Light) | `cyan-400` | Cyan glow | `emerald-400` | `amber-400` |
| `ember` | macOS/iOS (Dark) | `orange-500` | Orange glow | `emerald-400` | `amber-400` |
| `aurum` | Windows/Gold | `amber-400` | Gold glow | `green-500` | `orange-400` |
| `verdant` | Linux/Nature | `emerald-400` | Green glow | `blue-400` | `yellow-400` |
| `nebula` | Universal Purple | `violet-500` | Purple glow | `emerald-400` | `amber-400` |
| `crimson` | Error/Alert State | `rose-500` | Red glow | `emerald-400` | `red-400` |

### 3.2 Color Application Rules

| UI Element | Color Logic |
|------------|-------------|
| **Active nav item** | `bg-white/10` + theme border |
| **Notification dot** | Theme primary accent |
| **Badge backgrounds** | Theme accent @ 20% opacity |
| **Ambient glow** | Theme primary @ 20% blur |
| **Hover states** | Theme accent @ 10% overlay |
| **Status indicators** | Fixed semantic colors (emerald/amber) |
| **Warning states** | Fixed amber/orange (cross-theme consistent) |

---

## 4. 3D Tilt Effect Specification

### 4.1 Static Tilt (Default)

```css
transform: perspective(2000px) rotateX(8deg) rotateY(-12deg) scale(1);
```

| Parameter | Value | Description |
|-----------|-------|-------------|
| `perspective` | `2000px` | Depth of field |
| `rotateX` | `8deg` | Forward tilt (looking down) |
| `rotateY` | `-12deg` | Left rotation |
| `scale` | `1` | Base size |

### 4.2 Animation Specifications

| Animation | Duration | Easing | Trigger |
|-----------|----------|--------|---------|
| Initial entrance | `1000ms` | `easeOut` | Component mount |
| Hover lift | `300ms` | `spring` | Mouse enter |
| Tilt reset | `500ms` | `easeOut` | Mouse leave |

---

## 5. Technical Implementation

### 5.1 Component Architecture

```
DarkGlassDashboard (main container)
├── ThemeProvider (context for color mapping)
├── TiltContainer (3D transform wrapper)
│   ├── AmbientGlow (theme-colored backdrop)
│   ├── MainWidget (glass container)
│   │   ├── Sidebar (navigation)
│   │   │   ├── Logo
│   │   │   ├── NavItems[]
│   │   │   └── UserProfile
│   │   └── ContentArea
│   │       ├── Header
│   │       └── HierarchicalTree
│   │           ├── Unit[] (collapsible)
│   │           │   ├── Chapter[] (collapsible)
│   │           │   │   ├── Lesson[] (collapsible)
│   │           │   │   │   └── Activity[] (leaf nodes)
```

### 5.2 Types

```typescript
interface Activity {
  id: string;
  name: string;
  hasWarning?: string;
}

interface Lesson {
  id: string;
  name: string;
  activities: Activity[];
  expanded?: boolean;
}

interface Chapter {
  id: string;
  name: string;
  lessons: Lesson[];
  expanded?: boolean;
}

interface Unit {
  id: string;
  name: string;
  chapters: Chapter[];
  expanded?: boolean;
}

type Theme = 'aether' | 'ember' | 'aurum' | 'verdant' | 'nebula' | 'crimson';
```

---

## 6. Animation Specifications

| Interaction | Property | From | To | Duration | Easing |
|-------------|----------|------|-----|----------|--------|
| **Widget entrance** | opacity, rotateX, rotateY, scale | 0, 15deg, -15deg, 0.9 | 1, 8deg, -12deg, 1 | 1000ms | easeOut |
| **Mouse move tilt** | rotateX, rotateY | 8deg, -12deg | 12deg->2deg, -18deg->-6deg | Spring | stiffness: 150, damping: 20 |
| **Hover lift** | scale, y | 1, 0 | 1.02, -10px | 300ms | spring |
| **Row expand** | height, opacity | 0, 0 | auto, 1 | 300ms | easeOut |
| **Row hover** | background | white/5 | white/12 | 200ms | ease |
| **Action buttons** | opacity | 0 | 1 | 200ms | ease |

---

## 7. Accessibility

- **Reduced motion:** Disable 3D tilt when `prefers-reduced-motion` is detected
- **Keyboard navigation:** Full tab support through tree hierarchy
- **Screen readers:** ARIA labels for all interactive elements
- **Contrast:** Minimum 4.5:1 ratio for all text

---

## 8. Performance Requirements

- **Target FPS:** 60fps for all animations
- **Bundle size:** <50KB for component (excluding dependencies)
- **Render time:** <16ms per frame
- **Memory:** No memory leaks on theme switching

---

## 9. Dependencies

```json
{
  "dependencies": {
    "framer-motion": "^11.0.0",
    "lucide-react": "^0.400.0",
    "tailwindcss": "^3.4.0"
  }
}
```

---

## 10. Files to Create

| File | Path | Purpose |
|------|------|---------|
| Menu Window Button | `components/menu-window-button.tsx` | Button to toggle the widget |
| Dark Glass Dashboard | `components/dark-glass-dashboard.tsx` | Main widget component |
| Theme Context | `contexts/ThemeContext.tsx` | Theme provider |
| Tilt Container | `components/tilt-container.tsx` | 3D tilt wrapper |
| Sidebar | `components/dashboard-sidebar.tsx` | Navigation sidebar |
| Header | `components/dashboard-header.tsx` | Top header bar |
| Content Area | `components/dashboard-content.tsx` | Hierarchical tree content |
| Glass Row | `components/glass-row.tsx` | Collapsible row component |

---

## 11. Implementation Log

*This section will be updated as implementation progresses.*
