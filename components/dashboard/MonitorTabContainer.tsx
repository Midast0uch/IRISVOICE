"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BarChart3, Terminal, Stethoscope } from "lucide-react";
import { MonitorAnalyticsPanel } from "./MonitorAnalyticsPanel";
import { MonitorLogsPanel } from "./MonitorLogsPanel";
import { MonitorDiagnosticsPanel } from "./MonitorDiagnosticsPanel";

type SubTab = "analytics" | "logs" | "diagnostics";

interface MonitorTabContainerProps {
  glowColor?: string;
  fontColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
}

const TABS: { id: SubTab; label: string; icon: any }[] = [
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "logs", label: "Logs", icon: Terminal },
  { id: "diagnostics", label: "Diagnostics", icon: Stethoscope },
];

export function MonitorTabContainer({
  glowColor = "#00d4ff",
  fontColor = "white",
  sendMessage,
}: MonitorTabContainerProps) {
  const [activeTab, setActiveTab] = useState<SubTab>("analytics");

  return (
    <div className="w-full h-full flex flex-col">
      {/* Sub-tab bar */}
      <div
        className="flex items-center gap-0 flex-shrink-0 relative border-b"
        style={{ borderColor: `${glowColor}10` }}
      >
        {TABS.map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="relative flex items-center justify-center gap-1.5 px-2 py-2 transition-all duration-200 flex-1 min-w-0"
              style={{
                color: isActive ? glowColor : "rgba(255,255,255,0.3)",
              }}
            >
              <Icon size={11} style={{ color: isActive ? glowColor : "rgba(255,255,255,0.25)" }} />
              <span className="text-[10px] font-bold uppercase tracking-wider truncate">{tab.label}</span>
              {isActive && tab.id === "analytics" && (
                <>
                  <motion.div
                    className="w-[5px] h-[5px] rounded-full"
                    style={{ background: glowColor }}
                    animate={{ opacity: [1, 0.3, 1] }}
                    transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                  />
                  <span className="text-[8px] font-bold uppercase tracking-wider" style={{ color: `${glowColor}90` }}>
                    Live
                  </span>
                </>
              )}
              {isActive && (
                <motion.div
                  layoutId="monitor-subtab-indicator"
                  className="absolute bottom-0 left-0 right-0 h-[2px]"
                  style={{
                    background: `linear-gradient(90deg, transparent, ${glowColor}, transparent)`,
                    boxShadow: `0 0 8px ${glowColor}80`,
                  }}
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                />
              )}
              {/* Hover glow */}
              {!isActive && (
                <div
                  className="absolute inset-0 opacity-0 hover:opacity-100 transition-opacity duration-200 pointer-events-none"
                  style={{ background: `${glowColor}05` }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-hidden relative">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ duration: 0.2 }}
            className="w-full h-full"
          >
            {activeTab === "analytics" && (
              <MonitorAnalyticsPanel glowColor={glowColor} fontColor={fontColor} sendMessage={sendMessage} />
            )}
            {activeTab === "logs" && (
              <MonitorLogsPanel glowColor={glowColor} fontColor={fontColor} sendMessage={sendMessage} />
            )}
            {activeTab === "diagnostics" && (
              <MonitorDiagnosticsPanel glowColor={glowColor} fontColor={fontColor} sendMessage={sendMessage} />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

export default MonitorTabContainer;
