import type { LucideIcon } from "lucide-react"
import { NavLink } from "react-router"
import {
  Activity,
  Gauge,
  Route,
  Search,
  Settings,
  ShieldCheck,
  UserRound,
} from "lucide-react"
import { cn } from "cn"
import { useAuth } from "@/domains/auth"
import type { UserRole } from "@/domains/auth"
import { TAB_PATHS, canAccessRoute, type TabId } from "../routes"

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
  { id: "account", label: "Account", icon: UserRound },
  { id: "adminUsers", label: "Admin", icon: ShieldCheck },
]

interface NavListProps {
  collapsed: boolean
  onNavigate?: () => void
}

/**
 * Primary navigation. The list filters with the same permission helper as the
 * route gate, so a role never sees a link to a page it cannot open.
 */
export function NavList({ collapsed, onNavigate }: NavListProps) {
  const { account } = useAuth()
  const role: UserRole = account?.role ?? "agent"
  const visibleItems = navItems.filter((item) => canAccessRoute(item.id, role))

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
