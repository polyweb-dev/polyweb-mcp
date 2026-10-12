/**
 * Provider limit controller for one provider rail.
 *
 * The dashboard snapshot is the single card data source, so this hook keeps no
 * private limit copy. It owns grant saves, vendor sync, reload, and the audit
 * page. Every mutation awaits the dashboard query before it reports success,
 * and the audit page loads only while its modal stays open.
 */

import { useCallback, useEffect, useState } from "react"
import { apiService } from "@/services/api/freesearchApi"
import { toBackendId } from "@/services/api/mappers"
import { ApiError, errorMessage } from "@/shared/api/http"
import { decodeLimitHistory } from "@/domains/dashboard"
import type {
  CRDGrantPayload,
  LimitAuditEvent,
  ProviderLimits,
  ProviderLimitsSyncResult,
} from "@/domains/dashboard"
import { activeAuth } from "./crdCardModel"

const STALE_VERSION_TEXT =
  "The server holds a newer version of this record. Reload the limits and try again."

export interface ProviderLimitsInput {
  providerId: string
  limits: ProviderLimits
  hasKey?: boolean
  refreshDashboard: () => Promise<void>
  historyOpen: boolean
}

export interface ProviderLimitsController {
  reload: () => Promise<void>
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  saveGrant: (payload: CRDGrantPayload) => Promise<boolean>
  syncing: boolean
  syncNote: string | null
  /** The last refresh was skipped, so the card hides its refresh action. */
  refreshSkipped: boolean
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
  skipped: boolean
}

interface HistoryState {
  history: LimitAuditEvent[]
  historyLoading: boolean
  historyError: string | null
  hasMoreHistory: boolean
  loadMoreHistory: () => Promise<void>
}

interface HistoryInput {
  backendId: string
  authMode: string
  reloadKey: number
  snapshotKey: string
  open: boolean
}

type SyncBody = Partial<ProviderLimitsSyncResult>

/** Whether a refresh reply reports a skip; anything else keeps the action. */
function isSkippedSync(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false
  const body = value as SyncBody
  if (body.status !== "skipped") return false
  // A held lease means another sync is already running for this provider, so
  // the card keeps its refresh action instead of hiding it.
  return body.reason !== "lease_held"
}

/** Read the refresh reply defensively; a partial body still yields a safe, informative note. */
function syncText(value: unknown): string {
  const body = (typeof value === "object" && value !== null ? value : {}) as SyncBody
  const status = typeof body.status === "string" ? body.status : "failed"
  // A held lease means another sync is already running for this provider, so
  // the card reports success: the numbers update when that sync lands.
  if (status === "skipped" && body.reason === "lease_held") return "Limits refreshed"
  const note = typeof body.reason === "string" && body.reason ? body.reason : null
  const code = typeof body.error_code === "string" && body.error_code ? body.error_code : null
  const detail = note ?? code
  if (status === "synced") {
    return detail !== null ? "Limits refreshed: " + detail : "Limits refreshed"
  }
  if (status === "skipped") {
    return detail !== null ? "Refresh skipped: " + detail : "Refresh skipped"
  }
  if (detail !== null) return "Refresh failed: " + detail
  return "Refresh failed"
}

interface HistoryPage {
  /** The rail and snapshot this page belongs to; a stale page never shows. */
  key: string
  events: LimitAuditEvent[]
  cursor: string | null
  loading: boolean
  loadingMore: boolean
  error: string | null
}

const EMPTY_PAGE: HistoryPage = {
  key: "",
  events: [],
  cursor: null,
  loading: false,
  loadingMore: false,
  error: null,
}

/**
 * First page and further pages of the audit trail.
 *
 * The page carries the rail and snapshot key it belongs to, so a closed modal,
 * a changed rail, or a newer snapshot hides an older answer during render. The
 * first page therefore loads only while its modal stays open.
 */
