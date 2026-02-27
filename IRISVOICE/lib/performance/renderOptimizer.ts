/**
 * Frontend Rendering Optimizer
 * Ensures UI updates render within 16ms (60 FPS) with React optimizations.
 */

import { useCallback, useMemo, useRef, useEffect } from 'react';

/**
 * Performance metrics for rendering
 */
export interface RenderMetrics {
  frameTime: number;
  fps: number;
  droppedFrames: number;
}

/**
 * Hook to monitor render performance
 */
export function useRenderMetrics(): RenderMetrics {
  const frameTimeRef = useRef<number>(0);
  const lastFrameRef = useRef<number>(performance.now());
  const fpsRef = useRef<number>(60);
  const droppedFramesRef = useRef<number>(0);
  
  useEffect(() => {
    let animationFrameId: number;
    
    const measureFrame = () => {
      const now = performance.now();
      const frameTime = now - lastFrameRef.current;
      
      frameTimeRef.current = frameTime;
      fpsRef.current = 1000 / frameTime;
      
      // Count dropped frames (>16.67ms = missed 60fps target)
      if (frameTime > 16.67) {
        droppedFramesRef.current++;
      }
      
      lastFrameRef.current = now;
      animationFrameId = requestAnimationFrame(measureFrame);
    };
    
    animationFrameId = requestAnimationFrame(measureFrame);
    
    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, []);
  
  return {
    frameTime: frameTimeRef.current,
    fps: fpsRef.current,
    droppedFrames: droppedFramesRef.current,
  };
}

/**
 * Debounce hook for high-frequency updates
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = React.useState<T>(value);
  
  React.useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);
    
    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);
  
  return debouncedValue;
}

/**
 * Throttle hook for limiting update frequency
 */
export function useThrottle<T>(value: T, interval: number): T {
  const [throttledValue, setThrottledValue] = React.useState<T>(value);
  const lastUpdated = useRef<number>(Date.now());
  
  React.useEffect(() => {
    const now = Date.now();
    
    if (now >= lastUpdated.current + interval) {
      lastUpdated.current = now;
      setThrottledValue(value);
    } else {
      const timerId = setTimeout(() => {
        lastUpdated.current = Date.now();
        setThrottledValue(value);
      }, interval - (now - lastUpdated.current));
      
      return () => clearTimeout(timerId);
    }
  }, [value, interval]);
  
  return throttledValue;
}

/**
 * Optimized callback that only changes when dependencies change
 */
export function useOptimizedCallback<T extends (...args: any[]) => any>(
  callback: T,
  deps: React.DependencyList
): T {
  return useCallback(callback, deps);
}

/**
 * Optimized memo that only recomputes when dependencies change
 */
export function useOptimizedMemo<T>(
  factory: () => T,
  deps: React.DependencyList
): T {
  return useMemo(factory, deps);
}

/**
 * Request animation frame hook for smooth animations
 */
export function useAnimationFrame(callback: (deltaTime: number) => void) {
  const requestRef = useRef<number>();
  const previousTimeRef = useRef<number>();
  
  useEffect(() => {
    const animate = (time: number) => {
      if (previousTimeRef.current !== undefined) {
        const deltaTime = time - previousTimeRef.current;
        callback(deltaTime);
      }
      previousTimeRef.current = time;
      requestRef.current = requestAnimationFrame(animate);
    };
    
    requestRef.current = requestAnimationFrame(animate);
    return () => {
      if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
      }
    };
  }, [callback]);
}

/**
 * Batch state updates to reduce re-renders
 */
export function useBatchedUpdates() {
  const pendingUpdates = useRef<Array<() => void>>([]);
  const timeoutRef = useRef<NodeJS.Timeout>();
  
  const batchUpdate = useCallback((update: () => void) => {
    pendingUpdates.current.push(update);
    
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    
    timeoutRef.current = setTimeout(() => {
      // Execute all pending updates in a single batch
      React.startTransition(() => {
        pendingUpdates.current.forEach(fn => fn());
        pendingUpdates.current = [];
      });
    }, 0);
  }, []);
  
  return batchUpdate;
}

/**
 * Virtual scrolling helper for large lists
 */
export function useVirtualScroll<T>(
  items: T[],
  itemHeight: number,
  containerHeight: number
) {
  const [scrollTop, setScrollTop] = React.useState(0);
  
  const visibleRange = useMemo(() => {
    const startIndex = Math.floor(scrollTop / itemHeight);
    const endIndex = Math.ceil((scrollTop + containerHeight) / itemHeight);
    
    return {
      start: Math.max(0, startIndex - 5), // Buffer
      end: Math.min(items.length, endIndex + 5), // Buffer
    };
  }, [scrollTop, itemHeight, containerHeight, items.length]);
  
  const visibleItems = useMemo(() => {
    return items.slice(visibleRange.start, visibleRange.end);
  }, [items, visibleRange]);
  
  const totalHeight = items.length * itemHeight;
  const offsetY = visibleRange.start * itemHeight;
  
  return {
    visibleItems,
    totalHeight,
    offsetY,
    onScroll: (e: React.UIEvent<HTMLElement>) => {
      setScrollTop(e.currentTarget.scrollTop);
    },
  };
}

/**
 * Performance monitoring utility
 */
export class PerformanceMonitor {
  private static instance: PerformanceMonitor;
  private metrics: Map<string, number[]> = new Map();
  
  static getInstance(): PerformanceMonitor {
    if (!PerformanceMonitor.instance) {
      PerformanceMonitor.instance = new PerformanceMonitor();
    }
    return PerformanceMonitor.instance;
  }
  
  mark(name: string) {
    performance.mark(name);
  }
  
  measure(name: string, startMark: string, endMark: string) {
    performance.measure(name, startMark, endMark);
    const measure = performance.getEntriesByName(name, 'measure')[0];
    
    if (measure) {
      if (!this.metrics.has(name)) {
        this.metrics.set(name, []);
      }
      this.metrics.get(name)!.push(measure.duration);
    }
  }
  
  getMetrics(name: string): { mean: number; p95: number; max: number } | null {
    const samples = this.metrics.get(name);
    if (!samples || samples.length === 0) {
      return null;
    }
    
    const sorted = [...samples].sort((a, b) => a - b);
    const mean = samples.reduce((a, b) => a + b, 0) / samples.length;
    const p95 = sorted[Math.floor(sorted.length * 0.95)];
    const max = sorted[sorted.length - 1];
    
    return { mean, p95, max };
  }
  
  clear() {
    this.metrics.clear();
    performance.clearMarks();
    performance.clearMeasures();
  }
}

/**
 * React component wrapper for performance monitoring
 */
export function withPerformanceMonitoring<P extends object>(
  Component: React.ComponentType<P>,
  componentName: string
): React.ComponentType<P> {
  return (props: P) => {
    const monitor = PerformanceMonitor.getInstance();
    
    useEffect(() => {
      monitor.mark(`${componentName}-mount-start`);
      return () => {
        monitor.mark(`${componentName}-mount-end`);
        monitor.measure(
          `${componentName}-mount`,
          `${componentName}-mount-start`,
          `${componentName}-mount-end`
        );
      };
    }, []);
    
    useEffect(() => {
      monitor.mark(`${componentName}-render`);
    });
    
    return <Component {...props} />;
  };
}

// Add React import at the top
import * as React from 'react';
