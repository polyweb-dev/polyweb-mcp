import { useEffect, useRef, useState } from "react"
import { pollCredentialOAuth, startCredentialOAuth } from "@/domains/providers"
import type { OAuthDeviceStart, OAuthGrantStatus } from "@/domains/providers"

/** Phase of one credential's device flow, from start to a final status. */
export type OAuthFlowState =
  | { phase: "starting" }
  | { phase: "polling"; device: OAuthDeviceStart; status: OAuthGrantStatus }
  | { phase: "finished"; device: OAuthDeviceStart; status: OAuthGrantStatus }
  | { phase: "expired"; device: OAuthDeviceStart }
  | { phase: "failed"; message: string }

export const OAUTH_START_FAILED = "The connection could not be started."
export const OAUTH_POLL_FAILED = "The connection could not be checked."

interface FlowOptions {
  /** Credential base path (system or project). */
  base: string
  /** Called once when the grant becomes connected. */
  onConnected?: () => void
}

/**
 * Credential-scoped OAuth device flow.
 *
 * Starts the flow on mount, then polls every `interval` seconds as the server
 * says (a pending poll may name a new interval). Polling stops at a final
 * status, at expiry, on failure and on unmount — the dialog unmounts this on
 * close, and a project switch remounts the page. Only the user code, the
 * verification link and the status are kept.
 */
export function useCredentialOAuth({ base, onConnected }: FlowOptions): OAuthFlowState {
  const [state, setState] = useState<OAuthFlowState>({ phase: "starting" })
  const connectedCallback = useRef(onConnected)

  useEffect(() => {
    connectedCallback.current = onConnected
  })

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    let deadline = 0

    const poll = async (device: OAuthDeviceStart) => {
      if (Date.now() >= deadline) {
        setState({ phase: "expired", device })
        return
      }
      try {
        const answer = await pollCredentialOAuth(base, controller.signal)
        if (controller.signal.aborted) return
        if (answer.status === "pending") {
          setState({ phase: "polling", device, status: "pending" })
          schedule(device, answer.intervalSeconds ?? device.intervalSeconds)
          return
        }
        setState({ phase: "finished", device, status: answer.status })
        if (answer.status === "connected") connectedCallback.current?.()
      } catch {
        if (!controller.signal.aborted) setState({ phase: "failed", message: OAUTH_POLL_FAILED })
      }
    }

    const schedule = (device: OAuthDeviceStart, seconds: number) => {
      timer = window.setTimeout(() => void poll(device), seconds * 1000)
    }

    startCredentialOAuth(base, controller.signal).then(
      (device) => {
        if (controller.signal.aborted) return
        deadline = Date.now() + device.expiresInSeconds * 1000
        setState({ phase: "polling", device, status: "pending" })
        schedule(device, device.intervalSeconds)
      },
      () => {
        if (!controller.signal.aborted) setState({ phase: "failed", message: OAUTH_START_FAILED })
      }
    )

    return () => {
      controller.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [base])

  return state
}
