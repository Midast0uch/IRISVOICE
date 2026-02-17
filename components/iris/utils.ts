
import { useState, useEffect } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  return isMobile;
}

export function makeVibrant(color: string, intensity: number = 0.3): string {
  // This function was previously defined in hexagonal-control-center.tsx
  // Placeholder - actual implementation depends on color parsing/manipulation library
  return color; 
}

export function getSpiralPosition(index: number, total: number, radius: number) {
  // This function was previously defined in hexagonal-control-center.tsx
  // Placeholder - actual implementation depends on the desired spiral calculation
  const angle = (index / total) * Math.PI * 2;
  const x = Math.cos(angle) * radius;
  const y = Math.sin(angle) * radius;
  return { x, y };
}

export async function startWindowDrag() {
  try {
    const window = getCurrentWindow();
    await window.startDragging();
  } catch (error) {
    console.error("Failed to start window drag:", error);
  }
}
