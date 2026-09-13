import type {
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/domains/providers/api/oauthWire"

export type PairingPhase = "starting" | "pending" | "ready" | "denied" | "expired" | "failed" | "paired"

export interface FlowCallbacks {
  beginFlow: () => Promise<BackendOAuthDeviceCode>
  checkStatus: () => Promise<BackendOAuthStatus>
  onPaired: () => Promise<unknown>
  onClose: () => void
  statusPollMs?: number
  onRevokePairing?: () => Promise<unknown>
}

/** Terminal vendor verdicts; null while the user can still approve. */
export function terminalPhaseFor(status: BackendOAuthStatus["status"]): PairingPhase | null {
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
  return minutes + ":" + seconds.toString().padStart(2, "0")
}
