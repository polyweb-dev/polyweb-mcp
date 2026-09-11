import React, { useCallback, useEffect, useRef, useState } from "react"
import { Modal } from "@/components/common/Modal"
import { Button, buttonVariants } from "@/components/ui/button"
import { cn } from "cn"
import type {
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/services/api/backendTypes"
import { ApiError } from "@/shared/api/http"
import { oauthErrorMessage } from "./useOAuthPairing"

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

type PairingPhase = "starting" | "pending" | "ready" | "denied" | "expired" | "failed" | "paired"

/** Terminal vendor verdicts; null while the user can still approve. */
function terminalPhaseFor(status: BackendOAuthStatus["status"]): PairingPhase | null {
  if (status === "ready") return "ready"
  if (status === "denied") return "denied"
  if (status === "expired" || status === "unpaired") return "expired"
  return null
}

/** "5:00" from 300 — clamps negatives to 0:00. */
export function formatCountdown(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(clamped / 60)
  const seconds = clamped % 60
  return `${minutes}:${seconds.toString().padStart(2, "0")}`
}

interface PairingFlow {
  phase: PairingPhase
  device: BackendOAuthDeviceCode | null
  error: string | null
  copied: boolean
  remainingSec: number
  approvalUrl: string | null
  revokedElsewhere: boolean
  unpairPending: boolean
  begin: () => void
  copyCode: () => void
  unpair: () => void
}

type FlowCallbacks = Pick<
  OAuthPairingModalProps,
  "beginFlow" | "checkStatus" | "onPaired" | "onClose" | "statusPollMs" | "onRevokePairing"
>

function usePairingFlow(callbacks: FlowCallbacks): PairingFlow {
  const [phase, setPhase] = useState<PairingPhase>("starting")
  const [device, setDevice] = useState<BackendOAuthDeviceCode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [revokedElsewhere, setRevokedElsewhere] = useState(false)
  const [unpairPending, setUnpairPending] = useState(false)
  const [expiresAt, setExpiresAt] = useState<number | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())
  // Latest callbacks without resubscribing: parent inline closures change
  // identity every render, but the flow must begin exactly once per mount.
  const callbacksRef = useRef(callbacks)
  const generation = useRef(0)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    callbacksRef.current = callbacks
  })

  const clearPollTimer = useCallback(() => {
    if (pollTimer.current !== null) {
      clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }, [])

  const alive = useCallback((gen: number): boolean => gen === generation.current, [])

  // Mutable flow clocks that timeouts read without resubscribing. The round
  // body is assigned inside begin() (never during render), so no callback
  // ever references itself and parent re-renders cannot restart the chain.
  const expiresAtRef = useRef<number | null>(null)
  const pollRoundRef = useRef<(gen: number, delayMs: number) => Promise<void>>(async () => {})

  const schedulePoll = useCallback((gen: number, delayMs: number): void => {
    pollTimer.current = setTimeout(() => {
      void pollRoundRef.current(gen, delayMs)
    }, delayMs)
  }, [])

  const begin = useCallback(async (): Promise<void> => {
    const gen = generation.current + 1
    generation.current = gen
    clearPollTimer()
    setPhase("starting")
    setError(null)
    setCopied(false)
    setRevokedElsewhere(false)
    pollRoundRef.current = async (roundGen: number, delayMs: number): Promise<void> => {
      let next: BackendOAuthStatus
      try {
        next = await callbacksRef.current.checkStatus()
      } catch (pollError) {
        if (!alive(roundGen)) return
        clearPollTimer()
        setError(oauthErrorMessage(pollError, "Unable to check approval status"))
        setPhase("failed")
        return
      }
      if (!alive(roundGen)) return
      const settledAt = Date.now()
      setNowMs(settledAt)
      const terminal = terminalPhaseFor(next.status)
      if (terminal === "ready") {
        setPhase("ready")
        clearPollTimer()
        try {
          await callbacksRef.current.onPaired()
        } catch (pairedError) {
          if (!alive(roundGen)) return
          setError(oauthErrorMessage(pairedError, "Paired, but usage failed to refresh"))
          setPhase("failed")
          return
        }
        if (alive(roundGen)) callbacksRef.current.onClose()
        return
      }
      if (terminal !== null || (expiresAtRef.current !== null && settledAt >= expiresAtRef.current)) {
        clearPollTimer()
        setPhase(terminal === "denied" ? "denied" : "expired")
        return
      }
      schedulePoll(roundGen, delayMs)
    }
    let code: BackendOAuthDeviceCode
    try {
      code = await callbacksRef.current.beginFlow()
    } catch (beginError) {
      if (!alive(gen)) return
      // 409 means a live pairing already exists: surface it explicitly and
      // let the user disconnect first. Never auto-retry the POST in a loop.
      if (beginError instanceof ApiError && beginError.status === 409) {
        setPhase("paired")
        return
      }
      setError(oauthErrorMessage(beginError, "Unable to start pairing"))
      setPhase("failed")
      return
    }
    if (!alive(gen)) return
    if (code.expires_in <= 0) {
      setDevice(code)
      setPhase("expired")
      return
    }
    const pollMs = callbacksRef.current.statusPollMs ?? Math.max(1, code.interval) * 1000
    setDevice(code)
    const deadline = Date.now() + code.expires_in * 1000
    setExpiresAt(deadline)
    expiresAtRef.current = deadline
    setNowMs(Date.now())
    setPhase("pending")
    schedulePoll(gen, pollMs)
  }, [alive, clearPollTimer, schedulePoll])

  useEffect(() => {
    // Mount-once flow start. Justified: the loading phase is mount state
    // (already the useState initial value), this fires once per mount, reads
    // no render output, and every async continuation is generation-guarded
    // with its timers cleared on unmount — no render cascade is possible.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void begin()
    return () => {
      generation.current += 1
      clearPollTimer()
    }
  }, [begin, clearPollTimer])

  const copyCode = useCallback(async (): Promise<void> => {
    if (!device || typeof navigator === "undefined" || !navigator.clipboard) return
    try {
      await navigator.clipboard.writeText(device.user_code)
    } catch {
      return
    }
    setCopied(true)
  }, [device])

  const unpair = useCallback(async (): Promise<void> => {
    const revoke = callbacksRef.current.onRevokePairing
    if (!revoke) return
    setUnpairPending(true)
    setError(null)
    try {
      await revoke()
      setRevokedElsewhere(true)
    } catch (unpairError) {
      setError(oauthErrorMessage(unpairError, "Unable to disconnect"))
    } finally {
      setUnpairPending(false)
    }
  }, [])

  const remainingSec =
    expiresAt === null ? 0 : Math.max(0, Math.ceil((expiresAt - nowMs) / 1000))
  const approvalUrl = device
    ? (device.verification_uri_complete ?? device.verification_uri)
    : null

  return {
    phase,
    device,
    error,
    copied,
    remainingSec,
    approvalUrl,
    revokedElsewhere,
    unpairPending,
    begin: () => void begin(),
    copyCode: () => void copyCode(),
    unpair: () => void unpair(),
  }
}

