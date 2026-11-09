import type { LucideIcon } from "lucide-react"
import { Activity, Gauge, KeyRound, LayoutDashboard, Plug, Search, SlidersHorizontal, Users } from "lucide-react"
import { NavLink } from "react-router"
import type { PermissionAccess } from "@/domains/projects"
import {
  PROJECT_SECTIONS,
  canAccessProjectSection,
  projectPath,
  type ProjectSectionId,
} from "../routes"
import { NAV_ICON_CLASS, navLinkClass } from "./navLinkClass"

/** Icon of each registered project section. A new section adds its icon here. */
const SECTION_ICONS: Record<ProjectSectionId, LucideIcon> = {
  overview: LayoutDashboard,
  playground: Search,
  activity: Activity,
  usage: Gauge,
  providers: Plug,
  settings: SlidersHorizontal,
  members: Users,
  apiKeys: KeyRound,
}

export interface SectionLinksProps {
  projectId: string
  access: PermissionAccess | null
  /** Off a project route no section is current, so none shows active. */
  highlightActive: boolean
  collapsed: boolean
  onNavigate?: () => void
}

/** The permitted section links of one project, in registry order. */
export function SectionLinks({ projectId, access, highlightActive, collapsed, onNavigate }: SectionLinksProps) {
  const sections = PROJECT_SECTIONS.filter((section) => canAccessProjectSection(section.id, access))
  return (
    <nav aria-label="Project" className="flex shrink-0 flex-col gap-0.5 px-2">
      {!collapsed && sections.length > 0 && (
        <p aria-hidden="true" className="px-2.5 pt-3 pb-1.5 text-[12px] text-[var(--muted)]">
          Project
        </p>
      )}
      {sections.map(({ id, label }) => {
        const Icon = SECTION_ICONS[id]
        return (
          <NavLink
            key={id}
            to={projectPath(projectId, id)}
            end
            aria-label={label}
            title={collapsed ? label : undefined}
            onClick={onNavigate}
            className={({ isActive }) => navLinkClass(collapsed, highlightActive && isActive)}
          >
            <Icon aria-hidden="true" className={NAV_ICON_CLASS} strokeWidth={1.75} />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        )
      })}
    </nav>
  )
}
