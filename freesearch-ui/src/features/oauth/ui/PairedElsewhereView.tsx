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
    <div className="space-y-2" data-testid="oauth-device-paired">
      <p className="text-[13px] font-medium text-[var(--text-strong)]">
        Already connected elsewhere.
      </p>
      <p className="text-[13px] text-[var(--muted)]">
        {revoked
          ? "Disconnected. Get a new code to pair again."
          : canUnpair
            ? "This provider is already paired, possibly in another session. Disconnect it first, then get a new code."
            : "This provider is already paired, possibly in another session. Disconnect it from the connected session to pair again."}
      </p>
      {error && (
        <p
          role="alert"
          data-testid="oauth-device-error"
          className="text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          {error}
        </p>
      )}
      {!revoked && canUnpair && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="oauth-device-unpair"
          disabled={pending}
          onClick={onUnpair}
        >
          {pending ? "Disconnecting…" : "Disconnect"}
        </Button>
      )}
    </div>
  )
}
