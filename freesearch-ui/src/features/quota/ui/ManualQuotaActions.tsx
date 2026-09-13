import { Button } from "@/shared/ui/button"

export interface ManualQuotaActionsProps {
  isEditing: boolean
  canDelete: boolean
  pending: boolean
  saving: boolean
  deleting: boolean
  onCancel: () => void
  onDelete: () => void
}

/** Modal footer: clear-entry plus cancel/save actions. */
export function ManualQuotaActions({
  isEditing,
  canDelete,
  pending,
  saving,
  deleting,
  onCancel,
  onDelete,
}: ManualQuotaActionsProps) {
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <span>
        {isEditing && canDelete && (
          <Button
            type="button"
            variant="outline"
            size="lg" className="px-3"
            data-testid="manual-quota-clear"
            disabled={pending}
            onClick={onDelete}
          >
            {deleting ? "Clearing…" : "Clear entry"}
          </Button>
        )}
      </span>
      <span className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="lg" className="px-3"
          data-testid="manual-quota-cancel"
          disabled={pending}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button type="submit" size="lg" className="px-3" data-testid="manual-quota-save" disabled={pending}>
          {saving ? "Saving…" : isEditing ? "Save usage" : "Save budget"}
        </Button>
      </span>
    </div>
  )
}
