import { useCallback, useRef } from "react"
import type {
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/domains/providers/api/oauthWire"
import { ApiError } from "@/shared/api/http"
import { terminalPhaseFor, type FlowCallbacks, type PairingPhase } from "./pairingFlow"
import { oauthErrorMessage } from "./useOAuthPairing"

export interface BeginPairingInput {
  callbacksRef: { current: FlowCallbacks }
  setPhase: (phase: PairingPhase) => void
  setDevice: (device: BackendOAuthDeviceCode | null) => void
  setError: (error: string | null) => void
  setCopied: (copied: boolean) => void
  setRevokedElsewhere: (revoked: boolean) => void
  setExpiresAt: (expiresAt: number | null) => void
  setNowMs: (nowMs: number) => void
}

export interface BeginPairingApi {
  begin: () => Promise<void>
  generation: { current: number }
  clearPollTimer: () => void
  pollNow: () => void
}

/**
 * Mount-once begin step of the pairing flow. Owns the generation guard, the
 * deadline clock refs, and the single poll chain; the owner supplies only
 * the latest callbacks (read, never written) and stable state setters. The
 * poll round below assigns pollRoundRef (never during render) so no callback
 * references itself and parent re-renders cannot restart the chain.
 */
export function useBeginPairing(input: BeginPairingInput): BeginPairingApi {
  const {
    callbacksRef,
    setPhase,
    setDevice,
    setError,
    setCopied,
    setRevokedElsewhere,
    setExpiresAt,
    setNowMs,
  } = input
  const generation = useRef(0)
  const expiresAtRef = useRef<number | null>(null)
  const pollRoundRef = useRef<(gen: number, delayMs: number) => Promise<void>>(async () => {})
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearPollTimer = useCallback(() => {
    if (pollTimer.current !== null) {
      clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }, [])

  const alive = useCallback((gen: number): boolean => gen === generation.current, [])

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
    setDevice(code)
    const deadline = Date.now() + code.expires_in * 1000
    setExpiresAt(deadline)
    expiresAtRef.current = deadline
    setNowMs(Date.now())
    setPhase("pending")
    schedulePoll(gen, callbacksRef.current.statusPollMs ?? Math.max(1, code.interval) * 1000)
  }, [callbacksRef, clearPollTimer, schedulePoll, setPhase, setDevice, setError, setCopied, setRevokedElsewhere, setExpiresAt, setNowMs, alive])

  const pollNow = useCallback((): void => {
    clearPollTimer()
    void pollRoundRef.current(generation.current, callbacksRef.current.statusPollMs ?? 5000)
  }, [clearPollTimer, callbacksRef])

  return { begin, generation, clearPollTimer, pollNow }
}
