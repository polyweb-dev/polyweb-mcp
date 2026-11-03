import { oauthStatusText } from "@/domains/providers"
import { useCredentialOAuth } from "../model/useCredentialOAuth"

const EXPIRED_TEXT = "The code expired. Close and connect again."

/**
 * Body of the Connect dialog: the user code, the verification link and the
 * status, nothing else from the device flow. Mounted only while the dialog
 * is open, so closing it stops the polling.
 */
export function OAuthConnectPanel({ base, onConnected }: { base: string; onConnected: () => void }) {
  const state = useCredentialOAuth({ base, onConnected })

  if (state.phase === "starting") {
    return (
      <p role="status" className="text-[13px] text-[var(--muted)]">
        Starting the connection…
      </p>
    )
  }
  if (state.phase === "failed") {
    return (
      <p role="alert" className="text-[13px] text-[var(--status-danger)]">
        {state.message}
      </p>
    )
  }

  const statusText = state.phase === "expired" ? EXPIRED_TEXT : oauthStatusText(state.status)
  return (
    <div className="space-y-4 text-[13px]">
      <p className="text-[var(--muted)]">Enter this code on the verification page:</p>
      <p
        data-testid="oauth-user-code"
        className="font-mono text-[20px] tracking-widest text-[var(--text-strong)]"
      >
        {state.device.userCode}
      </p>
      <a
        href={state.device.verificationUri}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[var(--signal)] underline underline-offset-4"
      >
        Open verification page
      </a>
      <p role="status" className="text-[var(--text)]">
        {statusText}
      </p>
    </div>
  )
}
