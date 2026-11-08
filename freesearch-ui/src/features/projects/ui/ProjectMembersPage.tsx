import { useContext, useState } from "react"
import { getProviderOwner, hasPermission, useProjectScope } from "@/domains/projects"
import type { ProjectMember } from "@/domains/projects"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { NotificationsContext } from "@/shared/notifications/context"
import { PageHeader } from "@/shared/ui/PageHeader"
import { isEmailFieldMessage, useProjectMembersController } from "../model/useProjectMembersController"
import { MembersBody } from "./MembersBody"
import { MembersDialogs } from "./MembersDialogs"
import { MembersOwnershipControls } from "./MembersOwnershipControls"

/**
 * Membership administration of one project.
 *
 * The table lists members by email, with the caller's own row marked, and
 * the add panel sits beside it. Every control renders only from the caller's
 * live effective permissions — `members.manage` for the add panel and
 * membership changes, `roles.assign` for role edits — never from a role name.
 */
export function ProjectMembersPage({ accountId }: { accountId: string }) {
  const { projectId, project, accessState, refreshAccess } = useProjectScope()
  const controller = useProjectMembersController({ accountId, projectId, refreshAccess })
  const owner = useScopedResource({ scopeKey: `${accountId}:${projectId}:owner`, load: (signal) => getProviderOwner(projectId, signal) })
  const [permissionsMember, setPermissionsMember] = useState<ProjectMember | null>(null)
  const [transferMember, setTransferMember] = useState<ProjectMember | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const notifications = useContext(NotificationsContext)
  const access = accessState.status === "ready" ? accessState.data : null
  const canManage = hasPermission(access, "members.manage")
  const canAssign = hasPermission(access, "roles.assign")
  const projectName = project?.name ?? "this project"
  const pageMessage =
    controller.message !== null && !isEmailFieldMessage(controller.message) ? controller.message : null
  const ownerId = owner.status === "ready" ? owner.data?.user_id ?? null : undefined
  const saved = (message: string) => {
    void owner.reload()
    void controller.members.reload()
    refreshAccess()
    if (notifications) {
      setNotice(null)
      notifications.showToast(message, "success")
    } else setNotice(message)
  }

  return (
    <section className="flex flex-1 flex-col">
      <PageHeader title="Members" description="People in this project and what each person can do" />

      <MembersOwnershipControls owner={owner} canManage={canManage} projectId={projectId} accountId={accountId} onSaved={saved} />
      {notice && <p role="status" className="mb-4 text-[var(--muted)]">{notice}</p>}

      {pageMessage !== null && (
        <p role="alert" className="mb-4 text-[13px] text-[var(--status-danger)]">
          {pageMessage}
        </p>
      )}

      <MembersBody controller={controller} accountId={accountId} projectName={projectName} canManage={canManage}
        canAssign={canAssign} ownerId={ownerId} onTransfer={setTransferMember}
        onPermissions={setPermissionsMember} />
      <MembersDialogs projectId={projectId} projectName={projectName} members={controller.members} ownerId={ownerId}
        permissionsMember={permissionsMember} transferMember={transferMember} closePermissions={() => setPermissionsMember(null)}
        closeTransfer={() => setTransferMember(null)} onSaved={saved} />
    </section>
  )
}
