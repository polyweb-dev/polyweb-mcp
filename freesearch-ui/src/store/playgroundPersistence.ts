import type { PersistConfig } from "redux-persist"
import { clampLimit } from "@/domains/execution"
import type { FetchResponse, SearchResponse } from "@/domains/execution"
import { initialPlaygroundState } from "./playgroundSlice"
import type { ExecutionStatus, PlaygroundMode, PlaygroundState } from "./playgroundSlice"

/** Legacy unowned key. It is discarded, never migrated to an account. */
export const PLAYGROUND_PERSIST_KEY = "freesearch:playground:v1"
export const PLAYGROUND_PERSIST_VERSION = 1

/**
 * Account-scoped storage key. Account B can never rehydrate the drafts, the
 * results, or the dialogs that account A stored, because rehydration reads one
 * key only.
 */
export function playgroundPersistKey(accountId: string): string {
  return `${PLAYGROUND_PERSIST_KEY}:${accountId}`
}

/**
 * Application cap, well below typical per-origin quotas. An oversized snapshot
 * is dropped (not truncated): the current session keeps working from Redux,
 * but that state cannot satisfy reload persistence.
 */
export const MAX_PERSISTED_PLAYGROUND_BYTES = 2 * 1024 * 1024

/** A persisted `loading` cannot represent a live request after a browser reload. */
export const INTERRUPTED_REQUEST_ERROR = "Previous request was interrupted by reload."

/** redux-persist's asynchronous storage contract, as consumed by PersistConfig. */
export interface PlaygroundStorage {
  getItem(key: string): Promise<string | null>
  setItem(key: string, value: string): Promise<void>
  removeItem(key: string): Promise<void>
}

const STORAGE_WARNING = "[freesearch] playground state was not persisted:"

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isSearchResponse(value: unknown): value is SearchResponse {
  return isRecord(value) && typeof value.query === "string" && Array.isArray(value.results)
}

function isFetchResponse(value: unknown): value is FetchResponse {
  return isRecord(value) && isRecord(value.document) && typeof value.document.url === "string"
}

/** Only version-1 payloads are trusted; anything else falls back to defaults. */
function hasSupportedVersion(value: Record<string, unknown>): boolean {
  const persist = value._persist
  return isRecord(persist) && persist.version === PLAYGROUND_PERSIST_VERSION
}

function readString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback
}

function readMode(value: unknown): PlaygroundMode {
  return value === "fetch" ? "fetch" : "search"
}

function readNumber(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback
}

interface RestoredExecution {
  status: ExecutionStatus
  error: string | null
}

/**
 * Rehydration policy for one operation: completed/error states restore as-is, an
 * orphaned `loading` becomes an interrupted failure, and no request is issued.
 */
function restoreExecution(statusValue: unknown, errorValue: unknown): RestoredExecution {
  if (statusValue === "loading") return { status: "failed", error: INTERRUPTED_REQUEST_ERROR }
  if (statusValue === "succeeded" || statusValue === "failed") {
    return { status: statusValue, error: typeof errorValue === "string" ? errorValue : null }
  }
  return { status: "idle", error: null }
}

/**
 * Rebuilds playground state from untrusted storage: recognized fields are kept,
 * everything else falls back to defaults. Unsupported or absent version
 * metadata resets the whole slice instead of trusting hand-edited values.
 */
export function sanitizePersistedPlayground(value: unknown): PlaygroundState {
  if (!isRecord(value) || !hasSupportedVersion(value)) return { ...initialPlaygroundState }
  const search = restoreExecution(value.searchStatus, value.searchError)
  const fetch = restoreExecution(value.fetchStatus, value.fetchError)
  return {
    mode: readMode(value.mode),
    query: readString(value.query, initialPlaygroundState.query),
    fetchUrl: readString(value.fetchUrl, initialPlaygroundState.fetchUrl),
    selectedProviderId: readString(
      value.selectedProviderId,
      initialPlaygroundState.selectedProviderId,
    ),
    resultCount: clampLimit(readNumber(value.resultCount, initialPlaygroundState.resultCount)),
    activeSearch: isSearchResponse(value.activeSearch) ? value.activeSearch : null,
    activeFetch: isFetchResponse(value.activeFetch) ? value.activeFetch : null,
    searchStatus: search.status,
    fetchStatus: fetch.status,
    searchError: search.error,
    fetchError: fetch.error,
  }
}

function readLocalStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    // Accessing localStorage itself can throw (SecurityError on blocked origins).
    return null
  }
}

function removeQuietly(storage: Storage | null, key: string): void {
  try {
    storage?.removeItem(key)
  } catch {
    // Nothing to clean if storage is unavailable; the stale value is unreachable.
  }
}

function describeStorageError(error: unknown): string {
  const name = error instanceof Error ? error.name : "unknown error"
  return `localStorage rejected the write (${name}); removed the stored playground state.`
}

function warnOversized(): void {
  console.warn(
    `${STORAGE_WARNING} snapshot exceeds ${MAX_PERSISTED_PLAYGROUND_BYTES} bytes. ` +
      "Removed the stored playground state; current results stay in memory only.",
  )
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown
  } catch {
    return null
  }
}

/** redux-persist serializes every field's value on its own, then the envelope. */
function decodePersistedFields(envelope: Record<string, unknown>): Record<string, unknown> {
  const fields: Record<string, unknown> = {}
  for (const [field, value] of Object.entries(envelope)) {
    fields[field] = typeof value === "string" ? parseJson(value) : value
  }
  return fields
}

function encodePersistedFields(fields: Record<string, unknown>): string {
  const encoded: Record<string, string> = {}
  for (const [field, value] of Object.entries(fields)) {
    encoded[field] = JSON.stringify(value)
  }
  return JSON.stringify(encoded)
}

/**
 * Returns the stored envelope rebuilt only from sanitized fields. Because the
 * playground reducer is persisted directly, the envelope holds its fields at the
 * top level with each value serialized separately (`createPersistoid` serializes
 * per key, then the staged state) — so both levels are decoded here and
 * re-encoded in exactly the shape `getStoredState` expects.
 */
function readPersistedEnvelope(storage: Storage, key: string): string | null {
  let raw: string | null
  try {
    raw = storage.getItem(key)
  } catch {
    return null
  }
  if (raw === null) return null
  const envelope = parseJson(raw)
  if (!isRecord(envelope)) return null
  return encodePersistedFields({
    ...sanitizePersistedPlayground(decodePersistedFields(envelope)),
    _persist: { version: PLAYGROUND_PERSIST_VERSION, rehydrated: true },
  })
}

/**
 * Bounded, throw-free localStorage adapter for the playground slice: oversized
 * or rejected writes drop the stored entry and warn once per failed write
 * rather than crashing execution or resurrecting a stale result.
 */
export function createPlaygroundStorage(): PlaygroundStorage {
  return {
    async getItem(key: string): Promise<string | null> {
      const storage = readLocalStorage()
      return storage === null ? null : readPersistedEnvelope(storage, key)
    },

    async setItem(key: string, value: string): Promise<void> {
      const storage = readLocalStorage()
      if (storage === null) return
      if (new TextEncoder().encode(value).length > MAX_PERSISTED_PLAYGROUND_BYTES) {
        removeQuietly(storage, key)
        warnOversized()
        return
      }
      try {
        storage.setItem(key, value)
      } catch (error) {
        removeQuietly(storage, key)
        console.warn(`${STORAGE_WARNING} ${describeStorageError(error)}`)
      }
    },

    async removeItem(key: string): Promise<void> {
      removeQuietly(readLocalStorage(), key)
    },
  }
}

/**
 * Discard the legacy unowned snapshot.
 *
 * The old key belongs to no account, so the client drops it instead of
 * assigning those results to whoever signs in first.
 */
export function discardLegacyPlaygroundSnapshot(): void {
  removeQuietly(readLocalStorage(), PLAYGROUND_PERSIST_KEY)
}

/**
 * Persistence policy for one confirmed account: one account key, one version,
 * and bounded writes. The legacy unowned snapshot is discarded here, before any
 * rehydration, so the first mount after this change cannot restore it.
 */
export function createPlaygroundPersistConfig(
  accountId: string
): PersistConfig<PlaygroundState> {
  discardLegacyPlaygroundSnapshot()
  return {
    key: playgroundPersistKey(accountId),
    keyPrefix: "",
    version: PLAYGROUND_PERSIST_VERSION,
    storage: createPlaygroundStorage(),
  }
}
