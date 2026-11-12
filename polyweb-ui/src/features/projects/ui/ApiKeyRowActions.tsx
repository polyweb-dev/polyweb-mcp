import { RefreshCw, Trash2 } from "lucide-react"
import type { ProjectApiKey } from "@/domains/projects"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"
import { RowActionsMenu, type RowAction } from "@/shared/ui/RowActionsMenu"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"

export interface ApiKeyRowActionsProps {
  apiKey: ProjectApiKey
  /** Rotation is offered only for a rotatable key of an active project. */
  canRotate: boolean
  controller: ProjectApiKeysController
}

/**
 * Per-key controls of the API keys table.
 *
 * Only an active key has controls. The row menu offers Rotate and Revoke;
 * Rotate opens the rotate dialog and Revoke opens the shared confirmation
 * before it sends the request. A revoke failure shows as the page alert.
 */
export function ApiKeyRowActions({ apiKey, canRotate, controller }: ApiKeyRowActionsProps) {
  if (apiKey.status !== "active") return null

  const actions: RowAction[] = [
    ...(canRotate
      ? [{ key: "rotate", label: "Rotate key", icon: RefreshCw, onSelect: () => controller.openRotate(apiKey) }]
      : []),
    { key: "revoke", label: "Revoke key", icon: Trash2, danger: true, onSelect: () => controller.requestRevoke(apiKey.id) },
  ]
  return (
    <>
      <RowActionsMenu
        label={`Actions for ${apiKey.label}`}
        actions={actions}
        disabled={controller.pending}
      />
      <ConfirmDialog
        open={controller.confirmingRevokeId === apiKey.id}
        title={`Revoke ${apiKey.label}`}
        message="Programs that use this key stop working at once. You cannot undo this change"
        confirmLabel="Revoke key"
        pending={controller.pending}
        onConfirm={() => void controller.revoke(apiKey)}
        onClose={() => controller.requestRevoke(null)}
      />
    </>
  )
}
