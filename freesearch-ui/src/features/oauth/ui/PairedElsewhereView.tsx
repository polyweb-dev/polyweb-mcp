import { AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"

export interface PairedElsewhereViewProps {
  revoked: boolean
  pending: boolean
  error: string | null
  canUnpair: boolean
  onUnpair: () => void
}

/** 409 state: already paired elsewhere, with optional disconnect. */
export function PairedElsewhereView({ revoked, pending, error, canUnpair, onUnpair }: PairedElsewhereViewProps) {
  return (
    <div className="space-y-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] p-3.5" data-testid="oauth-device-paired">
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="h-4 w-4 text-[var(--status-warning)] shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="text-[13px] font-medium text-[var(--text-strong)]">
            Already connected elsewhere.
          </p>
          <p className="text-[12px] text-[var(--muted)] leading-relaxed">
            {revoked
              ? "Disconnected. Get a new code to pair again."
              : canUnpair
                ? "This provider is already paired, possibly in another session. Disconnect it first, then get a new code."
                : "This provider is already paired, possibly in another session. Disconnect it from the connected session to pair again."}
          </p>
        </div>
      </div>
      {error && (
        <p
          role="alert"
          data-testid="oauth-device-error"
          className="rounded border border-[var(--status-danger)]/40 bg-[var(--surface)] p-2 text-[12px]"
          style={{ color: "var(--status-danger)" }}
        >
          {error}
        </p>
      )}
      {!revoked && canUnpair && (
        <div className="pt-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="oauth-device-unpair"
            disabled={pending}
            onClick={onUnpair}
            className="h-8 px-3 text-[12px]"
          >
            {pending ? "Disconnecting…" : "Disconnect"}
          </Button>
        </div>
      )}
    </div>
  )
}

