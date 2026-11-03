import { Button } from "@/shared/ui/button"
import type { CredentialActions } from "../model/useCredentialActions"
import type { CredentialRef } from "../model/credentialRoutes"

interface CredentialRowActionsProps {
  credential: CredentialRef
  authMode: string
  actions: CredentialActions
}

/** Rotate (API key), Connect/Disconnect (OAuth) and Delete of one credential row. */
export function CredentialRowActions({ credential, authMode, actions }: CredentialRowActionsProps) {
  const { label } = credential
  const disabled = actions.status.pending
  return (
    <div className="flex flex-wrap justify-end gap-1">
      {authMode === "oauth" ? (
        <>
          <Button size="sm" variant="outline" aria-label={`Connect ${label}`} disabled={disabled} onClick={() => actions.openConnect(credential)}>
            Connect
          </Button>
          <Button size="sm" variant="ghost" aria-label={`Disconnect ${label}`} disabled={disabled} onClick={() => void actions.disconnect(credential)}>
            Disconnect
          </Button>
        </>
      ) : (
        <Button size="sm" variant="outline" aria-label={`Rotate key ${label}`} disabled={disabled} onClick={() => actions.openRotate(credential)}>
          Rotate
        </Button>
      )}
      <Button size="sm" variant="destructive" aria-label={`Delete key ${label}`} disabled={disabled} onClick={() => actions.requestDelete(credential)}>
        Delete
      </Button>
    </div>
  )
}
