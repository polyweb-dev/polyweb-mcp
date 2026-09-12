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
    <div className="mt-5 flex items-center justify-end gap-2 pt-3 border-t border-[var(--border-subtle)]">
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="oauth-device-cancel"
        onClick={onClose}
        className="h-8 px-3.5 text-[12px]"
      >
        Cancel
      </Button>
      {showRetry && (
        <Button
          type="button"
          size="sm"
          data-testid="oauth-device-retry"
          onClick={onRetry}
          className="h-8 px-3.5 text-[12px] bg-[var(--signal)] hover:bg-[var(--signal)]/90 text-white"
        >
          Get a new code
        </Button>
      )}
    </div>
  )
}

