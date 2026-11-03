import { Modal } from "@/shared/ui/Modal"
import { Button } from "@/shared/ui/button"

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmLabel: string
  pending: boolean
  onConfirm: () => void
  onClose: () => void
}

/** Small destructive confirmation dialog. */
export function ConfirmDialog(props: ConfirmDialogProps) {
  const { open, title, message, confirmLabel, pending, onConfirm, onClose } = props
  return (
    <Modal isOpen={open} onClose={onClose} title={title} maxWidth="md">
      <div className="space-y-4 text-[13px]">
        <p className="text-[var(--text)]">{message}</p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" disabled={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
