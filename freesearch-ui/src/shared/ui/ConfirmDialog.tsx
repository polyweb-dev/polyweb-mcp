import type { ReactNode } from "react"
import { Button } from "./button"
import { FormActions } from "./FormActions"
import { Modal } from "./Modal"

export interface ConfirmDialogProps {
  open: boolean
  title: ReactNode
  message: ReactNode
  confirmLabel: string
  pending: boolean
  onConfirm: () => void
  onClose: () => void
  /** A server refusal, shown inside the dialog instead of being lost. */
  error?: string | null
  /** `danger` (default) for destructive actions, `default` for the rest. */
  tone?: "danger" | "default"
}

/**
 * The one confirmation dialog: a short message, an optional error, Cancel
 * first and the confirm action last. Cancel takes the initial focus so Enter
 * never confirms a destructive action by accident.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  pending,
  onConfirm,
  onClose,
  error = null,
  tone = "danger",
}: ConfirmDialogProps) {
  return (
    <Modal isOpen={open} onClose={onClose} title={title} maxWidth="md">
      <div className="text-[13px] leading-5 text-[var(--text)]">{message}</div>
      {error !== null && (
        <p role="alert" className="mt-3 text-[13px] text-[var(--status-danger)]">
          {error}
        </p>
      )}
      <FormActions>
        <Button type="button" size="form" variant="outline" autoFocus onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="button"
          size="form"
          variant={tone === "danger" ? "destructive" : "default"}
          disabled={pending}
          onClick={onConfirm}
        >
          {confirmLabel}
        </Button>
      </FormActions>
    </Modal>
  )
}
