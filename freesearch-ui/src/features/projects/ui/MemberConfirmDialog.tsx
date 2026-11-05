import { Button } from "@/shared/ui/button"
import { Modal } from "@/shared/ui/Modal"

export interface PendingMemberAction {
  title: string
  body: string
  confirm: string
  run: () => void
}

export interface MemberConfirmDialogProps {
  open: boolean
  action: PendingMemberAction | null
  error: string | null
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}

/**
 * Confirmation dialog of one destructive member action — suspend, removal or
 * dropping a project admin role. A server refusal like the last-admin rule
 * renders inside the dialog rather than being lost.
 */
export function MemberConfirmDialog({
  open,
  action,
  error,
  pending,
  onCancel,
  onConfirm,
}: MemberConfirmDialogProps) {
  return (
    <Modal isOpen={open} onClose={onCancel} title={action?.title} maxWidth="sm">
      <div className="pt-1">
        <p className="text-[13px] text-[var(--text)]">{action?.body}</p>
        {error !== null && (
          <p role="alert" className="mt-3 text-[13px] text-[var(--status-danger)]">
            {error}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" size="form" variant="outline" autoFocus onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="button"
            size="form"
            variant="destructive"
            disabled={pending}
            onClick={onConfirm}
          >
            {action?.confirm}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
