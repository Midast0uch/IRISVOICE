/**
 * injectDropdownStyles
 *
 * Injects a single shared <style> block for the `.iris-select` class.
 * Must be called before any iris-select element renders (safe to call multiple times).
 *
 * Design: transparent by default, brand-color highlight on hover/focus.
 * The brand glow is supplied via the CSS custom property --glow on each element.
 */
const STYLE_ID = "iris-dropdown-hover-style"

export function injectDropdownStyles(): void {
  if (typeof document === "undefined") return
  if (document.getElementById(STYLE_ID)) return

  const s = document.createElement("style")
  s.id = STYLE_ID
  s.textContent = `
    .iris-select {
      background: transparent;
      border: 1px solid rgba(255,255,255,0.08);
      transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
    }
    .iris-select:hover {
      background: color-mix(in srgb, var(--glow, #8b5cf6) 14%, rgba(0,0,0,0.2));
      border-color: color-mix(in srgb, var(--glow, #8b5cf6) 45%, rgba(255,255,255,0.15));
      box-shadow: 0 0 10px color-mix(in srgb, var(--glow, #8b5cf6) 12%, transparent);
    }
    .iris-select:focus {
      background: color-mix(in srgb, var(--glow, #8b5cf6) 10%, rgba(0,0,0,0.25));
      border-color: color-mix(in srgb, var(--glow, #8b5cf6) 65%, rgba(255,255,255,0.2));
      box-shadow: 0 0 14px color-mix(in srgb, var(--glow, #8b5cf6) 20%, transparent);
      outline: none;
    }
    .iris-select:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
  `
  document.head.appendChild(s)
}
