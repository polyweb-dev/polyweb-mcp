import type { ReactNode } from "react"
import { MoreHorizontal } from "lucide-react"
import { PROJECT_ROLE_KEYS, PROJECT_ROLE_LABELS } from "@/domains/projects"
import type { ProjectMember, ProjectRoleKey } from "@/domains/projects"
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover"
import type { ProjectMembersController } from "../model/useProjectMembersController"
import type { PendingMemberAction } from "./MemberConfirmDialog"

const MENU_ITEM =
  "flex w-full items-center rounded px-2 py-1.5 text-left text-[13px] text-[var(--text)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] disabled:opacity-50"
const MENU_ITEM_DANGER = `${MENU_ITEM} text-[var(--status-danger)]`

function menuButton(
  key: string,
  label: string,
  onClick: () => void,
  danger = false
): ReactNode {
  return (
    <button key={key} type="button" className={danger ? MENU_ITEM_DANGER : MENU_ITEM} onClick={onClick}>
      {label}
    </button>
  )
}

export interface MemberActionsMenuProps {
  member: ProjectMember
  projectName: string
  canManage: boolean
  canAssign: boolean
  controller: ProjectMembersController
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Route one destructive item through the confirmation dialog. */
  onConfirm: (action: PendingMemberAction) => void
}

/**
 * Action menu of one member row. Direct items run at once; destructive items
 * hand a `PendingMemberAction` up for the confirmation dialog.
 */
export function MemberActionsMenu({
  member,
  projectName,
  canManage,
  canAssign,
  controller,
  open,
  onOpenChange,
  onConfirm,
}: MemberActionsMenuProps) {
  const heldRoles = member.roles.filter(isProjectRole)
  const addable = PROJECT_ROLE_KEYS.filter((role) => !member.roles.includes(role))

  const directly = (run: () => Promise<void>) => () => {
    onOpenChange(false)
    void run()
  }

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger
        aria-label={`Actions for ${member.email}`}
        disabled={controller.pending}
        className="grid size-8 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] disabled:opacity-50"
      >
        <MoreHorizontal aria-hidden="true" className="size-4" />
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={4} className="w-56 p-1">
        {canAssign && (
          <>
            {addable.map((role) =>
              menuButton(
                `add-${role}`,
                `Make ${PROJECT_ROLE_LABELS[role]}`,
                directly(() => controller.assign(member, role))
              )
            )}
            {heldRoles.map((role) =>
              role === "project_admin"
                ? menuButton(
                    `remove-${role}`,
                    `Remove ${PROJECT_ROLE_LABELS[role]} role`,
                    () =>
                      onConfirm({
                        title: `Remove ${PROJECT_ROLE_LABELS[role]} role`,
                        body: `${member.email} loses the ${PROJECT_ROLE_LABELS[role]} role in ${projectName}.`,
                        confirm: "Remove role",
                        run: () => void controller.unassign(member, role),
                      }),
                    true
                  )
                : menuButton(
                    `remove-${role}`,
                    `Remove ${PROJECT_ROLE_LABELS[role]} role`,
                    directly(() => controller.unassign(member, role))
                  )
            )}
          </>
        )}
        {canManage && (
          <>
            {member.status === "active"
              ? menuButton("suspend", "Suspend", () =>
                  onConfirm({
                    title: `Suspend ${member.email}`,
                    body: `${member.email} loses access to ${projectName} until reactivated.`,
                    confirm: "Suspend",
                    run: () => void controller.setStatus(member, "suspended"),
                  }), true)
              : menuButton(
                  "reactivate",
                  "Reactivate",
                  directly(() => controller.setStatus(member, "active"))
                )}
            {menuButton("remove", "Remove from project", () =>
              onConfirm({
                title: `Remove ${member.email}`,
                body: `${member.email} loses all access to ${projectName}.`,
                confirm: "Remove from project",
                run: () => void controller.remove(member),
              }), true)}
          </>
        )}
      </PopoverContent>
    </Popover>
  )
}

function isProjectRole(value: string): value is ProjectRoleKey {
  return (PROJECT_ROLE_KEYS as readonly string[]).includes(value)
}
