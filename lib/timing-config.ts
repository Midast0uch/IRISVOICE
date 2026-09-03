export const ENERGY_CYCLE = {
    duration: 8,
    segments: {
        s2Wheel: { start: 0.0, end: 0.375, label: "S2_WHEEL" },      // 0.0s - 3.0s (3/8 = 0.375)
        c2Forward: { start: 0.375, end: 0.5, label: "C2_FORWARD" },    // 3.0s - 4.0s (4/8 = 0.5)
        ss2Panel: { start: 0.5, end: 0.875, label: "SS2_PANEL" },     // 4.0s - 7.0s (7/8 = 0.875)
        c2Return: { start: 0.875, end: 1.0, label: "C2_RETURN" },     // 7.0s - 8.0s (8/8 = 1.0)
    }
} as const;

export const toFramerTimes = (segment: typeof ENERGY_CYCLE.segments.s2Wheel) => [
    segment.start,
    segment.start,
    segment.end,
    segment.end
];
