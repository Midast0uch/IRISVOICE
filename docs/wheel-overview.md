# WheelView Architecture — Redirected

This document has been superseded by the Hex Pattern Wheel View design document.

**→ See: [docs/Design/Hex-Pattern-Wheel-View.md](./Design/Hex-Pattern-Wheel-View.md)**

The `DualRingMechanism` (liquid metal surface) has been replaced by
`HexPatternRingMechanism` (hex pattern surface) as of 2026-06-19.

Key changes:
- Segment rendering: liquid metal gradients → honeycomb SVG pattern + neon edge
- Center button: liquid metal conic gradient → hex pattern neon edge + honeycomb texture
- ConnectionLine: added hex pattern texture overlay (layer 5)
- SVG filters: removed GPU-expensive `feSpecularLighting` — pattern provides texture
- All kinetic gliders, energy beams, orbital ticks, and spring physics are unchanged

For the complete architecture reference, layer stack, and interaction specs,
see the new design document linked above.

---

*Last Updated: 2026-06-19*
