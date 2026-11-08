import type { LucideIcon } from "lucide-react"
import { NavLink } from "react-router"
import { ChartPie, FolderKanban, KeyRound, Plug, UserRound } from "lucide-react"
import { useProjectsOptional } from "@/domains/projects"
import { TAB_PATHS, canAccessRoute, type TabId } from "../routes"
import { NAV_ICON_CLASS, navLinkClass } from "./navLinkClass"

interface NavItem {
  id: TabId
  label: string
  icon: LucideIcon
}

const systemItems: NavItem[] = [
  { id: "settings", label: "Providers", icon: Plug },
  { id: "quotas", label: "Quotas", icon: ChartPie },
]

const workspaceItems: NavItem[] = [
  { id: "projects", label: "Projects", icon: FolderKanban },
  { id: "accountKeys", label: "Keys and pools", icon: KeyRound },
  { id: "account", label: "Account", icon: UserRound },
]

interface NavListProps {
  collapsed: boolean
  onNavigate?: () => void
}

/**
 * Primary (global) navigation: the System group for installation
 * administrators, then Projects and Account. The list filters with the same
 * permission helper as the route gate, reading the live system access
 * descriptor, so a caller never sees a link to a page it cannot open. A gated
 * link stays hidden until the descriptor has loaded.
 */
export function NavList({ collapsed, onNavigate }: NavListProps) {
  const { systemAccess } = useProjectsOptional()
  const visibleSystem = systemItems.filter((item) => canAccessRoute(item.id, systemAccess))
  const visibleWorkspace = workspaceItems.filter((item) => canAccessRoute(item.id, systemAccess))

  const row = ({ id, label, icon: Icon }: NavItem) => (
    <NavLink
      key={id}
      to={TAB_PATHS[id]}
      end={id === "account"}
      aria-label={label}
      title={collapsed ? label : undefined}
      onClick={onNavigate}
      className={({ isActive }) => navLinkClass(collapsed, isActive)}
    >
      <Icon aria-hidden="true" className={NAV_ICON_CLASS} strokeWidth={1.75} />
      {!collapsed && <span className="truncate">{label}</span>}
    </NavLink>
  )

  return (
    <nav aria-label="Primary" className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-3">
      {visibleSystem.length > 0 &&
        (collapsed ? (
          <hr className="mx-2 my-2 border-[var(--border-subtle)]" />
        ) : (
          <p className="px-2.5 pt-5 pb-1.5 text-[12px] text-[var(--muted)]">System</p>
        ))}
      {visibleSystem.map(row)}
      <div aria-hidden="true" className="min-h-4 flex-1" />
      {visibleWorkspace.map(row)}
    </nav>
  )
}
