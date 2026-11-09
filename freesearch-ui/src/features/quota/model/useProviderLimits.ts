import { saveBudget } from "./budgetApi"
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
  UsdGrantPayload,
  LimitAuditEvent,
  ProviderLimits,
} from "@/domains/dashboard"
import { activeAuth } from "./usdCardModel"
import { bodyOf, skippedFor, syncText, withTimeout, NO_USAGE_ENDPOINT, NO_CREDENTIAL } from "./providerRefresh"

const STALE_VERSION_TEXT =
  "The server holds a newer version of this record. Reload the limits and try again."

export interface ProviderLimitsInput {
  providerId: string
  limits: ProviderLimits
  refreshDashboard: () => Promise<void>
  historyOpen: boolean
}

export interface ProviderLimitsController {
  reload: () => Promise<void>
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  saveGrant: (payload: UsdGrantPayload) => Promise<boolean>
  syncing: boolean
  syncNote: string | null
  /** The last refresh said the provider reports no usage, so the card hides its refresh action. */
  refreshSkipped: boolean
  /** The last refresh found no system key to read usage with. */
  needsCredential: boolean
  /** When the last refresh updated the numbers, in epoch milliseconds; null otherwise. */
  updatedAt: number | null
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
  needsCredential: boolean
  /** When the last refresh updated the numbers, in epoch milliseconds. */
  updatedAt: number | null
}

const IDLE_SYNC: SyncState = {
  syncing: false,
  syncNote: null,
  skipped: false,
  needsCredential: false,
  updatedAt: null,
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
  const authMode = activeAuth(limits)?.auth_mode ?? ""
  const snapshotKey = limits.generated_at + "-" + limits.version
  const [reloadKey, setReloadKey] = useState(0)
  const [save, setSave] = useState<SaveState>({
    saving: false,
    saveError: null,
    staleVersion: false,
  })
  const [sync, setSync] = useState<SyncState>(IDLE_SYNC)

  const reload = useCallback(async (): Promise<void> => {
    await refreshDashboard()
    setReloadKey((previous) => previous + 1)
  }, [refreshDashboard])

  const saveGrant = useCallback(
    async (payload: UsdGrantPayload): Promise<boolean> => {
      setSave({ saving: true, saveError: null, staleVersion: false })
      try {
        await saveBudget(backendId, payload)
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
            : errorMessage(failure, "Unable to save the budget"),
        })
        return false
      }
    },
    [backendId, refreshDashboard]
  )

  const syncNow = useCallback(async (): Promise<void> => {
    setSync({ ...IDLE_SYNC, syncing: true })
    try {
      const result = await withTimeout(apiService.syncProviderLimits(backendId))
      const note = syncText(result)
      await withTimeout(refreshDashboard())
      setSync({
        syncing: false,
        syncNote: note,
        skipped: skippedFor(result, NO_USAGE_ENDPOINT),
        needsCredential: skippedFor(result, NO_CREDENTIAL),
        updatedAt: bodyOf(result).status === "synced" ? Date.now() : null,
      })
      setReloadKey((previous) => previous + 1)
    } catch {
      setSync({ ...IDLE_SYNC, syncNote: "Refresh failed" })
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
    needsCredential: sync.needsCredential,
    updatedAt: sync.updatedAt,
    syncNow,
    ...history,
  }
}
