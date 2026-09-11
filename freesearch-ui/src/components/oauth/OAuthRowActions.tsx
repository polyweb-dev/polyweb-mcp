import React, { useState } from "react"
import { Button } from "@/components/ui/button"
import { oauthErrorMessage } from "./useOAuthPairing"

/**
 * Two-step revoke: the first click arms, the second confirms. Revocation is
 * idempotent on the backend, so a confirmed click always settles the row.
 */
export const OAuthDisconnectButton: React.FC<{
  providerName: string
  onDisconnect: () => Promise<unknown>
}> = ({ providerName, onDisconnect }) => {
  const [armed, setArmed] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm(): Promise<void> {
    setPending(true)
    setError(null)
    try {
      await onDisconnect()
      setArmed(false)
    } catch (disconnectError) {
      setError(oauthErrorMessage(disconnectError, "Unable to disconnect"))
    } finally {
      setPending(false)
    }
  }

  if (!armed) {
    return (
      <Button
        type="button"
        variant="outline"
        size="lg"
          className="px-3"
        data-testid={`oauth-device-disconnect`}
        aria-label={`Disconnect ${providerName} balance`}
        onClick={() => {
          setArmed(true)
          setError(null)
        }}
      >
        Disconnect
      </Button>
    )
  }

  return (
    <span className="flex flex-wrap items-center justify-end gap-2">
      {error && (
        <span
          role="alert"
          data-testid={`oauth-device-disconnect-error`}
          className="text-[12px]"
          style={{ color: "var(--status-danger)" }}
        >
          {error}
        </span>
      )}
      <Button
        type="button"
        variant="outline"
        size="lg"
          className="px-3"
        data-testid={`oauth-device-keep`}
        disabled={pending}
        onClick={() => setArmed(false)}
      >
        Keep
      </Button>
      <Button
        type="button"
        variant="destructive"
        size="lg"
          className="px-3"
        data-testid={`oauth-device-confirm-disconnect`}
        disabled={pending}
        onClick={() => void confirm()}
      >
        {pending ? "Disconnecting…" : "Confirm disconnect"}
      </Button>
    </span>
  )
}
