/**
 * Wheel-View Fields Barrel Export
 * 
 * This index.ts provides explicit exports for the wheel-view field components.
 * These are distinct from the general IRISVOICE/components/fields to avoid conflicts.
 * 
 * Key differences from general fields:
 * - Named exports with React.memo optimization
 * - Props include 'id' and 'glowColor' for wheel-view styling
 * - Self-contained components (no FieldWrapper dependency)
 */

export { ToggleField } from "./ToggleField"
export { SliderField } from "./SliderField"
export { DropdownField } from "./DropdownField"
export { TextField } from "./TextField"
export { ColorField } from "./ColorField"
