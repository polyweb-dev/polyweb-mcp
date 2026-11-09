import type { ReactNode } from "react"
import { MoreHorizontal } from "lucide-react"
import type { ProjectMember } from "@/domains/projects"
import {
  MENU_ITEM_CLASS,
  MENU_ITEM_DANGER_CLASS,
  MENU_SEPARATOR_CLASS,
  MENU_TRIGGER_ICON_CLASS,
} from "@/shared/ui/menuStyles"
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover"
import type { ProjectMembersController } from "../model/useProjectMembersController"
import { MemberRoleItems } from "./MemberRoleItems"

/** One destructive member action waiting for its confirmation. */
export interface PendingMemberAction {
  title: string
  body: string
  confirm: string
  run: () => void
}

const LAST_ADMIN_REASON = "A project needs one active admin."

function menuButton(key: string, label: string, onClick: () => void, danger = false): ReactNode {
  return (
    <button key={key} type="button" className={danger ? MENU_ITEM_DANGER_CLASS : MENU_ITEM_CLASS} onClick={onClick}>
      {label}
    </button>
  )
}

export interface MemberActionsMenuProps {
  member: ProjectMember
  projectName: string
  canManage: boolean
  canAssign: boolean
  /** The caller's own row offers no Suspend. */
  isSelf: boolean
  /** The member is the project's only active admin: the admin role stays. */
  lastAdmin: boolean
  controller: ProjectMembersController
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Route one destructive item through the confirmation dialog. */
  onConfirm: (action: PendingMemberAction) => void
  ownerId?: string | null
  callerIsProviderOwner?: boolean
  onPermissions?: (member: ProjectMember) => void
  onTransfer?: (member: ProjectMember) => void
}

function statusReason(isOwner: boolean, lastAdmin: boolean, admin: boolean, ownerId: string | null | undefined): string | undefined {
  if (isOwner) return "Transfer provider ownership first."
  if (lastAdmin) return LAST_ADMIN_REASON
  if (admin && ownerId === undefined) return "Provider ownership is not available yet."
  return undefined
}

function ownershipLabel(props: { allowed: boolean; isOwner: boolean; isSelf: boolean; admin: boolean; active: boolean }): string | undefined {
  if (!props.allowed) return undefined
  if (props.isOwner) return "Transfer provider ownership"
  if (!props.isSelf && props.admin && props.active) return "Make provider owner"
  return undefined
}

/** Action menu for one project member. */
export function MemberActionsMenu({
  member,
  projectName,
  canManage,
  canAssign,
  isSelf,
  lastAdmin,
  controller,
  open,
  onOpenChange,
  onConfirm,
  ownerId,
  callerIsProviderOwner = false,
  onPermissions,
  onTransfer,
}: MemberActionsMenuProps) {
  const directly = (run: () => Promise<void>) => () => {
    onOpenChange(false)
    void run()
  }

  const admin = member.role === "admin"
  const isOwner = ownerId != null && member.user_id === ownerId
  const reason = statusReason(isOwner, lastAdmin, admin, ownerId)
  const ownershipAction = ownershipLabel({ allowed: callerIsProviderOwner && onTransfer !== undefined,
    isOwner, isSelf, admin, active: member.account_active && member.status === "active" })

  const suspend = () =>
    onConfirm({
      title: `Suspend ${member.email}`,
      body: `${member.email} loses access to ${projectName} until reactivated`,
      confirm: "Suspend",
      run: () => void controller.setStatus(member, "suspended"),
    })

  const removeMember = () =>
    onConfirm({
      title: `Remove ${member.email}`,
      body: `${member.email} loses all access to ${projectName}`,
      confirm: "Remove from project",
      run: () => void controller.remove(member),
    })

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger
        aria-label={`Actions for ${member.email}`}
        disabled={controller.pending}
        className={MENU_TRIGGER_ICON_CLASS}
      >
        <MoreHorizontal aria-hidden="true" className="size-4" />
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={4} className="w-60 p-1">
        {canAssign && (
          <MemberRoleItems member={member} admin={admin} isSelf={isSelf} reason={reason} ownershipAction={ownershipAction}
            onPermissions={onPermissions && (() => { onOpenChange(false); onPermissions(member) })}
            onTransfer={onTransfer && (() => { onOpenChange(false); onTransfer(member) })}
            onChangeRole={directly(() => controller.assign(member, admin ? "project_member" : "project_admin"))} />
        )}
        {canManage && (
          <>
            {canAssign && <div aria-hidden="true" className={MENU_SEPARATOR_CLASS} />}
            {member.status === "active"
              ? !isSelf && <button type="button" className={MENU_ITEM_DANGER_CLASS} disabled={Boolean(reason)} title={reason} onClick={suspend}>Suspend member</button>
              : menuButton("reactivate", "Reactivate member", directly(() => controller.setStatus(member, "active")))}
            <button type="button" className={MENU_ITEM_DANGER_CLASS} disabled={Boolean(reason)} title={reason} onClick={removeMember}>Remove from project</button>
          </>
        )}
      </PopoverContent>
    </Popover>
  )
}
