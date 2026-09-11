import { Button } from "@/components/ui/button"
import type { PairingPhase } from "../model/pairingFlow"

export interface PairingDialogFooterProps {
  phase: PairingPhase
  revokedElsewhere: boolean
  onClose: () => void
  onRetry: () => void
}

/** Dialog footer: cancel always, retry once the code can no longer succeed. */
export function PairingDialogFooter({ phase, revokedElsewhere, onClose, onRetry }: PairingDialogFooterProps) {
  const failed = phase === "denied" || phase === "expired" || phase === "failed"
  const showRetry = failed || (phase === "paired" && revokedElsewhere)
  return (
    <div className="mt-4 flex items-center justify-end gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="oauth-device-cancel"
        onClick={onClose}
      >
        Cancel
      </Button>
      {showRetry && (
        <Button type="button" size="sm" data-testid="oauth-device-retry" onClick={onRetry}>
          Get a new code
        </Button>
      )}
    </div>
  )
}
