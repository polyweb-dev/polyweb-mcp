import { oauthStatusText } from "@/domains/providers"
import type { OAuthGrantStatus } from "@/domains/providers"
import { StatusDot } from "@/shared/ui/StatusDot"
import type { StatusTone } from "@/shared/ui/StatusDot"
import { useCredentialOAuth } from "../model/useCredentialOAuth"

const EXPIRED_TEXT = "The code expired. Close and connect again."

const STATUS_TONE: Record<OAuthGrantStatus, StatusTone> = {
  pending: "neutral",
  connected: "positive",
  refresh_failed: "negative",
  disconnected: "neutral",
}

const STEP_CLASS = "grid grid-cols-[20px_minmax(0,1fr)] gap-2"
const STEP_NUMBER_CLASS = "tnum text-[var(--muted)]"

/**
 * Body of the Connect dialog: three plain steps (open the page, enter the
 * code, approve) and the live status, nothing else from the device flow.
 * Mounted only while the dialog is open, so closing it stops the polling.
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

  const expired = state.phase === "expired"
  const statusText = expired ? EXPIRED_TEXT : oauthStatusText(state.status)
  const tone: StatusTone = expired ? "warning" : STATUS_TONE[state.status]
  return (
    <div className="space-y-5 text-[13px] text-[var(--text)]">
      <ol className="space-y-3">
        <li className={STEP_CLASS}>
          <span className={STEP_NUMBER_CLASS}>1</span>
          <a
            href={state.device.verificationUri}
            target="_blank"
            rel="noopener noreferrer"
            className="fs-link w-fit"
          >
            Open verification page
          </a>
        </li>
        <li className={STEP_CLASS}>
          <span className={STEP_NUMBER_CLASS}>2</span>
          <div className="space-y-2">
            <p>Enter this code</p>
            <p
              data-testid="oauth-user-code"
              className="w-fit rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-1.5 font-mono text-[18px] tracking-widest text-[var(--text-strong)]"
            >
              {state.device.userCode}
            </p>
          </div>
        </li>
        <li className={STEP_CLASS}>
          <span className={STEP_NUMBER_CLASS}>3</span>
          <p>Approve access. This dialog updates on its own.</p>
        </li>
      </ol>
      <p role="status">
        <StatusDot tone={tone} label={statusText} />
      </p>
    </div>
  )
}
