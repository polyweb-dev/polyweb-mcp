import { memberPermissionSummary } from "@/domains/projects"
import type { ProjectMember } from "@/domains/projects"
import { Tag } from "@/shared/ui/Tag"
import type { ProjectMembersController } from "../model/useProjectMembersController"
import { identityLabel } from "@/shared/lib/identity"
import { memberSortLabel } from "../model/memberIdentity"
import { MemberRowActions } from "./MemberRowActions"

function isActiveAdmin(member: ProjectMember): boolean {
  return member.account_active && member.status === "active" && member.role === "admin"
}

export interface MembersTableProps {
  members: readonly ProjectMember[]
  /** The caller's account id; its row is marked "(you)" and offers no Suspend. */
  accountId: string
  projectName: string
  canManage: boolean
  canAssign: boolean
  controller: ProjectMembersController
  ownerId?: string | null
  onPermissions?: (member: ProjectMember) => void
  onTransfer?: (member: ProjectMember) => void
}

/**
 * Member table of one project: the display name leads when one exists (the
 * full name, then the username), with the email kept for contact and
 * disambiguation, and roles as tags plus the row menu. The project's only
 * active admin is passed to the menu so it cannot drop that role.
 */
export function MembersTable({ members, accountId, projectName, canManage, canAssign, controller, ownerId, onPermissions, onTransfer }: MembersTableProps) {
  const showActions = canManage || canAssign
  const activeAdmins = members.filter(isActiveAdmin).length
  return (
    <div className="fs-panel overflow-hidden">
      <table aria-label="Members" className="fs-table">
        <thead>
          <tr>
            <th scope="col">Member</th>
            <th scope="col">Role</th>
            <th scope="col">Access</th>
            {showActions && (
              <th scope="col" className="fs-cell-actions">
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {[...members].sort((a, b) => Number(b.user_id === accountId) - Number(a.user_id === accountId) || memberSortLabel(a).localeCompare(memberSortLabel(b))).map((member) => {
            const isSelf = member.user_id === accountId
            const admin = member.role === "admin"
            return (
              <tr key={member.user_id}>
                <td className="fs-cell-strong">
                  <span className="flex items-center gap-2">
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">{identityLabel(member)}</span>
                      {identityLabel(member) !== member.email && (
                        <span className="truncate text-[12px] font-normal text-[var(--muted)]">{member.email}</span>
                      )}
                    </span>
                    {isSelf && (
                      <span aria-hidden="true" className="font-normal text-[var(--muted)]">
                        (you)
                      </span>
                    )}
                    {member.status === "suspended" && <Tag tone="warning">Suspended</Tag>}
                    {!member.account_active && <Tag tone="warning">Account inactive</Tag>}
                  </span>
                </td>
                <td>
                  <span className="flex flex-wrap gap-1.5">
                    <Tag>{admin ? "Project admin" : "Developer"}</Tag>
                    {admin && member.user_id === ownerId && <Tag>Provider owner</Tag>}
                  </span>
                </td>
                <td className="text-[var(--muted)]">{admin ? "All permissions" : memberPermissionSummary(member.permissions)}</td>
                {showActions && (
                  <td className="fs-cell-actions">
                    <MemberRowActions
                      projectName={projectName}
                      member={member}
                      canManage={canManage}
                      canAssign={canAssign}
                      isSelf={isSelf}
                      lastAdmin={isActiveAdmin(member) && activeAdmins <= 1}
                      controller={controller}
                      ownerId={ownerId}
                      callerIsProviderOwner={accountId === ownerId}
                      onPermissions={onPermissions}
                      onTransfer={onTransfer}
                    />
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
