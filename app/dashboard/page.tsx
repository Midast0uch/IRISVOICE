'use client';

import { lazy, Suspense } from 'react';

// Lazy load the heavy DarkGlassDashboard component (named export)
const LazyDarkGlassDashboard = lazy(() => 
  import('@/components/dark-glass-dashboard').then(module => ({ default: module.DarkGlassDashboard }))
);

// This is a dedicated page for the dashboard window.
export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="text-white p-4">Loading dashboard...</div>}>
      <LazyDarkGlassDashboard />
    </Suspense>
  );
}
