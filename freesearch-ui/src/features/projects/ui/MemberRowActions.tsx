import { useState } from "react"
import type { ProjectMember } from "@/domains/projects"
import type { ProjectMembersController } from "../model/useProjectMembersController"
import { MemberActionsMenu } from "./MemberActionsMenu"
import { MemberConfirmDialog } from "./MemberConfirmDialog"
import type { PendingMemberAction } from "./MemberConfirmDialog"

export interface MemberRowActionsProps {
  member: ProjectMember
  projectName: string
  canManage: boolean
  canAssign: boolean
  controller: ProjectMembersController
}

/**
 * Per-member administration controls: one action menu plus the confirmation
 * dialog of destructive items. Every action is gated by the caller's live
 * project permissions — membership changes need `members.manage`, role
 * changes need `roles.assign`.
 *
 * The dialog settles from the controller: before a submit it just confirms;
 * a clean finish closes it, a server refusal (e.g. last admin) keeps it open
 * and shows the message inside.
 */
export function MemberRowActions({
  member,
  projectName,
  canManage,
  canAssign,
  controller,
}: MemberRowActionsProps) {
  const [open, setOpen] = useState(false)
  const [action, setAction] = useState<PendingMemberAction | null>(null)
  const [submitted, setSubmitted] = useState(false)

  const dialogOpen =
    action !== null && (!submitted || controller.pending || controller.message !== null)
  const dialogError =
    submitted && !controller.pending && controller.message !== null ? controller.message : null

  return (
    <>
      <MemberActionsMenu
        member={member}
        projectName={projectName}
        canManage={canManage}
        canAssign={canAssign}
        controller={controller}
        open={open}
        onOpenChange={setOpen}
        onConfirm={(next) => {
          setSubmitted(false)
          setAction(next)
          setOpen(false)
        }}
      />
      <MemberConfirmDialog
        open={dialogOpen}
        action={action}
        error={dialogError}
        pending={controller.pending}
        onCancel={() => {
          setSubmitted(false)
          setAction(null)
        }}
        onConfirm={() => {
          setSubmitted(true)
          action?.run()
        }}
      />
    </>
  )
}
