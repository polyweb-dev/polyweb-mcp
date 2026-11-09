import type { ProjectMember } from "@/domains/projects"
import type { ProjectMembersController } from "../model/useProjectMembersController"
import { AddMemberForm } from "./AddMemberForm"
import { MembersTable } from "./MembersTable"

const TWO_COLUMNS = "grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]"

interface Props {
  controller: ProjectMembersController
  accountId: string
  projectName: string
  canManage: boolean
  canAssign: boolean
  ownerId: string | null | undefined
  onPermissions: (member: ProjectMember) => void
  onTransfer: (member: ProjectMember) => void
}

export function MembersBody({ controller, accountId, projectName, canManage, canAssign, ownerId, onPermissions, onTransfer }: Props) {
  const members = controller.members
  return (
    <div className={canManage ? TWO_COLUMNS : undefined}>
      <div className="min-w-0">
        {members.status === "loading" && <p role="status" className="text-[13px] text-[var(--muted)]">Loading members...</p>}
        {members.status === "error" && <p role="alert" className="text-[13px] text-[var(--muted)]">The member list could not be loaded.</p>}
        {members.status === "ready" && (
          <MembersTable members={members.data} accountId={accountId} projectName={projectName} canManage={canManage}
            canAssign={canAssign} controller={controller} ownerId={ownerId}
            onPermissions={canManage ? onPermissions : undefined}
            onTransfer={canManage && ownerId === accountId ? onTransfer : undefined} />
        )}
      </div>
      {canManage && <AddMemberForm controller={controller} />}
    </div>
  )
}
