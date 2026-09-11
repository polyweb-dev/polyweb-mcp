import { useCallback, useEffect, useState } from "react"
import { toBackendId } from "@/services/api/mappers"
import { apiService } from "@/services/api/freesearchApi"
import { ApiError } from "@/shared/api/http"
import type { BackendOAuthStatus } from "@/services/api/backendTypes"

export function oauthErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail || fallback
  if (error instanceof Error && error.message) return error.message
  return fallback
}

/**
 * Pairing status for one provider row. A missing pairing (backend 404) maps
 * to `unpaired` inside the API client; any other failure keeps the previous
 * status so the row falls back to its unpaired affordances honestly.
 */
export function useOAuthStatus(
  providerId: string,
  enabled: boolean
): { status: BackendOAuthStatus | null; reload: () => void } {
  const [status, setStatus] = useState<BackendOAuthStatus | null>(null)
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    const run = async (): Promise<void> => {
      try {
        const next = await apiService.getOAuthStatus(toBackendId(providerId))
        if (!cancelled) setStatus(next)
      } catch {
        // Honest unknown on failure: keep the previous status.
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [providerId, enabled, generation])

  const reload = useCallback(() => {
    setGeneration((current) => current + 1)
  }, [])

  return { status, reload }
}
