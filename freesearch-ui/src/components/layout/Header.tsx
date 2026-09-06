import React from "react"
import { cn } from "@/lib/utils"

export type TabId = "playground" | "providers" | "routing" | "quotas" | "activity" | "settings"

interface HeaderProps {
  activeTab: TabId
  onSelectTab: (tab: TabId) => void
}

const navItems: Array<{ id: TabId; label: string }> = [
  { id: "playground", label: "Playground" },
  { id: "providers", label: "Providers" },
  { id: "routing", label: "Routing" },
  { id: "quotas", label: "Usage" },
  { id: "activity", label: "Activity" },
  { id: "settings", label: "Settings" },
]

export const Header: React.FC<HeaderProps> = ({ activeTab, onSelectTab }) => {
  return (
    <header
      className="sticky top-0 z-40 w-full backdrop-blur-sm"
      style={{
        background: "rgba(13, 16, 23, 0.85)",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div className="w-full max-w-[1600px] mx-auto px-6 sm:px-8 lg:px-12 flex items-center justify-between h-14">
        {/* Brand */}
        <span
          className="text-[15px] font-semibold tracking-tight"
          style={{ color: "var(--text-strong)" }}
        >
          FreeSearch
        </span>

        {/* Navigation — plain text links with bottom-border active indicator */}
        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const isActive = activeTab === item.id
            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                className={cn(
                  "px-3 py-1 text-[13px] font-medium rounded-md transition-colors",
                  isActive
                    ? "text-white bg-white/[0.07]"
                    : "text-[var(--muted)] hover:text-[var(--text-strong)]"
                )}
              >
                {item.label}
              </button>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
