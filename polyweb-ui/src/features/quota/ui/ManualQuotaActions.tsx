import { useState } from "react"
import { Button } from "@/shared/ui/button"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"
import { FormActions } from "@/shared/ui/FormActions"
import { BALANCE_ENTRY } from "../model/quotaLabels"

export interface ManualQuotaActionsProps {
  isEditing: boolean
  canDelete: boolean
  pending: boolean
  saving: boolean
  deleting: boolean
  onCancel: () => void
  onDelete: () => void
}

/**
 * Dialog footer: clear entry on the left, then Cancel and Save on the right.
 * Clearing a saved entry asks for confirmation first.
 */
export function ManualQuotaActions({
  isEditing,
  canDelete,
  pending,
  saving,
  deleting,
  onCancel,
  onDelete,
}: ManualQuotaActionsProps) {
  const [confirming, setConfirming] = useState(false)
  const clear =
    isEditing && canDelete ? (
      <Button
        type="button"
        variant="ghost"
        size="form"
        data-testid="manual-quota-clear"
        disabled={pending}
        onClick={() => setConfirming(true)}
      >
        {deleting ? "Clearing…" : "Clear entry"}
      </Button>
    ) : undefined
  return (
    <>
      <FormActions {...(clear !== undefined ? { start: clear } : {})}>
        <Button
          type="button"
          variant="outline"
          size="form"
          data-testid="manual-quota-cancel"
          disabled={pending}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button type="submit" size="form" data-testid="manual-quota-save" disabled={deleting} pending={saving}>
          Save balance
        </Button>
      </FormActions>
      <ConfirmDialog
        open={confirming}
        title={"Clear " + BALANCE_ENTRY.toLowerCase()}
        message="The saved balance and its estimate leave this provider"
        confirmLabel="Clear entry"
        pending={pending}
        onClose={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false)
          onDelete()
        }}
      />
    </>
  )
}
