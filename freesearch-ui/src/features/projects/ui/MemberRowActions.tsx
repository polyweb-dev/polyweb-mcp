import { useState } from "react"
import type { ProjectMember } from "@/domains/projects"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"
import type { ProjectMembersController } from "../model/useProjectMembersController"
import { MemberActionsMenu } from "./MemberActionsMenu"
import type { PendingMemberAction } from "./MemberActionsMenu"

export interface MemberRowActionsProps {
  member: ProjectMember
  projectName: string
  canManage: boolean
  canAssign: boolean
  /** The caller's own row offers no Suspend. */
  isSelf: boolean
  /** The member is the project's only active admin. */
  lastAdmin: boolean
  controller: ProjectMembersController
  ownerId?: string | null
  callerIsProviderOwner?: boolean
  onPermissions?: (member: ProjectMember) => void
  onTransfer?: (member: ProjectMember) => void
}

const NO_ACTION: PendingMemberAction = { title: "", body: "", confirm: "", run: () => {} }

/**
 * Open and error state of the confirmation: before a submit it just
 * confirms; a clean finish closes it, a server refusal (e.g. last admin)
 * keeps it open and shows the message inside.
 */
function confirmState(
  action: PendingMemberAction | null,
  submitted: boolean,
  controller: Pick<ProjectMembersController, "pending" | "message">
): { open: boolean; error: string | null } {
  if (action === null) return { open: false, error: null }
  if (!submitted) return { open: true, error: null }
  if (controller.pending) return { open: true, error: null }
  return { open: controller.message !== null, error: controller.message }
}

/**
 * Per-member administration controls: one action menu plus the shared
 * confirmation dialog of destructive items. Every action is gated by the
 * caller's live project permissions — membership changes need
 * `members.manage`, role changes need `roles.assign`.
 */
export function MemberRowActions({ controller, ...menuProps }: MemberRowActionsProps) {
  const [open, setOpen] = useState(false)
  const [action, setAction] = useState<PendingMemberAction | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const dialog = confirmState(action, submitted, controller)
  const shown = action ?? NO_ACTION

  return (
    <>
      <MemberActionsMenu
        {...menuProps}
        controller={controller}
        open={open}
        onOpenChange={setOpen}
        onConfirm={(next) => {
          setSubmitted(false)
          setAction(next)
          setOpen(false)
        }}
      />
      <ConfirmDialog
        open={dialog.open}
        title={shown.title}
        message={shown.body}
        confirmLabel={shown.confirm}
        error={dialog.error}
        pending={controller.pending}
        onClose={() => {
          setSubmitted(false)
          setAction(null)
        }}
        onConfirm={() => {
          setSubmitted(true)
          shown.run()
        }}
      />
    </>
  )
}
