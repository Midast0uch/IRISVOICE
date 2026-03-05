# Design: Theme Color System Cleanup

## Overview

This design consolidates theme color management into a single context with clear component responsibilities. The key architectural decision is to make `ThemeSwitcherCard` the primary user-facing control while removing conflicting components.

## Architecture

### Component Hierarchy

```
App (BrandColorProvider)
├── ThemeSwitcherCard (primary control)
│   ├── Theme preview cards (4 options)
│   └── SidePanel (when theme selected)
│       ├── Theme preview grid
│       ├── Brand Color sliders (collapsible)
│       └── Base Plate sliders (collapsible)
├── WheelView
│   ├── DualRingMechanism (uses BrandColorContext)
│   └── SidePanel (for other cards)
├── DashboardWing (uses BrandColorContext for glow)
└── ChatView (uses BrandColorContext for glow)
```

### Data Flow

```
User selects theme
    ↓
ThemeSwitcherCard calls setTheme()
    ↓
BrandColorContext updates state
    ↓
All components using useBrandColor() re-render
    ↓
WheelView, DashboardWing, ChatView update colors
```

## Components

### 1. BrandColorContext (Existing, Verified)

**File:** `IRISVOICE/contexts/BrandColorContext.tsx`

**Interface:**
```typescript
interface BrandColorContextType {
  theme: ThemeType
  brandColor: { hue, saturation, lightness }
  basePlateColor: { hue, saturation, lightness }
  setTheme: (theme: ThemeType) => void
  setHue, setSaturation, setLightness: (value: number) => void
  setBasePlateHue, setBasePlateSaturation, setBasePlateLightness: (value: number) => void
  getThemeConfig: () => ThemeConfig
  resetToThemeDefault: () => void
}
```

**Status:** ✅ Correct - use as-is

### 2. ThemeSwitcherCard (Update)

**File:** `IRISVOICE/components/theme-switcher-card.tsx`

**Changes:**
- Keep current compact design
- Add click handler that triggers SidePanel
- No internal sliders - defer to SidePanel

**Props:**
```typescript
interface ThemeSwitcherCardProps {
  onThemeSelect?: (theme: ThemeType) => void
  showSidePanel?: () => void
}
```

### 3. SidePanel (Update)

**File:** `IRISVOICE/components/wheel-view/SidePanel.tsx`

**New Theme UI Structure:**

```typescript
// When card.id === 'theme-mode'
const ThemePanel = () => (
  <>
    {/* Theme Selection Grid */}
    <div className="grid grid-cols-2 gap-2 mb-4">
      {themes.map(t => <ThemePreviewCard key={t} theme={t} />)}
    </div>
    
    {/* Collapsible Brand Color */}
    <CollapsibleSection title="Brand Color">
      <ColorSliderGroup 
        hue={brandColor.hue} onHueChange={setHue}
        saturation={brandColor.saturation} onSatChange={setSaturation}
        lightness={brandColor.lightness} onLightChange={setLightness}
      />
      <ResetButton onClick={resetToThemeDefault} />
    </CollapsibleSection>
    
    {/* Collapsible Base Plate */}
    <CollapsibleSection title="Base Plate">
      <ColorSliderGroup 
        hue={basePlateColor.hue} onHueChange={setBasePlateHue}
        saturation={basePlateColor.saturation} onSatChange={setBasePlateSaturation}
        lightness={basePlateColor.lightness} onLightChange={setBasePlateLightness}
      />
    </CollapsibleSection>
  </>
)
```

### 4. Components to Remove

**File:** `IRISVOICE/components/testing/ThemeTestSwitcher.tsx`

**Action:** Delete entire file - testing component not needed

**Rationale:** Confusion with ThemeSwitcherCard

---

## Collapsible Section Component

**New file:** `IRISVOICE/components/wheel-view/CollapsibleSection.tsx`

```typescript
interface CollapsibleSectionProps {
  title: string
  children: React.ReactNode
  defaultExpanded?: boolean
}

export const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  title,
  children,
  defaultExpanded = false
}) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)
  
  return (
    <div className="border-b border-white/10">
      <button 
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between py-3"
      >
        <span className="text-[10px] font-bold uppercase tracking-wider text-white/60">
          {title}
        </span>
        <ChevronDown 
          className={`w-4 h-4 text-white/40 transition-transform ${
            isExpanded ? 'rotate-180' : ''
          }`} 
        />
      </button>
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="pb-4 space-y-3">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
```

