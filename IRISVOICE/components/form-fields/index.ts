/**
 * Form Fields Barrel Export
 * 
 * This index.ts provides explicit exports for the general form field components.
 * These are distinct from IRISVOICE/components/wheel-view/fields to avoid conflicts.
 * 
 * Key differences from wheel-view fields:
 * - Default exports
 * - Props include 'description' and 'error' for form validation
 * - Uses FieldWrapper component for consistent styling
 * - Uses useBrandColor context for theming
 */

export { FieldWrapper } from "./FieldWrapper"
export { TextField } from "./TextField"
export { SliderField } from "./SliderField"
export { DropdownField } from "./DropdownField"
export { ToggleField } from "./ToggleField"
export { ColorField } from "./ColorField"
export { CompactSlider } from "./CompactSlider"
export { DeviceRow } from "./DeviceRow"
export { ToggleRow } from "./ToggleRow"
