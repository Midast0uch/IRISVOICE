"use client"

import React from "react";
import { motion } from "framer-motion";
import { MessageSquare, Bot, Wrench, Clock, Sparkles } from "lucide-react";

export type ActivityType = "conversation" | "action" | "tool" | "skill";

export interface ActivityItem {
  id: string;
  type: ActivityType;
  title: string;
  description?: string;
  timestamp: Date;
  metadata?: Record<string, any>;
}

interface ActivityPanelProps {
  glowColor?: string;
  fontColor?: string;
  activities?: ActivityItem[];
  maxItems?: number;
}

const getActivityIcon = (type: ActivityType, glowColor: string) => {
  const iconProps = { size: 14, style: { color: glowColor } };
  switch (type) {
    case "conversation":
      return <MessageSquare {...iconProps} />;
    case "action":
      return <Bot {...iconProps} />;
    case "tool":
      return <Wrench {...iconProps} />;
    case "skill":
      return <Sparkles {...iconProps} />;
    default:
      return <Clock {...iconProps} />;
  }
};

const getActivityTypeLabel = (type: ActivityType): string => {
  switch (type) {
    case "conversation":
      return "Conversation";
    case "action":
      return "Agent Action";
    case "tool":
      return "Tool Used";
    case "skill":
      return "Skill";
    default:
      return "Activity";
  }
};

const formatTimestamp = (date: Date): string => {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
};

export function ActivityPanel({
  glowColor = "#00d4ff",
  fontColor = "#ffffff",
  activities = [],
  maxItems = 15,
}: ActivityPanelProps) {
  const displayActivities = activities.slice(0, maxItems);
  const hasActivities = displayActivities.length > 0;

  return (
    <div className="h-full flex flex-col p-3">
      {/* Header */}
      <div
        className="flex items-center justify-between mb-3 pb-2 border-b"
        style={{ borderColor: `${glowColor}15` }}
      >
        <span
          className="text-[11px] font-semibold tracking-wide uppercase"
          style={{ color: `${fontColor}70` }}
        >
          Recent Activity
        </span>
        {hasActivities && (
          <span className="text-[9px]" style={{ color: `${fontColor}40` }}>
            {displayActivities.length} items
          </span>
        )}
      </div>

      {/* Activity List */}
      <div className="flex-1 overflow-y-auto space-y-0">
        {!hasActivities ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3 }}
            >
              <Clock
                size={28}
                style={{ color: `${glowColor}30` }}
                className="mx-auto mb-2"
              />
              <p className="text-[12px]" style={{ color: `${fontColor}40` }}>
                No recent activity
              </p>
              <p className="text-[9px] mt-1" style={{ color: `${fontColor}25` }}>
                Conversations and agent actions will appear here
              </p>
            </motion.div>
          </div>
        ) : (
          displayActivities.map((activity, index) => (
            <motion.div
              key={activity.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
              className="group"
            >
              <div className="flex items-start gap-2.5 py-2.5 px-2 rounded-lg transition-colors hover:bg-white/[0.03]">
                {/* Icon */}
                <div
                  className="flex-shrink-0 w-6 h-6 rounded-md flex items-center justify-center"
                  style={{ backgroundColor: `${glowColor}10` }}
                >
                  {getActivityIcon(activity.type, glowColor)}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span
                      className="text-[9px] font-medium tracking-wide uppercase"
                      style={{ color: `${glowColor}70` }}
                    >
                      {getActivityTypeLabel(activity.type)}
                    </span>
                    <span className="text-[8px]" style={{ color: `${fontColor}25` }}>
                      •
                    </span>
                    <span className="text-[8px]" style={{ color: `${fontColor}35` }}>
                      {formatTimestamp(activity.timestamp)}
                    </span>
                  </div>
                  <p
                    className="text-[11px] font-medium truncate"
                    style={{ color: `${fontColor}90` }}
                  >
                    {activity.title}
                  </p>
                  {activity.description && (
                    <p
                      className="text-[9px] mt-0.5 line-clamp-2"
                      style={{ color: `${fontColor}50` }}
                    >
                      {activity.description}
                    </p>
                  )}
                </div>
              </div>

              {/* Divider line (not for last item) */}
              {index < displayActivities.length - 1 && (
                <div
                  className="h-px mx-2"
                  style={{ backgroundColor: `${glowColor}08` }}
                />
              )}
            </motion.div>
          ))
        )}
      </div>

      {/* Footer - Connect to memory hint */}
      {hasActivities && (
        <div
          className="mt-2 pt-2 border-t text-center"
          style={{ borderColor: `${glowColor}08` }}
        >
          <span className="text-[8px]" style={{ color: `${fontColor}25` }}>
            Connected to episodic memory
          </span>
        </div>
      )}
    </div>
  );
}

export default ActivityPanel;