---

## Color Slider Group Component

**New file:** `IRISVOICE/components/wheel-view/ColorSliderGroup.tsx`

```typescript
interface ColorSliderGroupProps {
  hue: number
  saturation: number
  lightness: number
  onHueChange: (value: number) => void
  onSatChange: (value: number) => void
  onLightChange: (value: number) => void
  glowColor: string
}

export const ColorSliderGroup: React.FC<ColorSliderGroupProps> = ({
  hue, saturation, lightness,
  onHueChange, onSatChange, onLightChange,
  glowColor
}) => {
  return (
    <div className="space-y-3">
      {/* Hue - Rainbow gradient */}
      <SliderField
        label="Hue"
        value={hue}
        min={0}
        max={360}
        unit="°"
        gradient="linear-gradient(to right, hsl(0,100%,50%), hsl(60,100%,50%), hsl(120,100%,50%), hsl(180,100%,50%), hsl(240,100%,50%), hsl(300,100%,50%), hsl(360,100%,50%))"
        onChange={onHueChange}
        glowColor={glowColor}
      />
      
      {/* Saturation */}
      <SliderField
        label="Saturation"
        value={saturation}
        min={0}
        max={100}
        unit="%"
        gradient={`linear-gradient(to right, hsl(${hue},0%,50%), hsl(${hue},100%,50%))`}
        onChange={onSatChange}
        glowColor={glowColor}
      />
      
      {/* Lightness */}
      <SliderField
        label="Lightness"
        value={lightness}
        min={0}
        max={100}
        unit="%"
        gradient={`linear-gradient(to right, hsl(${hue},${saturation}%,0%), hsl(${hue},${saturation}%,50%), hsl(${hue},${saturation}%,100%))`}
        onChange={onLightChange}
        glowColor={glowColor}
      />
    </div>
  )
}
```

---

## Data Models

### Theme Type

```typescript
type ThemeType = 'aether' | 'ember' | 'aurum' | 'verdant'
```

### Color State

```typescript
interface BrandColorState {
  hue: number      // 0-360
  saturation: number  // 0-100
  lightness: number   // 0-100
}
```

---

## Key Design Decisions

### Decision 1: Keep BrandColorContext, Remove Duplicates

**Choice:** Use `BrandColorContext` as the single source
**Rationale:** Already working correctly, has localStorage persistence
**Remove:** Any other color contexts or inline color state

### Decision 2: Remove ThemeTestSwitcher

**Choice:** Delete the testing component
**Rationale:** Only for development, causes confusion with ThemeSwitcherCard
**Migration:** Any needed debugging features move to ThemeSwitcherCard

### Decision 3: Collapsible Sections in SidePanel

**Choice:** Group sliders into collapsible sections
**Rationale:** Reduces visual clutter, users can focus on one color at a time
**Alternative considered:** All sliders visible (rejected - too many sliders)

### Decision 4: ThemeSwitcherCard → SidePanel Flow

**Choice:** Click theme card → SidePanel opens with sliders
**Rationale:** Consistent with other card interactions
**Alternative considered:** Inline sliders (rejected - breaks card pattern)

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| localStorage unavailable | Fall back to session-only state |
| Invalid theme in storage | Reset to 'aether' default |
| Color values out of range | Clamp to valid range (0-360, 0-100) |
| Component loads before context | Show loading state |

---

## Testing Strategy

1. **Unit Tests:**
   - BrandColorContext state updates
   - CollapsibleSection expand/collapse
   - ColorSliderGroup value changes

2. **Integration Tests:**
   - Theme change updates all components
   - Custom colors persist and reload
   - SidePanel theme UI flow

3. **E2E Tests:**
   - User changes theme via ThemeSwitcherCard
   - User fine-tunes colors in SidePanel
   - Verify all components reflect changes

---

## Migration Path

**Before implementation:**
1. Audit all color-related code
2. Document current color prop drilling
3. Identify all uses of ThemeTestSwitcher

**During implementation:**
1. Update ThemeSwitcherCard
2. Update SidePanel with new UI
3. Remove ThemeTestSwitcher
4. Update prop-drilling components

**After implementation:**
1. Verify no color props passed down
2. Test all theme interactions
3. Delete old code