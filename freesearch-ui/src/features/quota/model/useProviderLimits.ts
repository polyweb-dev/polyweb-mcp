/**
 * Provider limit controller for one provider rail.
 *
 * The hook owns loading, grant saves, sync, and paged history. Each load is
 * driven by its own effect, so a cancelled effect never writes state after a
 * newer load or after unmount.
 */

import { useCallback, useEffect, useState } from "react"
import { apiService } from "@/services/api/freesearchApi"
import { toBackendId } from "@/services/api/mappers"
import { ApiError, errorMessage } from "@/shared/api/http"
import { decodeLimitHistory, decodeProviderLimits } from "@/domains/dashboard"
import type {
  CRDGrantPayload,
  LimitAuditEvent,
  ProviderLimits,
  ProviderLimitsSyncResult,
} from "@/domains/dashboard"

const STALE_VERSION_TEXT =
  "The server holds a newer version of this record. Reload the limits and try again."

export interface ProviderLimitsController {
  limits: ProviderLimits | null
  loading: boolean
  error: string | null
  reload: () => Promise<void>
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  saveGrant: (payload: CRDGrantPayload) => Promise<void>
  syncing: boolean
  syncNote: string | null
  syncNow: () => Promise<void>
  history: LimitAuditEvent[]
  historyLoading: boolean
  historyError: string | null
  hasMoreHistory: boolean
  loadMoreHistory: () => Promise<void>
}

interface SaveState {
  saving: boolean
  saveError: string | null
  staleVersion: boolean
}

interface SyncState {
  syncing: boolean
  syncNote: string | null
}

interface HistoryState {
  history: LimitAuditEvent[]
  historyLoading: boolean
  historyError: string | null
  hasMoreHistory: boolean
  loadMoreHistory: () => Promise<void>
}

type SyncBody = Partial<ProviderLimitsSyncResult>

/** Read the sync reply defensively; a partial body still yields a safe note. */
function syncText(value: unknown): string {
  const body = (typeof value === "object" && value !== null ? value : {}) as SyncBody
  const status = typeof body.status === "string" ? body.status : "failed"
  const note = typeof body.reason === "string" && body.reason ? body.reason : null
  const code = typeof body.error_code === "string" && body.error_code ? body.error_code : null
  const detail = note ?? code
  if (detail !== null) return "Sync " + status + ": " + detail
  return "Sync " + status
}

/** First page of the audit trail, refreshed when the rail or limits change. */
function useLimitHistory(
  backendId: string,
  authMode: string,
  reloadKey: number,
): HistoryState {
  const [events, setEvents] = useState<LimitAuditEvent[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (authMode === "") return
    let cancelled = false
    apiService
      .getLimitHistory({ backendId, authMode })
      .then((body) => {
        if (cancelled) return
        const page = decodeLimitHistory(body)
        setEvents(page.events)
        setCursor(page.next_cursor)
        setError(null)
        setLoading(false)
      })
      .catch((failure: unknown) => {
        if (cancelled) return
        setError(errorMessage(failure, "Unable to load limit history"))
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [authMode, backendId, reloadKey])

  const loadMoreHistory = useCallback(async (): Promise<void> => {
    if (cursor === null) return
    setLoading(true)
    try {
      const page = decodeLimitHistory(
        await apiService.getLimitHistory({ backendId, authMode, cursor })
      )
      setEvents((previous) => [...previous, ...page.events])
      setCursor(page.next_cursor)
      setError(null)
    } catch (failure) {
      setError(errorMessage(failure, "Unable to load limit history"))
    } finally {
      setLoading(false)
    }
  }, [authMode, backendId, cursor])

  return {
    history: events,
    historyLoading: loading,
    historyError: error,
    hasMoreHistory: cursor !== null,
    loadMoreHistory,
  }
}

export function useProviderLimits(providerId: string): ProviderLimitsController {
  const backendId = toBackendId(providerId)
  const [limits, setLimits] = useState<ProviderLimits | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [authMode, setAuthMode] = useState("")
  const [reloadKey, setReloadKey] = useState(0)
  const [save, setSave] = useState<SaveState>({
    saving: false,
    saveError: null,
    staleVersion: false,
  })
  const [sync, setSync] = useState<SyncState>({ syncing: false, syncNote: null })

  useEffect(() => {
    let cancelled = false
    apiService
      .getProviderLimits(backendId)
      .then((body) => {
        if (cancelled) return
        const next = decodeProviderLimits(body)[0] ?? null
        setLimits(next)
        setAuthMode(next === null ? "keyed" : next.active_auth_mode)
        setError(null)
        setLoading(false)
      })
      .catch((failure: unknown) => {
        if (cancelled) return
        setError(errorMessage(failure, "Unable to load provider limits"))
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [backendId, reloadKey])

  const reload = useCallback(async (): Promise<void> => {
    setLoading(true)
    setReloadKey((previous) => previous + 1)
  }, [])

  const saveGrant = useCallback(
    async (payload: CRDGrantPayload): Promise<void> => {
      setSave({ saving: true, saveError: null, staleVersion: false })
      try {
        const updated = decodeProviderLimits(await apiService.putCRDGrants(backendId, payload))
        setLimits(updated[0] ?? null)
        setAuthMode(payload.auth_mode ?? authMode)
        setSave({ saving: false, saveError: null, staleVersion: false })
        setReloadKey((previous) => previous + 1)
      } catch (failure) {
        const stale = failure instanceof ApiError && failure.status === 409
        setSave({
          saving: false,
          staleVersion: stale,
          saveError: stale
            ? STALE_VERSION_TEXT
            : errorMessage(failure, "Unable to save the credit-unit grant"),
        })
      }
    },
    [authMode, backendId]
  )

  const syncNow = useCallback(async (): Promise<void> => {
    setSync({ syncing: true, syncNote: null })
    try {
      const note = syncText(await apiService.syncProviderLimits(backendId))
      setSync({ syncing: false, syncNote: note })
      setReloadKey((previous) => previous + 1)
    } catch (failure) {
      setSync({ syncing: false, syncNote: errorMessage(failure, "Unable to sync provider limits") })
    }
  }, [backendId])

  const history = useLimitHistory(backendId, authMode, reloadKey)

  return {
    limits,
    loading,
    error,
    reload,
    saving: save.saving,
    saveError: save.saveError,
    staleVersion: save.staleVersion,
    saveGrant,
    syncing: sync.syncing,
    syncNote: sync.syncNote,
    syncNow,
    ...history,
  }
}
