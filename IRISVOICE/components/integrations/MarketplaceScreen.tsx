"use client"

import React, { useState, useCallback, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Search, Sparkles, Download, Star, Shield, ExternalLink, X, Filter, Grid3X3, List, ThumbsUp } from "lucide-react"
import { useNavigation } from "@/contexts/NavigationContext"
import { useIntegrationsContext, type RecommendedIntegration } from "@/contexts/IntegrationsContext"

export interface MarketplaceIntegration {
  id: string
  name: string
  description: string
  icon: string
  category: "email" | "messaging" | "productivity" | "developer" | "other"
  publisher: string
  rating: number
  installCount: number
  verified: boolean
  installed: boolean
  featured?: boolean
}

interface MarketplaceScreenProps {
  glowColor?: string
  fontColor?: string
  onInstall?: (integration: MarketplaceIntegration) => void
  onClose?: () => void
}

const CATEGORIES: { id: string; label: string; icon: string }[] = [
  { id: "all", label: "All", icon: "⊞" },
  { id: "email", label: "Email", icon: "@" },
  { id: "messaging", label: "Messaging", icon: "💬" },
  { id: "productivity", label: "Productivity", icon: "⚡" },
  { id: "developer", label: "Developer", icon: "</>" },
  { id: "other", label: "Other", icon: "•••" },
]

const MOCK_INTEGRATIONS: MarketplaceIntegration[] = [
  {
    id: "gmail",
    name: "Gmail",
    description: "Send, read, and manage emails through your Gmail account",
    icon: "📧",
    category: "email",
    publisher: "Google",
    rating: 4.8,
    installCount: 125000,
    verified: true,
    installed: true,
    featured: true,
  },
  {
    id: "outlook",
    name: "Outlook",
    description: "Microsoft 365 email and calendar integration",
    icon: "📧",
    category: "email",
    publisher: "Microsoft",
    rating: 4.6,
    installCount: 89000,
    verified: true,
    installed: false,
    featured: true,
  },
  {
    id: "telegram",
    name: "Telegram",
    description: "Send and receive messages through Telegram",
    icon: "✈️",
    category: "messaging",
    publisher: "Telegram",
    rating: 4.7,
    installCount: 67000,
    verified: true,
    installed: false,
  },
  {
    id: "discord",
    name: "Discord",
    description: "Send messages to Discord channels via bot",
    icon: "🎮",
    category: "messaging",
    publisher: "Discord",
    rating: 4.5,
    installCount: 45000,
    verified: true,
    installed: false,
  },
  {
    id: "slack",
    name: "Slack",
    description: "Post messages to Slack workspaces",
    icon: "💬",
    category: "messaging",
    publisher: "Slack",
    rating: 4.6,
    installCount: 52000,
    verified: true,
    installed: false,
    featured: true,
  },
  {
    id: "notion",
    name: "Notion",
    description: "Create and update pages in your Notion workspace",
    icon: "📝",
    category: "productivity",
    publisher: "Notion",
    rating: 4.7,
    installCount: 38000,
    verified: true,
    installed: false,
  },
  {
    id: "linear",
    name: "Linear",
    description: "Create and manage issues in Linear",
    icon: "⚡",
    category: "developer",
    publisher: "Linear",
    rating: 4.8,
    installCount: 22000,
    verified: true,
    installed: false,
  },
  {
    id: "github",
    name: "GitHub",
    description: "Create issues, search repositories, and more",
    icon: "🐙",
    category: "developer",
    publisher: "GitHub",
    rating: 4.9,
    installCount: 94000,
    verified: true,
    installed: false,
    featured: true,
  },
]

