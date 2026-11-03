import type { LucideIcon } from "lucide-react"
import { Activity, Gauge, KeyRound, LayoutDashboard, Plug, Search, SlidersHorizontal, Users } from "lucide-react"
import { NavLink } from "react-router"
import { useProjectScopeOptional } from "@/domains/projects"
import {
  PROJECT_SECTIONS,
  canAccessProjectSection,
  projectPath,
  type ProjectSectionId,
} from "../routes"
import { navLinkClass } from "./navLinkClass"

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

interface ProjectNavProps {
  collapsed: boolean
  onNavigate?: () => void
}

/**
 * Project navigation group of the sidebar.
 *
 * The group renders only inside an open project (a `/p/:projectId/...` URL).
 * Its links come from the section registry, filtered by the live project
 * access descriptor that the page below shares, so a section the caller
 * cannot open never shows a link.
 */
export function ProjectNav({ collapsed, onNavigate }: ProjectNavProps) {
  const scope = useProjectScopeOptional()
  if (scope === null) return null

  const access = scope.accessState.status === "ready" ? scope.accessState.data : null
  const sections = PROJECT_SECTIONS.filter((section) =>
    canAccessProjectSection(section.id, access)
  )

  return (
    <nav
      aria-label="Project"
      className="flex shrink-0 flex-col gap-1 border-b border-[var(--border-subtle)] px-2 py-3"
    >
      {sections.map(({ id, label }) => {
        const Icon = SECTION_ICONS[id]
        return (
          <NavLink
            key={id}
            to={projectPath(scope.projectId, id)}
            end
            aria-label={label}
            title={collapsed ? label : undefined}
            onClick={onNavigate}
            className={({ isActive }) => navLinkClass(collapsed, isActive)}
          >
            <Icon aria-hidden="true" className="size-[18px] shrink-0" strokeWidth={1.8} />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        )
      })}
    </nav>
  )
}
