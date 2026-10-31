import type { ProjectApiKey } from "@/domains/projects"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"

const ACTION_BUTTON =
  "rounded px-2 py-1 text-[12px] text-[var(--muted)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] disabled:opacity-50"

export interface ApiKeyRowActionsProps {
  apiKey: ProjectApiKey
  /** Rotation is offered only for a rotatable key of an active project. */
  canRotate: boolean
  controller: ProjectApiKeysController
}

/**
 * Per-key controls of the API keys table.
 *
 * Only an active key has controls. Revoke asks for an inline confirmation
 * before it sends the request; Rotate opens the rotate dialog.
 */
export function ApiKeyRowActions({ apiKey, canRotate, controller }: ApiKeyRowActionsProps) {
  if (apiKey.status !== "active") return null
  const confirming = controller.confirmingRevokeId === apiKey.id

  if (confirming) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={ACTION_BUTTON}
          disabled={controller.pending}
          onClick={() => void controller.revoke(apiKey)}
        >
          Confirm revoke
        </button>
        <button
          type="button"
          className={ACTION_BUTTON}
          disabled={controller.pending}
          onClick={() => controller.requestRevoke(null)}
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {canRotate && (
        <button
          type="button"
          className={ACTION_BUTTON}
          disabled={controller.pending}
          aria-label={`Rotate ${apiKey.label}`}
          onClick={() => controller.openRotate(apiKey)}
        >
          Rotate
        </button>
      )}
      <button
        type="button"
        className={ACTION_BUTTON}
        disabled={controller.pending}
        aria-label={`Revoke ${apiKey.label}`}
        onClick={() => controller.requestRevoke(apiKey.id)}
      >
        Revoke
      </button>
    </div>
  )
}