/**
 * One focused pairing moment: code + approval link + countdown. Mount only
 * while open; the flow begins exactly once per mount and the single poll
 * chain dies on unmount, terminal state, or retry.
 */
export const OAuthPairingModal: React.FC<OAuthPairingModalProps> = (props) => {
  const { open, providerName, onClose, onRevokePairing } = props
  const flow = usePairingFlow(props)

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      maxWidth="sm"
      title={`Connect ${providerName}`}
      subtitle="Approve in your browser to share your Parallel balance."
    >
      <div data-testid="oauth-device-dialog">
        {flow.phase === "starting" && (
          <p data-testid="oauth-device-loading" className="text-[13px] text-[var(--muted)]">
            Starting secure approval…
          </p>
        )}
        {flow.phase === "pending" && flow.device && (
          <PairingPendingView
            userCode={flow.device.user_code}
            approvalUrl={flow.approvalUrl}
            totalSec={flow.device.expires_in}
            remainingSec={flow.remainingSec}
            copied={flow.copied}
            onCopy={flow.copyCode}
          />
        )}
        {flow.phase === "ready" && (
          <p data-testid="oauth-device-loading" className="text-[13px] text-[var(--muted)]">
            Connected. Refreshing usage…
          </p>
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
          <p
            role="alert"
            data-testid="oauth-device-error"
            className="p-2.5 rounded border border-[var(--status-danger)]/40 bg-[var(--surface)] text-[13px]"
            style={{ color: "var(--status-danger)" }}
          >
            {flow.error}
          </p>
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

const PairingDialogFooter: React.FC<{
  phase: PairingPhase
  revokedElsewhere: boolean
  onClose: () => void
  onRetry: () => void
}> = ({ phase, revokedElsewhere, onClose, onRetry }) => {
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

const PairingPendingView: React.FC<{
  userCode: string
  approvalUrl: string | null
  totalSec: number
  remainingSec: number
  copied: boolean
  onCopy: () => void
}> = ({ userCode, approvalUrl, totalSec, remainingSec, copied, onCopy }) => (
  <div className="space-y-3">
    <div>
      <p id="oauth-device-code-label" className="text-[12px] text-[var(--muted)] mb-1">
        Enter this code in your browser
      </p>
      <div className="flex items-center gap-2">
        <p
          data-testid="oauth-device-user-code"
          aria-labelledby="oauth-device-code-label"
          className="flex-1 rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-2 text-center text-[20px] font-semibold tracking-[0.2em] text-[var(--text-strong)] tnum select-all"
        >
          {userCode}
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="oauth-device-copy"
          onClick={onCopy}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
    <div className="flex items-center gap-2">
      {approvalUrl && (
        <a
          data-testid="oauth-device-open-verification"
          href={approvalUrl}
          target="_blank"
          rel="noreferrer"
          className={cn(buttonVariants({ variant: "default", size: "sm" }))}
        >
          Open Parallel approval
        </a>
      )}
      <span
        role="progressbar"
        aria-label="Time left to approve"
        aria-valuemin={0}
        aria-valuemax={Math.max(1, totalSec)}
        aria-valuenow={remainingSec}
        data-testid="oauth-device-countdown"
        className="text-[12px] text-[var(--muted)] tnum"
      >
        Expires in {formatCountdown(remainingSec)}
      </span>
    </div>
    <p className="text-[12px] text-[var(--muted)]">
      Waiting for approval. This closes on its own once you approve.
    </p>
  </div>
)

const PairingFailedView: React.FC<{ kind: "denied" | "expired" }> = ({ kind }) => {
  const denied = kind === "denied"
  return (
    <div className="space-y-2" data-testid={`oauth-device-${kind}`}>
      <p className="text-[13px] font-medium text-[var(--text-strong)]">
        {denied ? "Request denied." : "This code expired."}
      </p>
      <p
        role="alert"
        data-testid="oauth-device-error"
        className="text-[13px]"
        style={{ color: "var(--status-danger)" }}
      >
        {denied
          ? "The approval was denied in the browser. Get a new code to try again."
          : "This code expired before approval. Get a new code to try again."}
      </p>
    </div>
  )
}

const PairedElsewhereView: React.FC<{
  revoked: boolean
  pending: boolean
  error: string | null
  canUnpair: boolean
  onUnpair: () => void
}> = ({ revoked, pending, error, canUnpair, onUnpair }) => (
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
