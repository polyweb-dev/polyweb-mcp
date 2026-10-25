import { PROJECT_ROLE_KEYS, PROJECT_ROLE_LABELS } from "@/domains/projects"
import type { MembershipStatus, ProjectMember, ProjectRoleKey } from "@/domains/projects"
import type { ProjectMembersController } from "../model/useProjectMembersController"

const ACTION_BUTTON =
  "rounded px-2 py-1 text-[12px] text-[var(--muted)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] disabled:opacity-50"

export interface MemberRowActionsProps {
  member: ProjectMember
  canManage: boolean
  canAssign: boolean
  controller: ProjectMembersController
}

function statusAction(member: ProjectMember): { status: MembershipStatus; label: string } {
  return member.status === "active"
    ? { status: "suspended", label: "Suspend" }
    : { status: "active", label: "Reactivate" }
}

/**
 * Per-member administration controls.
 *
 * Every control is gated by the caller's live project permissions: membership
 * changes need `members.manage`, role changes need `roles.assign`. The row
 * never decides from a stored role name.
 */
export function MemberRowActions({
  member,
  canManage,
  canAssign,
  controller,
}: MemberRowActionsProps) {
  const toggle = statusAction(member)
  const heldRoles = member.roles.filter(isProjectRole)
  const addable = PROJECT_ROLE_KEYS.filter((role) => !member.roles.includes(role))
  const confirming = controller.confirmingUserId === member.user_id

  return (
    <div className="flex flex-wrap items-center gap-2">
      {canManage && (
        <>
          <button
            type="button"
            className={ACTION_BUTTON}
            disabled={controller.pending}
            onClick={() => void controller.setStatus(member, toggle.status)}
          >
            {toggle.label}
          </button>
          {confirming ? (
            <button
              type="button"
              className={ACTION_BUTTON}
              disabled={controller.pending}
              onClick={() => void controller.remove(member)}
            >
              Confirm removal
            </button>
          ) : (
            <button
              type="button"
              className={ACTION_BUTTON}
              disabled={controller.pending}
              onClick={() => controller.requestRemove(member.user_id)}
            >
              Remove
            </button>
          )}
        </>
      )}
      {canAssign && (
        <>
          {heldRoles.map((role) => (
            <button
              key={role}
              type="button"
              className={ACTION_BUTTON}
              disabled={controller.pending}
              aria-label={`Remove role ${PROJECT_ROLE_LABELS[role]} from ${member.email}`}
              onClick={() => void controller.unassign(member, role)}
            >
              − {PROJECT_ROLE_LABELS[role]}
            </button>
          ))}
          {addable.length > 0 && (
            <select
              aria-label={`Add role to ${member.email}`}
              className="rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2 py-1 text-[12px] text-[var(--text)]"
              value=""
              disabled={controller.pending}
              onChange={(event) => {
                const role = event.target.value
                if (isProjectRole(role)) void controller.assign(member, role)
              }}
            >
              <option value="">Add role…</option>
              {addable.map((role) => (
                <option key={role} value={role}>
                  {PROJECT_ROLE_LABELS[role]}
                </option>
              ))}
            </select>
          )}
        </>
      )}
    </div>
  )
}

function isProjectRole(value: string): value is ProjectRoleKey {
  return (PROJECT_ROLE_KEYS as readonly string[]).includes(value)
}
