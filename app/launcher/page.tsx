"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LauncherIndexPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/launcher/settings");
  }, [router]);
  return (
    <div className="flex items-center justify-center h-full">
      <div className="animate-pulse text-sm text-muted-foreground">Loading IRIS Launcher…</div>
    </div>
  );
}
