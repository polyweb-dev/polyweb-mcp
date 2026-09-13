import { Modal } from "@/shared/ui/Modal"
import { Loader2, CheckCircle2, AlertCircle } from "lucide-react"
import type {
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/domains/providers/api/oauthWire"
import { usePairingFlow } from "../model/usePairingFlow"
import { PairedElsewhereView } from "./PairedElsewhereView"
import { PairingDialogFooter } from "./PairingDialogFooter"
import { PairingFailedView } from "./PairingFailedView"
import { PairingPendingView } from "./PairingPendingView"

export interface OAuthPairingModalProps {
  open: boolean
  providerId: string
  providerName: string
  onClose: () => void
  onPaired: () => Promise<unknown>
  beginFlow: () => Promise<BackendOAuthDeviceCode>
  checkStatus: () => Promise<BackendOAuthStatus>
  /**
   * Revokes a live pairing elsewhere so the user can re-pair; used only
   * after a 409. The row always provides it; direct renders may omit it,
   * in which case the paired state explains without offering Disconnect.
   */
  onRevokePairing?: () => Promise<unknown>
  /** Test seam: poll delay override (defaults to the server interval). */
  statusPollMs?: number
}

/**
 * One focused pairing moment: code + approval link + countdown. Mount only
 * while open; the flow begins exactly once per mount and the single poll
 * chain dies on unmount, terminal state, or retry.
 */
export function OAuthPairingModal(props: OAuthPairingModalProps) {
  const { open, providerName, onClose, onRevokePairing } = props
  const flow = usePairingFlow(props)

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      maxWidth="md"
      title={"Connect " + providerName}
      subtitle="Approve in your browser to share your Parallel balance."
    >
      <div data-testid="oauth-device-dialog">
        {flow.phase === "starting" && (
          <div data-testid="oauth-device-loading" className="flex items-center gap-2.5 py-4 text-[13px] text-[var(--muted)]">
            <Loader2 className="h-4 w-4 animate-spin text-[var(--signal)]" />
            <span>Starting secure approval…</span>
          </div>
        )}
        {flow.phase === "pending" && flow.device && (
          <PairingPendingView
            userCode={flow.device.user_code}
            approvalUrl={flow.approvalUrl}
            totalSec={flow.device.expires_in}
            remainingSec={flow.remainingSec}
            copied={flow.copied}
            onCopy={flow.copyCode}
            providerName={providerName}
          />
        )}
        {flow.phase === "ready" && (
          <div data-testid="oauth-device-loading" className="flex items-center gap-2.5 py-4 text-[13px] text-[var(--status-healthy)]">
            <CheckCircle2 className="h-4 w-4 text-[var(--status-healthy)]" />
            <span>Connected. Refreshing usage…</span>
          </div>
        )}
        {(flow.phase === "denied" || flow.phase === "expired") && (
          <PairingFailedView kind={flow.phase} />
        )}
        {flow.phase === "paired" && (
          <PairedElsewhereView
            revoked={flow.revokedElsewhere}
            pending={flow.unpairPending}
            error={flow.error}
            canUnpair={onRevokePairing !== undefined}
            onUnpair={flow.unpair}
          />
        )}
        {flow.phase === "failed" && flow.error && (
          <div
            role="alert"
            data-testid="oauth-device-error"
            className="flex items-start gap-2.5 rounded-lg border border-[var(--status-danger)]/40 bg-[var(--surface)] p-3 text-[13px]"
            style={{ color: "var(--status-danger)" }}
          >
            <AlertCircle className="h-4 w-4 text-[var(--status-danger)] shrink-0 mt-0.5" />
            <span>{flow.error}</span>
          </div>
        )}
        <PairingDialogFooter
          phase={flow.phase}
          revokedElsewhere={flow.revokedElsewhere}
          onClose={onClose}
          onRetry={flow.begin}
        />
      </div>
    </Modal>
  )
}

