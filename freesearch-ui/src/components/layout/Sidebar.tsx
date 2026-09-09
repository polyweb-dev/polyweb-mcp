import { useCallback, useEffect, useRef, useState } from "react"
import type { LucideIcon } from "lucide-react"
import { NavLink } from "react-router"
import {
  Activity,
  Gauge,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Route,
  Search,
  Settings,
  X,
} from "lucide-react"
import freesearchLogo from "@/assets/freesearch.webp"
import { cn } from "@/lib/utils"

export type TabId =
  | "playground"
  | "routing"
  | "quotas"
  | "activity"
  | "settings"

export interface SidebarProps {
  collapsed?: boolean
  defaultCollapsed?: boolean
  onCollapsedChange?: (collapsed: boolean) => void
}

interface NavItem {
  id: TabId
  label: string
  icon: LucideIcon
}

const navItems: NavItem[] = [
  { id: "playground", label: "Playground", icon: Search },
  { id: "routing", label: "Routing", icon: Route },
  { id: "quotas", label: "Usage", icon: Gauge },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "settings", label: "Settings", icon: Settings },
]

const TAB_PATHS: Record<TabId, string> = {
  playground: "/playground",
  routing: "/routing",
  quotas: "/usage",
  activity: "/activity",
  settings: "/settings",
}

const STORAGE_KEY = "freesearch.sidebar.collapsed"

function readStoredCollapsed(defaultValue: boolean): boolean {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === null) return defaultValue
    if (stored === "1") return true
    if (stored === "0") return false
    return defaultValue
  } catch {
    return defaultValue
  }
}

interface NavListProps {
  collapsed: boolean
  onNavigate?: () => void
}

function NavList({ collapsed, onNavigate }: NavListProps) {
  return (
    <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 px-2 py-3">
      {navItems.map(({ id, label, icon: Icon }) => (
        <NavLink
          key={id}
          to={TAB_PATHS[id]}
          aria-label={label}
          title={collapsed ? label : undefined}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "relative flex h-10 w-full items-center rounded-md text-[13px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-inset motion-reduce:transition-none",
              collapsed ? "justify-center px-0" : "gap-3 px-3",
              isActive
                ? "bg-[var(--signal-muted)] text-[var(--text-strong)] before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-r before:bg-[var(--signal)]"
                : "text-[var(--muted)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)]"
            )
          }
        >
          <Icon aria-hidden="true" className="size-[18px] shrink-0" strokeWidth={1.8} />
          {!collapsed && <span>{label}</span>}
        </NavLink>
      ))}
    </nav>
  )
}

interface BrandProps {
  collapsed?: boolean
}

function Brand({ collapsed = false }: BrandProps) {
  return (
    <div className={cn("flex h-16 items-center", collapsed ? "justify-center" : "gap-3 px-4")}>
      <span className="grid size-8 shrink-0 place-items-center overflow-hidden rounded-md border border-[var(--border-subtle)] bg-[var(--secondary)]">
        <img
          src={freesearchLogo}
          alt=""
          aria-hidden="true"
          className="size-6 object-contain"
        />
      </span>
      {!collapsed && (
        <span className="text-[15px] font-semibold tracking-tight text-[var(--text-strong)]">
          FreeSearch
        </span>
      )}
    </div>
  )
}

export function Sidebar({
  collapsed,
  defaultCollapsed = false,
  onCollapsedChange,
}: SidebarProps) {
  const isControlled = collapsed !== undefined
  const [internalCollapsed, setInternalCollapsed] = useState(() =>
    readStoredCollapsed(defaultCollapsed)
  )
  const [drawerOpen, setDrawerOpen] = useState(false)
  const openerRef = useRef<HTMLButtonElement>(null)
  const isCollapsed = isControlled ? collapsed : internalCollapsed

  const closeDrawer = useCallback((returnFocus = false) => {
    setDrawerOpen(false)
    if (returnFocus) openerRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!drawerOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDrawer(true)
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [closeDrawer, drawerOpen])

  const toggleCollapsed = () => {
    const next = !isCollapsed
    if (!isControlled) {
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0")
      } catch {
        // Persistence is best-effort; the control must remain usable.
      }
    }
    setInternalCollapsed(next)
    onCollapsedChange?.(next)
  }

  return (
    <>
      <button
        ref={openerRef}
        type="button"
        aria-label="Open navigation"
        onClick={() => setDrawerOpen(true)}
        className="fixed left-3 top-3 z-30 grid size-10 place-items-center rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] md:hidden"
      >
        <Menu aria-hidden="true" className="size-5" />
      </button>

      <aside
        id="primary-sidebar"
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col overflow-hidden border-r border-[var(--border-subtle)] bg-[var(--elevated)] transition-[width] duration-200 motion-reduce:transition-none md:flex",
          isCollapsed ? "w-16" : "w-60"
        )}
      >
        <Brand collapsed={isCollapsed} />
        <NavList collapsed={isCollapsed} />
        <button
          type="button"
          aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!isCollapsed}
          aria-controls="primary-sidebar"
          onClick={toggleCollapsed}
          className={cn(
            "m-2 flex h-10 items-center rounded-md text-[13px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] motion-reduce:transition-none",
            isCollapsed ? "justify-center" : "gap-3 px-3"
          )}
        >
          {isCollapsed ? (
            <PanelLeftOpen aria-hidden="true" className="size-[18px]" />
          ) : (
            <>
              <PanelLeftClose aria-hidden="true" className="size-[18px]" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Dismiss navigation overlay"
            data-testid="sidebar-scrim"
            onClick={() => closeDrawer(true)}
            className="absolute inset-0 bg-[var(--surface)]/80"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="relative flex h-full w-72 flex-col border-r border-[var(--border-subtle)] bg-[var(--elevated)] motion-reduce:transition-none"
          >
            <div className="flex items-center justify-between pr-3">
              <Brand />
              <button
                type="button"
                aria-label="Close navigation"
                onClick={() => closeDrawer(true)}
                className="grid size-9 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]"
              >
                <X aria-hidden="true" className="size-5" />
              </button>
            </div>
            <NavList collapsed={false} onNavigate={() => closeDrawer()} />
          </div>
        </div>
      )}
    </>
  )
}
