"use client";

import {
  Activity,
  FolderGit2,
  Fingerprint,
  LayoutDashboard,
  Network,
  HardDrive,
  Wrench,
  Settings,
  Github,
} from "lucide-react";
import { NavLink } from "@/components/launcher/NavLink";
import { useApp } from "@/contexts/LauncherContext";
import { useBrandColor } from "@/contexts/BrandColorContext";
import { useLauncherMode } from "@/hooks/useLauncherMode";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarHeader,
  SidebarFooter,
  useSidebar,
} from "@/components/ui/sidebar";

const mainItems = [
  { title: "Overview", url: "/launcher/overview", icon: LayoutDashboard },
  { title: "Identity", url: "/launcher/identity", icon: Fingerprint },
  { title: "Projects", url: "/launcher/projects", icon: HardDrive },
  { title: "Tailscale", url: "/launcher/tailscale", icon: Network },
  { title: "Settings", url: "/launcher/settings", icon: Settings },
];

const devItems = [
  { title: "GitHub", url: "/launcher/github", icon: Github },
  { title: "Git & Source", url: "/launcher/git", icon: FolderGit2 },
  { title: "Diff Review", url: "/launcher/diff-review", icon: Activity },
  { title: "Rebuild", url: "/launcher/rebuild", icon: Wrench },
];

export function AppSidebar() {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const { mode: appMode } = useApp();
  const { mode: backendMode } = useLauncherMode();
  const effectiveMode = appMode || backendMode;
  const router = useRouter();
  const { getThemeConfig } = useBrandColor();
  const glowColor = getThemeConfig().glow.color || "#00d4ff";

  return (
    <Sidebar
      collapsible="icon"
      aria-label="Main navigation"
      className="border-r border-sidebar-border bg-sidebar"
    >
      <SidebarHeader className="p-5 pb-4">
        {!collapsed && (
          <div className="flex items-center gap-3">
            <motion.div
              className="h-9 w-9 rounded-xl flex items-center justify-center"
              style={{
                background: `${glowColor}18`,
                border: `1px solid ${glowColor}30`,
                boxShadow: `inset 0 1px 1px ${glowColor}20, 0 0 12px ${glowColor}20`,
              }}
              whileHover={{ scale: 1.08, rotate: 2 }}
              whileTap={{ scale: 0.95 }}
              transition={{ type: "spring", stiffness: 400, damping: 15 }}
            >
              <span className="font-mono text-sm font-bold" style={{ color: glowColor }}>IR</span>
            </motion.div>
            <div>
              <h2 className="text-sm font-semibold text-sidebar-foreground tracking-tight">IRIS Launcher</h2>
              <p className="text-[10px] text-sidebar-foreground/50 tracking-wide">
                {effectiveMode === "developer" ? "Developer" : "Personal"}
              </p>
            </div>
          </div>
        )}
        {collapsed && (
          <div className="flex justify-center">
            <motion.div
              className="h-9 w-9 rounded-xl flex items-center justify-center"
              style={{
                background: `${glowColor}18`,
                border: `1px solid ${glowColor}30`,
                boxShadow: `inset 0 1px 1px ${glowColor}20, 0 0 12px ${glowColor}20`,
              }}
              whileHover={{ scale: 1.1 }}
              transition={{ type: "spring", stiffness: 400, damping: 15 }}
            >
              <span className="font-mono text-xs font-bold" style={{ color: glowColor }}>IR</span>
            </motion.div>
          </div>
        )}
      </SidebarHeader>

      <SidebarContent className="flex flex-col gap-4 py-4 pb-6">
        <SidebarGroup className="flex-shrink-0">
          <SidebarGroupLabel className="text-[10px] font-medium uppercase tracking-[0.15em] text-sidebar-foreground/40 px-3 mb-2">
            System
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-2">
              {mainItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild className="h-10">
                    <NavLink
                      to={item.url}
                      end
                      aria-label={item.title}
                      className="text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground rounded-xl transition-all duration-200"
                      activeClassName="bg-sidebar-accent text-sidebar-accent-foreground font-medium shadow-none"
                    >
                      <item.icon className="mr-2.5 h-4 w-4" aria-hidden="true" />
                      {!collapsed && <span className="text-sm tracking-wide">{item.title}</span>}
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="flex-shrink-0">
          <SidebarGroupLabel className="text-[10px] font-medium uppercase tracking-[0.15em] text-sidebar-foreground/40 px-3 mb-2">
            Developer
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-2">
              {devItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild className="h-10">
                    <NavLink
                      to={item.url}
                      end
                      aria-label={item.title}
                      className="text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground rounded-xl transition-all duration-200"
                      activeClassName="bg-sidebar-accent text-sidebar-accent-foreground font-medium shadow-none"
                    >
                      <item.icon className="mr-2.5 h-4 w-4" aria-hidden="true" />
                      {!collapsed && <span className="text-sm tracking-wide">{item.title}</span>}
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <div className="flex-1 min-h-0" />
      </SidebarContent>

      <SidebarFooter className="p-4 mt-auto" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
        {!collapsed && (
          <div className="space-y-4">
            <button
              aria-label="Switch application mode"
              onClick={() => router.push("/mode-select")}
              className="flex items-center gap-2.5 text-[11px] text-sidebar-foreground/50 hover:text-sidebar-foreground/80 transition-colors w-full tracking-wide px-2 py-2 rounded-lg hover:bg-sidebar-accent"
            >
              <Settings className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Switch Mode</span>
            </button>
            <div className="flex items-center gap-2.5 text-[11px] text-sidebar-foreground/50 px-2" aria-label="System status: Healthy">
              <motion.div
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: '#22c55e' }}
                animate={{ opacity: [1, 0.4, 1] }}
                transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                aria-hidden="true"
              />
              <span>System Healthy</span>
            </div>
          </div>
        )}
        {collapsed && (
          <div className="flex justify-center">
            <motion.div
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: '#22c55e' }}
              animate={{ opacity: [1, 0.4, 1] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
              aria-label="System status: Healthy"
            />
          </div>
        )}
      </SidebarFooter>
    </Sidebar>
  );
}
