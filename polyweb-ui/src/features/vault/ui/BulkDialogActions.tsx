import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"

/** Footer shared by the bulk and keyless-defaults dialogs: Cancel plus the
 * create action, or Done plus a retry once a run has produced outcome lines.
 * Leaving is disabled while writes are pending.
 */
export function BulkDialogActions({ attempted, pending, canSave, createLabel, onDismiss, onSave }: {
  attempted: boolean
  pending: boolean
  canSave: boolean
  createLabel: string
  onDismiss: () => void
  onSave: () => void
}) {
  return (
    <FormActions>
      <Button type="button" variant="outline" size="form" disabled={pending} onClick={onDismiss}>{attempted ? "Done" : "Cancel"}</Button>
      <Button type="button" size="form" pending={pending} disabled={pending || !canSave} onClick={onSave}>
        {attempted ? "Retry remaining" : createLabel}
      </Button>
    </FormActions>
  )
}
