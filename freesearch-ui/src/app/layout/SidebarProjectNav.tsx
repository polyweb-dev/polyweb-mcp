import { getProjectAccess, resolveLastProject, useProjectScopeOptional, useProjectsOptional } from "@/domains/projects"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { SectionLinks } from "./SidebarSectionLinks"

interface ProjectNavProps {
  collapsed: boolean
  onNavigate?: () => void
}

/**
 * Project navigation group of the sidebar.
 *
 * Inside an open project (a `/p/:projectId/...` URL) its links come from the
 * section registry, filtered by the live project access descriptor that the
 * page below shares, so a section the caller cannot open never shows a link.
 * On a system page the group stays for continuity: it lists the remembered
 * project's sections, gated by the same descriptor loaded through the nav's
 * own scope, and the project switcher above names that project.
 */
export function ProjectNav({ collapsed, onNavigate }: ProjectNavProps) {
  const scope = useProjectScopeOptional()
  const { accountId, projects } = useProjectsOptional()
  const lastId = resolveLastProject(accountId, projects)
  const lastProject = projects.find((project) => project.id === lastId) ?? null

  const fallbackAccess = useScopedResource({
    scopeKey: `${accountId}:${lastProject?.id ?? "none"}:nav`,
    load: (signal) => getProjectAccess(lastProject?.id ?? "", signal),
    enabled: scope === null && lastProject !== null,
  })
  const navigate = onNavigate === undefined ? {} : { onNavigate }

  if (scope !== null) {
    const access = scope.accessState.status === "ready" ? scope.accessState.data : null
    return <SectionLinks projectId={scope.projectId} access={access} highlightActive collapsed={collapsed} {...navigate} />
  }
  if (lastProject === null || fallbackAccess.status !== "ready") return null
  return (
    <SectionLinks
      projectId={lastProject.id}
      access={fallbackAccess.data}
      highlightActive={false}
      collapsed={collapsed}
      {...navigate}
    />
  )
}
