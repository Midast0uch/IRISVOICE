/**
 * Utility functions for color manipulation and WCAG contrast compliance.
 */

/**
 * Converts a hex color to rgba with specified alpha.
 * Supports #RRGGBB and RRGGBB formats.
 */
export function hexToRgba(hex: string, alpha: number): string {
    let r = 0, g = 0, b = 0;

    // Clean hex string
    const cleanHex = hex.replace("#", "");

    if (cleanHex.length === 6) {
        r = parseInt(cleanHex.substring(0, 2), 16);
        g = parseInt(cleanHex.substring(2, 4), 16);
        b = parseInt(cleanHex.substring(4, 6), 16);
    } else if (cleanHex.length === 3) {
        r = parseInt(cleanHex[0] + cleanHex[0], 16);
        g = parseInt(cleanHex[1] + cleanHex[1], 16);
        b = parseInt(cleanHex[2] + cleanHex[2], 16);
    } else {
        // Fallback to a neutral value
        return `rgba(255, 255, 255, ${alpha})`;
    }

    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Basic luminance calculation
 */
function getLuminance(r: number, g: number, b: number): number {
    const [rs, gs, bs] = [r, g, b].map(c => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

/**
 * Get contrast ratio between two hex colors
 */
export function getContrastRatio(hex1: string, hex2: string): number {
    const getRGB = (hex: string) => {
        const clean = hex.replace("#", "");
        return [
            parseInt(clean.substring(0, 2), 16),
            parseInt(clean.substring(2, 4), 16),
            parseInt(clean.substring(4, 6), 16)
        ];
    };

    const lum1 = getLuminance(...(getRGB(hex1) as [number, number, number]));
    const lum2 = getLuminance(...(getRGB(hex2) as [number, number, number]));

    const brightest = Math.max(lum1, lum2);
    const darkest = Math.min(lum1, lum2);

    return (brightest + 0.05) / (darkest + 0.05);
}
