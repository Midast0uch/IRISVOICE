/**
 * orbWingGeometry — the ONE source of the orb + wing layout.
 *
 * WHY THIS FILE EXISTS
 * Four places used to hold their own copy of this maths, and they had drifted:
 *   - chat-view.tsx        ORB_WING_GAP = -20, dashboard balanced 510
 *   - dashboard-wing.tsx   ORB_WING_GAP = -20
 *   - app/page.tsx         ORB_WING_GAP = -2 (balanced) / +4 (spotlight)
 *   - useWindowResize.ts   dashboard balanced 560, spotlight 760, NO tilt at all
 * The window therefore reserved more width than the wings drew, and the wings
 * positioned themselves against an orb container that inflated to fill the
 * slack. The result on screen was a small orb with a wide empty gap on each
 * side, inside a window far larger than anything it contained.
 *
 * THE MODEL
 * The whole assembly is one frame, laid out left to right:
 *
 *   |<-- chatSide -->|<-- ORB_BAND -->|<-- dashSide -->|
 *   [  chat wing   ] [     orb      ] [ dashboard wing ]
 *
 * `chatSide` is the wing's width PLUS how far its tilted inner edge leans
 * toward the orb, so the band is clear space in what the user actually sees,
 * not in the untransformed box. Each wing pins to its own edge of the frame,
 * the orb sits in the middle of the band, and the frame is exactly as wide as
 * its three parts. Nothing is left over, so there is no slack to spread.
 *
 * In Tauri the native window IS the frame (see useWindowResize), so
 * frameLeft() returns 0. In a browser the viewport is wider and the same
 * frame is centred in it. One formula covers both.
 */

export const TILT_DEG = 15
export const PERSPECTIVE = 800

/**
 * The orb container: the canvas (capped at 120 px by XurOrb) plus the ring of
 * labels around it. "↑↑ VOICE" reaches furthest — 45 px out, scaled by
 * ORB_BOX/120, plus half its text and its 10 px hit padding.
 */
export const ORB_BOX = 175

/**
 * Horizontal clear space the wings must leave for the orb. Sized to the label
 * ring above (~214 px), rounded up so the tilted wing edges stop just short of
 * "↑↑ VOICE" instead of covering it.
 */
export const ORB_BAND = 220

/**
 * The idle window: orb only, no wings. It has to clear the voice haze
 * (inset -60 on the 175 box = 295), the level-2 radial menu (246) and the
 * ambient crawl tier, which anchors up and right of the orb.
 *
 * It used to be 680x680. A transparent Tauri window cannot be clicked through,
 * so those 680 px blocked the desktop underneath even though only the orb was
 * drawn. 420 blocks 62% less area.
 */
export const IDLE_W = 420
export const IDLE_H = 420

/** Window height whenever a wing is open. Wings render at 88vh of it. */
export const WING_H = 680

/** Level 3 is WheelView, which needs the full original column. */
export const WHEEL_W = 680
export const WHEEL_H = 680

export type UIStr = 'idle' | 'chat_open' | 'dashboard_open' | 'both_open'
export type SpotlightStr = 'balanced' | 'chatSpotlight' | 'dashboardSpotlight'

/** Mirrors ChatView.getSpotlightWidth. */
export function chatWidth(spotlight: SpotlightStr): number {
  if (spotlight === 'chatSpotlight') return 680
  if (spotlight === 'dashboardSpotlight') return 360
  return 510
}

/** Mirrors DashboardWing.getSpotlightWidth. */
export function dashboardWidth(spotlight: SpotlightStr): number {
  if (spotlight === 'dashboardSpotlight') return 680
  if (spotlight === 'chatSpotlight') return 360
  return 510
}

/**
 * How far a wing's tilted inner edge leans toward the orb.
 *
 * The wing is rotated on Y inside an 800 px perspective, so its inner edge
 * comes toward the viewer and projects wider than the flat box. This returns
 * that extra width in CSS pixels.
 */
export function tiltExtension(width: number, angleDeg: number = TILT_DEG): number {
  const rad = (angleDeg * Math.PI) / 180
  const z = width * Math.sin(rad)
  const scale = PERSPECTIVE / (PERSPECTIVE - z)
  return width * (Math.cos(rad) * scale - 1)
}

export interface Frame {
  /** Total assembly width — in Tauri, the native window width. */
  width: number
  /** Total assembly height — in Tauri, the native window height. */
  height: number
  /** Chat wing width plus its tilt lean. 0 when the chat wing is shut. */
  chatSide: number
  /** Dashboard wing width plus its tilt lean. 0 when the dashboard is shut. */
  dashSide: number
  /** Orb centre, measured from the left edge of the frame. */
  orbCenterX: number
  /** Orb centre, measured from the top edge of the frame. */
  orbCenterY: number
}

/**
 * The frame for one (layout, spotlight, navigation level) combination.
 *
 * `level` is the NavigationContext level. Level 3 replaces the orb with
 * WheelView, which is why it gets its own size.
 */
export function computeFrame(
  ui: UIStr,
  spotlight: SpotlightStr,
  level: number = 1,
): Frame {
  if (level >= 3) {
    return {
      width: WHEEL_W,
      height: WHEEL_H,
      chatSide: 0,
      dashSide: 0,
      orbCenterX: WHEEL_W / 2,
      orbCenterY: WHEEL_H / 2,
    }
  }

  if (ui === 'idle') {
    return {
      width: IDLE_W,
      height: IDLE_H,
      chatSide: 0,
      dashSide: 0,
      orbCenterX: IDLE_W / 2,
      orbCenterY: IDLE_H / 2,
    }
  }

  const chatOpen = ui === 'chat_open' || ui === 'both_open'
  const dashOpen = ui === 'dashboard_open' || ui === 'both_open'

  const cw = chatOpen ? chatWidth(spotlight) : 0
  const dw = dashOpen ? dashboardWidth(spotlight) : 0

  // A spotlighted wing renders flat — getSpotlightTransform returns
  // rotateY(0deg) for it — so it leans by nothing and needs no extension.
  const chatSide = chatOpen
    ? cw + (spotlight === 'chatSpotlight' ? 0 : tiltExtension(cw))
    : 0
  const dashSide = dashOpen
    ? dw + (spotlight === 'dashboardSpotlight' ? 0 : tiltExtension(dw))
    : 0

  const width = chatSide + ORB_BAND + dashSide

  return {
    width,
    height: WING_H,
    chatSide,
    dashSide,
    orbCenterX: chatSide + ORB_BAND / 2,
    orbCenterY: WING_H / 2,
  }
}

/**
 * Left edge of the frame inside the viewport.
 *
 * Tauri sizes the window to the frame, so this is 0 there and every wing pins
 * flush to a window edge. A browser viewport is usually wider, so the same
 * frame is centred in it.
 *
 * The result is deliberately NOT clamped to 0. A browser window narrower than
 * the frame — 1280 px against the 1400 px both-open frame — is the only case
 * that goes negative, and clamping it put the whole 120 px shortfall on the
 * right wing, which then covered the orb. Letting it go negative hangs both
 * wings equally off the two edges and keeps the orb exactly between them.
 */
export function frameLeft(viewportWidth: number, frameWidth: number): number {
  return (viewportWidth - frameWidth) / 2
}

/**
 * How far the orb's centre sits from the centre of the viewport. The ambient
 * crawl tier is positioned from the viewport centre, so it needs this to
 * follow the orb when one wing is open and the orb is off to one side.
 */
export function orbCenterOffsetX(frame: Frame): number {
  return (frame.chatSide - frame.dashSide) / 2
}
