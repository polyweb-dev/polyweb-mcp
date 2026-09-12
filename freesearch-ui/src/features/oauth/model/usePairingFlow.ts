import { useCallback, useEffect, useRef, useState } from "react"
import type { BackendOAuthDeviceCode } from "@/services/api/backendTypes"
import type { FlowCallbacks, PairingPhase } from "./pairingFlow"
import { useBeginPairing } from "./pairingBegin"
import { oauthErrorMessage } from "./useOAuthPairing"

export interface PairingFlow {
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

/**
 * Device-code pairing lifecycle: begin once per mount, poll until a terminal
 * vendor verdict, and clear the single poll chain on unmount, terminal
 * state, or retry. Kept separate from row status (useOAuthStatus): this hook
 * owns one modal moment, that one owns the long-lived row affordance.
 */
export function usePairingFlow(callbacks: FlowCallbacks): PairingFlow {
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

  useEffect(() => {
    callbacksRef.current = callbacks
  })

  const { begin, generation, clearPollTimer, pollNow } = useBeginPairing({
    callbacksRef,
    setPhase,
    setDevice,
    setError,
    setCopied,
    setRevokedElsewhere,
    setExpiresAt,
    setNowMs,
  })

  // Mount-once flow start: the loading phase is mount state (already the
  // useState initial value), this fires once per mount, reads no render
  // output, and every async continuation is generation-guarded with its
  // timers cleared on unmount — no render cascade is possible.
  useEffect(() => {
    void begin()
    return () => {
      generation.current += 1
      clearPollTimer()
    }
  }, [begin, clearPollTimer, generation])

  // Poll immediately when returning to the tab/window from the provider's approval page
  useEffect(() => {
    if (phase !== "pending") return
    const onWake = () => {
      if (document.visibilityState === "visible") {
        pollNow()
      }
    }
    window.addEventListener("focus", onWake)
    document.addEventListener("visibilitychange", onWake)
    return () => {
      window.removeEventListener("focus", onWake)
      document.removeEventListener("visibilitychange", onWake)
    }
  }, [phase, pollNow])

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
