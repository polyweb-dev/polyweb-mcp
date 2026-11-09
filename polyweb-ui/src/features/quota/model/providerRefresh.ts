import type { ProviderLimitsSyncResult } from "@/domains/dashboard"

/** A refresh that hangs resolves as a failure, so the button never stays on "Refreshing…". */
const SYNC_TIMEOUT_MS = 20_000

export function withTimeout<T>(promise: Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Refresh timed out")), SYNC_TIMEOUT_MS)
    promise.then(
      (value) => {
        clearTimeout(timer)
        resolve(value)
      },
      (failure: unknown) => {
        clearTimeout(timer)
        reject(failure instanceof Error ? failure : new Error("Refresh failed"))
      },
    )
  })
}

type SyncBody = Partial<ProviderLimitsSyncResult>

/** The note of a refresh that updated the numbers, or joined a running sync. */
const UPDATED_TEXT = "Updated"
/** The note of a refresh that failed for an unknown reason. */
const FAILED_TEXT = "Refresh failed"
/** The one skip reason that means this provider has nothing to refresh. */
export const NO_USAGE_ENDPOINT = "no_usage_endpoint"
/** The skip reason that means no system credential exists to read usage with. */
export const NO_CREDENTIAL = "no_credential"

/** Plain words for every refresh skip reason, so no backend code reaches the card. */
const SKIP_TEXT: Readonly<Record<string, string>> = {
  no_credential: "Add a system key to see usage",
  no_adapter: "Provider unavailable right now",
  no_usage_endpoint: "This provider does not report usage",
  no_native_pool: "No usage data for this provider",
  credential_store_unavailable: "Usage service unavailable, try again",
  no_limit_service: "Usage service unavailable, try again",
  no_repository: "Usage service unavailable, try again",
  cadence: "Refreshed recently, try again in a minute",
  lease_held: "Refresh already in progress",
}

/** Plain words for every refresh error code. */
const ERROR_TEXT: Readonly<Record<string, string>> = {
  adapter_unavailable: "The provider key could not be loaded",
}

export function bodyOf(value: unknown): SyncBody {
  return (typeof value === "object" && value !== null ? value : {}) as SyncBody
}

function textField(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null
}

/** Whether a refresh reply was skipped for one reason. */
export function skippedFor(value: unknown, reason: string): boolean {
  const body = bodyOf(value)
  return body.status === "skipped" && body.reason === reason
}

/** Read the refresh reply defensively and map it to one plain sentence. */
export function syncText(value: unknown): string {
  const body = bodyOf(value)
  const status = textField(body.status) ?? "failed"
  if (status === "synced") return UPDATED_TEXT
  const reason = textField(body.reason)
  if (status === "skipped") return (reason === null ? null : SKIP_TEXT[reason]) ?? FAILED_TEXT
  const code = textField(body.error_code)
  const mapped = code === null ? undefined : ERROR_TEXT[code]
  if (mapped !== undefined) return mapped
  return (reason === null ? null : SKIP_TEXT[reason]) ?? FAILED_TEXT
}

