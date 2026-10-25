import {
  PROJECT_ROLE_LABELS,
  hasPermission,
  useProjectScope,
} from "@/domains/projects"
import type { ProjectRoleKey } from "@/domains/projects"
import { useProjectMembersController } from "../model/useProjectMembersController"
import { AddMemberForm } from "./AddMemberForm"
import { MemberRowActions } from "./MemberRowActions"

function roleLabel(role: string): string {
  return PROJECT_ROLE_LABELS[role as ProjectRoleKey] ?? role
}

/**
 * Membership administration of one project.
 *
 * The table lists members by email. Every control renders only from the
 * caller's live effective permissions — `members.manage` for the add form and
 * membership changes, `roles.assign` for role edits — never from a role name.
 */
export function ProjectMembersPage({ accountId }: { accountId: string }) {
  const { projectId, accessState, refreshAccess } = useProjectScope()
  const controller = useProjectMembersController({ accountId, projectId, refreshAccess })
  const access = accessState.status === "ready" ? accessState.data : null
  const canManage = hasPermission(access, "members.manage")
  const canAssign = hasPermission(access, "roles.assign")
  const showActions = canManage || canAssign

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="border-b border-[var(--border-subtle)] pb-2">
        <h2 className="text-[var(--text-strong)]">Members</h2>
      </header>

      {controller.message !== null && (
        <p role="alert" className="text-[13px] text-[var(--muted)]">
          {controller.message}
        </p>
      )}

      {canManage && <AddMemberForm controller={controller} />}

      {controller.members.status === "loading" && (
        <p role="status" className="text-[13px] text-[var(--muted)]">
          Loading members…
        </p>
      )}
      {controller.members.status === "error" && (
        <p role="alert" className="text-[13px] text-[var(--muted)]">
          The member list could not be loaded.
        </p>
      )}
      {controller.members.status === "ready" && (
        <table className="w-full text-left text-[13px]">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
              <th scope="col" className="py-2 pr-4 font-medium">
                Email
              </th>
              <th scope="col" className="py-2 pr-4 font-medium">
                Status
              </th>
              <th scope="col" className="py-2 pr-4 font-medium">
                Roles
              </th>
              {showActions && (
                <th scope="col" className="py-2 font-medium">
                  Actions
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {controller.members.data.map((member) => (
              <tr
                key={member.user_id}
                className="border-b border-[var(--border-subtle)] text-[var(--text)]"
              >
                <td className="py-2 pr-4">{member.email}</td>
                <td className="py-2 pr-4">
                  {member.status === "suspended" ? "Suspended" : "Active"}
                </td>
                <td className="py-2 pr-4">{member.roles.map(roleLabel).join(", ")}</td>
                {showActions && (
                  <td className="py-2">
                    <MemberRowActions
                      member={member}
                      canManage={canManage}
                      canAssign={canAssign}
                      controller={controller}
                    />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
