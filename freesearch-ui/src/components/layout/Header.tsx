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
        background: "rgba(37, 37, 38, 0.85)",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div className="mx-auto flex h-14 w-full max-w-[1600px] min-w-0 items-center justify-between gap-4 px-6 sm:px-8 lg:px-12">
        <div className="flex shrink-0 items-center gap-3">
          <span
            className="text-[15px] font-semibold tracking-tight"
            style={{ color: "var(--text-strong)" }}
          >
            FreeSearch
          </span>
          <span
            aria-hidden="true"
            className="size-2 rounded-full bg-[var(--signal)]"
          />
          <span
            aria-hidden="true"
            className="h-5 w-px bg-[var(--border-subtle)]"
          />
        </div>

        <nav className="flex max-w-full items-center gap-1 overflow-x-auto rounded-full border border-[var(--border-subtle)] bg-[var(--secondary)] p-1">
          {navItems.map((item) => {
            const isActive = activeTab === item.id
            return (
              <button
                key={item.id}
                type="button"
                aria-current={isActive ? "page" : undefined}
                onClick={() => onSelectTab(item.id)}
                className={cn(
                  "relative shrink-0 rounded-full px-3 py-1 text-[13px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--elevated)] motion-reduce:transition-none",
                  isActive
                    ? "bg-[var(--signal-muted)] text-white"
                    : "text-[var(--muted)] hover:text-[var(--text-strong)]"
                )}
              >
                {item.label}
                {isActive && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-[var(--signal)]"
                  />
                )}
              </button>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
