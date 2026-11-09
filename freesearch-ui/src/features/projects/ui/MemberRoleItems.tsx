import type { ProjectMember } from "@/domains/projects"
import { MENU_ITEM_CLASS } from "@/shared/ui/menuStyles"

interface Props {
  member: ProjectMember
  admin: boolean
  isSelf: boolean
  reason?: string
  ownershipAction?: string
  onPermissions?: () => void
  onTransfer?: () => void
  onChangeRole: () => void
}

export function MemberRoleItems({ member, admin, isSelf, reason, ownershipAction, onPermissions, onTransfer, onChangeRole }: Props) {
  const unavailable = member.role === undefined
  return (
    <div role="group" aria-label="Roles">
      {onPermissions && <button type="button" className={MENU_ITEM_CLASS} onClick={onPermissions}>{admin ? "View permissions" : "Edit permissions"}</button>}
      {!isSelf && (
        <button type="button" className={MENU_ITEM_CLASS} disabled={unavailable || (admin && Boolean(reason))}
          title={unavailable ? "This action is not available yet." : reason} onClick={onChangeRole}>
          {admin ? "Make developer" : "Make project admin"}
        </button>
      )}
      {ownershipAction && <button type="button" className={MENU_ITEM_CLASS} onClick={onTransfer}>{ownershipAction}</button>}
    </div>
  )
}
