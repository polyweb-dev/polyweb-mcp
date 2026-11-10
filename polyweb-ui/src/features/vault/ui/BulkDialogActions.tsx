import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"

/** Footer shared by the bulk and keyless-defaults dialogs: Cancel plus the
 * create action, or Done plus a retry once outcome lines exist.
 */
export function BulkDialogActions({ done, pending, canSave, createLabel, onDismiss, onSave }: {
  done: boolean
  pending: boolean
  canSave: boolean
  createLabel: string
  onDismiss: () => void
  onSave: () => void
}) {
  return (
    <FormActions>
      <Button type="button" variant="outline" size="form" onClick={onDismiss}>{done ? "Done" : "Cancel"}</Button>
      <Button type="button" size="form" pending={pending} disabled={pending || !canSave} onClick={onSave}>
        {done ? "Retry remaining" : createLabel}
      </Button>
    </FormActions>
  )
}