function useLimitHistory(input: HistoryInput): HistoryState {
  const { backendId, authMode, reloadKey, snapshotKey, open } = input
  const [page, setPage] = useState<HistoryPage>(EMPTY_PAGE)
  const active = open && authMode !== ""
  const key = active ? authMode + "|" + snapshotKey + "|" + reloadKey : ""
  const current = page.key === key ? page : { ...EMPTY_PAGE, key, loading: active }

  useEffect(() => {
    if (key === "") return
    let cancelled = false
    apiService
      .getLimitHistory({ backendId, authMode })
      .then((body) => {
        if (cancelled) return
        const next = decodeLimitHistory(body)
        setPage({
          key,
          events: next.events,
          cursor: next.next_cursor,
          loading: false,
          loadingMore: false,
          error: null,
        })
      })
      .catch((failure: unknown) => {
        if (cancelled) return
        setPage({
          ...EMPTY_PAGE,
          key,
          error: errorMessage(failure, "Unable to load limit history"),
        })
      })
    return () => {
      cancelled = true
    }
  }, [authMode, backendId, key])

  const loadMoreHistory = useCallback(async (): Promise<void> => {
    const cursor = current.cursor
    if (cursor === null || current.loading || current.loadingMore) return
    setPage((previous) => (previous.key === key ? { ...previous, loadingMore: true } : previous))
    try {
      const next = decodeLimitHistory(
        await apiService.getLimitHistory({ backendId, authMode, cursor })
      )
      setPage((previous) =>
        previous.key === key
          ? {
              ...previous,
              events: [...previous.events, ...next.events],
              cursor: next.next_cursor,
              loadingMore: false,
              error: null,
            }
          : previous
      )
    } catch (failure) {
      setPage((previous) =>
        previous.key === key
          ? { ...previous, loadingMore: false, error: errorMessage(failure, "Unable to load limit history") }
          : previous
      )
    }
  }, [authMode, backendId, current.cursor, current.loading, current.loadingMore, key])

  return {
    history: current.events,
    historyLoading: current.loading || current.loadingMore,
    historyError: current.error,
    hasMoreHistory: current.cursor !== null,
    loadMoreHistory,
  }
}

export function useProviderLimits(input: ProviderLimitsInput): ProviderLimitsController {
  const { providerId, limits, refreshDashboard, historyOpen } = input
  const backendId = toBackendId(providerId)
  const authMode = activeAuth(limits, input.hasKey)?.auth_mode ?? ""
  const snapshotKey = limits.generated_at + "-" + limits.version
  const [reloadKey, setReloadKey] = useState(0)
  const [save, setSave] = useState<SaveState>({
    saving: false,
    saveError: null,
    staleVersion: false,
  })
  const [sync, setSync] = useState<SyncState>({ syncing: false, syncNote: null, skipped: false })

  const reload = useCallback(async (): Promise<void> => {
    await refreshDashboard()
    setReloadKey((previous) => previous + 1)
  }, [refreshDashboard])

  const saveGrant = useCallback(
    async (payload: CRDGrantPayload): Promise<boolean> => {
      setSave({ saving: true, saveError: null, staleVersion: false })
      try {
        await apiService.putCRDGrants(backendId, payload)
        await refreshDashboard()
        setSave({ saving: false, saveError: null, staleVersion: false })
        setReloadKey((previous) => previous + 1)
        return true
      } catch (failure) {
        const stale = failure instanceof ApiError && failure.status === 409
        setSave({
          saving: false,
          staleVersion: stale,
          saveError: stale
            ? STALE_VERSION_TEXT
            : errorMessage(failure, "Unable to save the credit-unit grant"),
        })
        return false
      }
    },
    [backendId, refreshDashboard]
  )

  const syncNow = useCallback(async (): Promise<void> => {
    setSync({ syncing: true, syncNote: null, skipped: false })
    try {
      const result = await apiService.syncProviderLimits(backendId)
      const note = syncText(result)
      await refreshDashboard()
      setSync({ syncing: false, syncNote: note, skipped: isSkippedSync(result) })
      setReloadKey((previous) => previous + 1)
    } catch (failure) {
      setSync({ syncing: false, syncNote: errorMessage(failure, "Unable to refresh provider limits"), skipped: false })
    }
  }, [backendId, refreshDashboard])

  const history = useLimitHistory({ backendId, authMode, reloadKey, snapshotKey, open: historyOpen })

  return {
    reload,
    saving: save.saving,
    saveError: save.saveError,
    staleVersion: save.staleVersion,
    saveGrant,
    syncing: sync.syncing,
    syncNote: sync.syncNote,
    refreshSkipped: sync.skipped,
    syncNow,
    ...history,
  }
}
