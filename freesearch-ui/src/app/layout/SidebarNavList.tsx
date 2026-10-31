import type { LucideIcon } from "lucide-react"
import { NavLink } from "react-router"
import {
  Activity,
  FolderKanban,
  Gauge,
  Route,
  Search,
  Settings,
  ShieldCheck,
  UserRound,
} from "lucide-react"
import { useProjectsOptional } from "@/domains/projects"
import { TAB_PATHS, canAccessRoute, type TabId } from "../routes"
import { navLinkClass } from "./navLinkClass"

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
  { id: "projects", label: "Projects", icon: FolderKanban },
  { id: "account", label: "Account", icon: UserRound },
  { id: "adminUsers", label: "Admin", icon: ShieldCheck },
]

interface NavListProps {
  collapsed: boolean
  onNavigate?: () => void
}

/**
 * Primary (global) navigation. The list filters with the same permission
 * helper as the route gate, reading the live system access descriptor, so a
 * caller never sees a link to a page it cannot open. A gated link stays
 * hidden until the descriptor has loaded.
 */
export function NavList({ collapsed, onNavigate }: NavListProps) {
  const { systemAccess } = useProjectsOptional()
  const visibleItems = navItems.filter((item) => canAccessRoute(item.id, systemAccess))

  return (
    <nav
      aria-label="Primary"
      className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-2 py-3"
    >
      {visibleItems.map(({ id, label, icon: Icon }) => (
        <NavLink
          key={id}
          to={TAB_PATHS[id]}
          aria-label={label}
          title={collapsed ? label : undefined}
          onClick={onNavigate}
          className={({ isActive }) => navLinkClass(collapsed, isActive)}
        >
          <Icon aria-hidden="true" className="size-[18px] shrink-0" strokeWidth={1.8} />
          {!collapsed && <span>{label}</span>}
        </NavLink>
      ))}
    </nav>
  )
}
