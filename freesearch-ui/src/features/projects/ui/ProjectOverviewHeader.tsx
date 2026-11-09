import { PROJECT_PERMISSIONS, hasPermission } from "@/domains/projects"
import type { Project, ProjectAccess } from "@/domains/projects"
import { LinkButton } from "@/shared/ui/LinkButton"
import { PageHeader } from "@/shared/ui/PageHeader"
import { Tag } from "@/shared/ui/Tag"

function canExecute(access: ProjectAccess | null): boolean {
  return (
    hasPermission(access, PROJECT_PERMISSIONS.searchExecute) ||
    hasPermission(access, PROJECT_PERMISSIONS.fetchExecute)
  )
}

/**
 * Overview header: project name, archive status and the permitted Playground action.
 */
export function ProjectOverviewHeader({
  project,
  projectId,
  access,
}: {
  project: Project | null
  projectId: string
  access: ProjectAccess | null
}) {
  const archived = project?.status === "archived"
  const meta = (
    <>
      {archived && <Tag tone="warning">Archived</Tag>}
    </>
  )
  const action =
    canExecute(access) && !archived ? (
      <LinkButton to={`/p/${projectId}/playground`}>
        Open playground
      </LinkButton>
    ) : undefined
  return (
    <PageHeader
      title={project?.name ?? "Project"}
      description="Calls, order and recent activity for this project"
      meta={meta}
      {...(action === undefined ? {} : { actions: action })}
    />
  )
}