function formatInstallCount(count: number): string {
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`
  if (count >= 1000) return `${(count / 1000).toFixed(0)}k`
  return count.toString()
}

export function MarketplaceScreen({
  glowColor = "#00d4ff",
  fontColor = "#ffffff",
  onInstall,
  onClose,
}: MarketplaceScreenProps) {
  const { activeTheme } = useNavigation()
  const { recommendations: contextRecommendations, getRecommendations, storePreference, preferencesLoading } = useIntegrationsContext()
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedCategory, setSelectedCategory] = useState<string>("all")
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid")
  const [isLoading, setIsLoading] = useState(false)
  const [integrations, setIntegrations] = useState<MarketplaceIntegration[]>(MOCK_INTEGRATIONS)

  // Fetch recommendations on mount
  useEffect(() => {
    getRecommendations()
  }, [getRecommendations])

  // Store category preference when user browses
  const handleCategoryChange = useCallback((categoryId: string) => {
    setSelectedCategory(categoryId)
    if (categoryId !== "all") {
      storePreference("category_viewed", categoryId, { timestamp: Date.now() })
    }
  }, [storePreference])

  // Filter integrations based on search and category
  const filteredIntegrations = integrations.filter((integration) => {
    const matchesSearch = 
      integration.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      integration.description.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesCategory = selectedCategory === "all" || integration.category === selectedCategory
    return matchesSearch && matchesCategory
  })

  const featuredIntegrations = filteredIntegrations.filter((i) => i.featured)
  const regularIntegrations = filteredIntegrations.filter((i) => !i.featured)

  const handleInstall = useCallback((integration: MarketplaceIntegration) => {
    onInstall?.(integration)
  }, [onInstall])

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div
        className="h-14 flex items-center justify-between px-4 border-b flex-shrink-0"
        style={{ borderColor: `${glowColor}15` }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: `${glowColor}15` }}
          >
            <Sparkles size={16} style={{ color: glowColor }} />
          </div>
          <div>
            <h2
              className="text-[14px] font-semibold"
              style={{ color: fontColor }}
            >
              Marketplace
            </h2>
            <p className="text-[10px]" style={{ color: `${fontColor}50` }}>
              Discover and install integrations
            </p>
          </div>
        </div>

        {onClose && (
          <button
            onClick={onClose}
            className="p-2 rounded-lg transition-all duration-150"
            style={{ color: `${fontColor}50` }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = fontColor
              e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.05)"
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = `${fontColor}50`
              e.currentTarget.style.backgroundColor = "transparent"
            }}
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* Search Bar */}
      <div className="px-4 py-3 flex-shrink-0">
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg border"
          style={{
            backgroundColor: "rgba(0,0,0,0.2)",
            borderColor: `${glowColor}20`,
          }}
        >
          <Search size={16} style={{ color: `${fontColor}40` }} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search integrations..."
            className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-white/30"
            style={{ color: fontColor }}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="p-1 rounded"
              style={{ color: `${fontColor}40` }}
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Category Tabs */}
      <div
        className="flex items-center gap-1 px-4 pb-3 border-b overflow-x-auto scrollbar-hide flex-shrink-0"
        style={{ borderColor: `${glowColor}10` }}
      >
        {CATEGORIES.map((category) => {
          const isActive = selectedCategory === category.id
          return (
            <button
              key={category.id}
              onClick={() => handleCategoryChange(category.id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium whitespace-nowrap transition-all duration-150"
              style={{
                color: isActive ? glowColor : `${fontColor}60`,
                backgroundColor: isActive ? `${glowColor}15` : "transparent",
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.color = `${fontColor}80`
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.color = `${fontColor}60`
              }}
            >
              <span>{category.icon}</span>
              {category.label}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Loading State */}
        {isLoading ? (
          <div className="flex items-center justify-center h-32">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
              className="w-6 h-6 border-2 border-t-transparent rounded-full"
              style={{ borderColor: `${glowColor}40`, borderTopColor: "transparent" }}
            />
          </div>
        ) : (
          <>
            {/* Featured Section */}
            {!searchQuery && selectedCategory === "all" && featuredIntegrations.length > 0 && (
              <div>
                <h3
                  className="text-[11px] font-semibold uppercase tracking-wider mb-3"
                  style={{ color: `${fontColor}60` }}
                >
                  Featured
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  {featuredIntegrations.map((integration) => (
                    <FeaturedCard
                      key={integration.id}
                      integration={integration}
                      glowColor={glowColor}
                      fontColor={fontColor}
                      onInstall={handleInstall}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Recommended Section */}
            {!searchQuery && selectedCategory === "all" && contextRecommendations.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <ThumbsUp size={12} style={{ color: glowColor }} />
                  <h3
                    className="text-[11px] font-semibold uppercase tracking-wider"
                    style={{ color: `${fontColor}60` }}
                  >
                    Recommended for You
                  </h3>
                </div>
                <div className={viewMode === "grid" ? "grid grid-cols-2 gap-3" : "space-y-2"}>
                  {contextRecommendations.slice(0, 4).map((rec) => (
                    <RecommendedCard
                      key={rec.integration_id}
                      recommendation={rec}
                      glowColor={glowColor}
                      fontColor={fontColor}
                      onInstall={() => {
                        const integration = integrations.find(i => i.id === rec.integration_id)
                        if (integration) handleInstall(integration)
                      }}
                      compact={viewMode === "list"}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* All Integrations */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3
                  className="text-[11px] font-semibold uppercase tracking-wider"
                  style={{ color: `${fontColor}60` }}
                >
                  {searchQuery ? "Search Results" : "All Integrations"}
                </h3>
                <span className="text-[10px]" style={{ color: `${fontColor}40` }}>
                  {filteredIntegrations.length} found
                </span>
              </div>

              <div className={viewMode === "grid" ? "grid grid-cols-2 gap-3" : "space-y-2"}>
                {regularIntegrations.map((integration) => (
                  <IntegrationCard
                    key={integration.id}
                    integration={integration}
                    glowColor={glowColor}
                    fontColor={fontColor}
                    onInstall={handleInstall}
                    compact={viewMode === "list"}
                  />
                ))}
              </div>

              {filteredIntegrations.length === 0 && (
                <div className="text-center py-12">
                  <Search size={32} style={{ color: `${glowColor}30` }} className="mx-auto mb-3" />
                  <p className="text-[12px]" style={{ color: `${fontColor}50` }}>
                    No integrations found
                  </p>
                  <p className="text-[10px] mt-1" style={{ color: `${fontColor}30` }}>
                    Try a different search term
                  </p>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

interface FeaturedCardProps {
  integration: MarketplaceIntegration
  glowColor: string
  fontColor: string
  onInstall?: (integration: MarketplaceIntegration) => void
}

function FeaturedCard({ integration, glowColor, fontColor, onInstall }: FeaturedCardProps) {
  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      className="relative p-4 rounded-xl border overflow-hidden group cursor-pointer"
      style={{
        backgroundColor: "rgba(10,10,20,0.6)",
        borderColor: `${glowColor}20`,
      }}
      onClick={() => onInstall?.(integration)}
    >
      {/* Gradient overlay */}
      <div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300"
        style={{
          background: `linear-gradient(135deg, ${glowColor}10 0%, transparent 50%)`,
        }}
      />

      <div className="relative">
        <div className="flex items-start justify-between mb-3">
          <span className="text-2xl">{integration.icon}</span>
          {integration.verified && (
            <Shield size={14} style={{ color: glowColor }} />
          )}
        </div>

        <h4 className="text-[13px] font-semibold mb-1" style={{ color: fontColor }}>
          {integration.name}
        </h4>
        <p
          className="text-[10px] line-clamp-2 mb-3"
          style={{ color: `${fontColor}60` }}
        >
          {integration.description}
        </p>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-[9px]" style={{ color: `${fontColor}40` }}>
            <span className="flex items-center gap-0.5">
              <Star size={10} style={{ color: "#fbbf24" }} />
              {integration.rating}
            </span>
            <span>•</span>
            <span>{formatInstallCount(integration.installCount)}</span>
          </div>

          <button
            className="px-3 py-1 rounded-lg text-[10px] font-medium transition-all duration-150"
            style={{
              backgroundColor: integration.installed ? `${glowColor}20` : `${glowColor}30`,
              color: glowColor,
            }}
            onClick={(e) => {
              e.stopPropagation()
              onInstall?.(integration)
            }}
          >
            {integration.installed ? "Installed" : "Install"}
          </button>
        </div>
      </div>
    </motion.div>
  )
}

interface IntegrationCardProps {
  integration: MarketplaceIntegration
  glowColor: string
  fontColor: string
  onInstall?: (integration: MarketplaceIntegration) => void
  compact?: boolean
}

function IntegrationCard({ integration, glowColor, fontColor, onInstall, compact }: IntegrationCardProps) {
  if (compact) {
    return (
      <motion.div
        whileHover={{ backgroundColor: "rgba(255,255,255,0.03)" }}
        className="flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors"
        style={{
          backgroundColor: "rgba(10,10,20,0.4)",
          borderColor: `${glowColor}15`,
        }}
        onClick={() => onInstall?.(integration)}
      >
        <span className="text-xl">{integration.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-[12px] font-medium truncate" style={{ color: fontColor }}>
              {integration.name}
            </h4>
            {integration.verified && <Shield size={12} style={{ color: glowColor }} />}
          </div>
          <p className="text-[9px] truncate" style={{ color: `${fontColor}50` }}>
            {integration.description}
          </p>
        </div>
        <button
          className="px-2.5 py-1 rounded-lg text-[9px] font-medium transition-all duration-150"
          style={{
            backgroundColor: integration.installed ? `${glowColor}20` : `${glowColor}30`,
            color: glowColor,
          }}
          onClick={(e) => {
            e.stopPropagation()
            onInstall?.(integration)
          }}
        >
          {integration.installed ? "Installed" : "Install"}
        </button>
      </motion.div>
    )
  }

  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      className="p-3 rounded-xl border cursor-pointer transition-colors"
      style={{
        backgroundColor: "rgba(10,10,20,0.4)",
        borderColor: `${glowColor}15`,
      }}
      onClick={() => onInstall?.(integration)}
    >
      <div className="flex items-start gap-3 mb-2">
        <span className="text-2xl">{integration.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <h4 className="text-[12px] font-medium truncate" style={{ color: fontColor }}>
              {integration.name}
            </h4>
            {integration.verified && <Shield size={12} style={{ color: glowColor }} />}
          </div>
          <p className="text-[9px]" style={{ color: `${fontColor}40` }}>
            {integration.publisher}
          </p>
        </div>
      </div>

      <p
        className="text-[10px] line-clamp-2 mb-3"
        style={{ color: `${fontColor}60` }}
      >
        {integration.description}
      </p>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[9px]" style={{ color: `${fontColor}40` }}>
          <span className="flex items-center gap-0.5">
            <Star size={10} style={{ color: "#fbbf24" }} />
            {integration.rating}
          </span>
          <span>•</span>
          <span>{formatInstallCount(integration.installCount)}</span>
        </div>

        <button
          className="px-2.5 py-1 rounded-lg text-[9px] font-medium transition-all duration-150"
          style={{
            backgroundColor: integration.installed ? `${glowColor}20` : `${glowColor}30`,
            color: glowColor,
          }}
          onClick={(e) => {
            e.stopPropagation()
            onInstall?.(integration)
          }}
        >
          {integration.installed ? "Installed" : "Install"}
        </button>
      </div>
    </motion.div>
  )
}

interface RecommendedCardProps {
  recommendation: RecommendedIntegration
  glowColor: string
  fontColor: string
  onInstall?: () => void
  compact?: boolean
}

function RecommendedCard({ recommendation, glowColor, fontColor, onInstall, compact }: RecommendedCardProps) {
  if (compact) {
    return (
      <motion.div
        whileHover={{ backgroundColor: "rgba(255,255,255,0.03)" }}
        className="flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors relative overflow-hidden"
        style={{
          backgroundColor: "rgba(10,10,20,0.4)",
          borderColor: `${glowColor}30`,
        }}
        onClick={onInstall}
      >
        {/* Recommendation badge */}
        <div
          className="absolute top-0 right-0 px-1.5 py-0.5 rounded-bl-lg text-[8px] font-medium"
          style={{
            backgroundColor: `${glowColor}20`,
            color: glowColor,
          }}
        >
          Recommended
        </div>

        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center text-lg"
          style={{ backgroundColor: `${glowColor}15` }}
        >
          {recommendation.category === "email" && "📧"}
          {recommendation.category === "messaging" && "💬"}
          {recommendation.category === "productivity" && "⚡"}
          {recommendation.category === "developer" && "</>"}
          {!recommendation.category && "🔌"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-[12px] font-medium truncate" style={{ color: fontColor }}>
              {recommendation.name}
            </h4>
          </div>
          <p className="text-[9px] truncate" style={{ color: `${fontColor}50` }}>
            {recommendation.reason}
          </p>
        </div>
        <button
          className="px-2.5 py-1 rounded-lg text-[9px] font-medium transition-all duration-150"
          style={{
            backgroundColor: `${glowColor}30`,
            color: glowColor,
          }}
          onClick={(e) => {
            e.stopPropagation()
            onInstall?.()
          }}
        >
          Install
        </button>
      </motion.div>
    )
  }

  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      className="relative p-4 rounded-xl border overflow-hidden group cursor-pointer"
      style={{
        backgroundColor: "rgba(10,10,20,0.6)",
        borderColor: `${glowColor}30`,
      }}
      onClick={onInstall}
    >
      {/* Recommendation badge */}
      <div
        className="absolute top-2 right-2 px-2 py-0.5 rounded text-[9px] font-medium flex items-center gap-1"
        style={{
          backgroundColor: `${glowColor}20`,
          color: glowColor,
        }}
      >
        <Sparkles size={10} />
        Recommended
      </div>

      {/* Hover gradient overlay */}
      <div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300"
        style={{
          background: `linear-gradient(135deg, ${glowColor}10 0%, transparent 50%)`,
        }}
      />

      <div className="relative">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl mb-3"
          style={{ backgroundColor: `${glowColor}15` }}
        >
          {recommendation.category === "email" && "📧"}
          {recommendation.category === "messaging" && "💬"}
          {recommendation.category === "productivity" && "⚡"}
          {recommendation.category === "developer" && "</>"}
          {!recommendation.category && "🔌"}
        </div>

        <h4 className="text-[13px] font-semibold mb-1" style={{ color: fontColor }}>
          {recommendation.name}
        </h4>
        <p
          className="text-[10px] line-clamp-2 mb-3"
          style={{ color: `${fontColor}60` }}
        >
          {recommendation.description}
        </p>

        <div className="flex items-center justify-between">
          <span
            className="text-[9px] px-2 py-0.5 rounded-full"
            style={{
              backgroundColor: `${glowColor}10`,
              color: `${fontColor}60`,
            }}
          >
            {recommendation.reason}
          </span>

          <button
            className="px-3 py-1 rounded-lg text-[10px] font-medium transition-all duration-150"
            style={{
              backgroundColor: `${glowColor}30`,
              color: glowColor,
            }}
            onClick={(e) => {
              e.stopPropagation()
              onInstall?.()
            }}
          >
            Install
          </button>
        </div>
      </div>
    </motion.div>
  )
}

export default MarketplaceScreen
