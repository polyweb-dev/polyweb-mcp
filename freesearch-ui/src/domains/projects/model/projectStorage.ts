/**
 * Project-scoped draft persistence.
 *
 * Every key is keyed by `(accountId, projectId, schemaVersion)`, so drafts of
 * one project can never appear under another project or another account. The
 * store is throw-free: malformed JSON, a foreign schema version, an oversized
 * payload, and an unavailable `localStorage` all degrade to "no draft"
 * instead of breaking the screen.
 */

/** Scope identity of one project-scoped draft key. */
export interface ProjectStorageScope {
  accountId: string
  projectId: string
  schemaVersion: number
}

/** Bounded draft size, well below typical per-origin quotas. */
const MAX_PROJECT_DRAFT_BYTES = 64 * 1024

/**
 * Return the storage key of one namespaced project draft.
 *
 * Example: `freesearch:member-draft:v1:<accountId>:<projectId>`.
 */
export function projectStorageKey(namespace: string, scope: ProjectStorageScope): string {
  return `freesearch:${namespace}:v${scope.schemaVersion}:${scope.accountId}:${scope.projectId}`
}

interface DraftEnvelope {
  schemaVersion: number
  value: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function readLocalStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
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

/**
 * Return the stored value of one draft, or `null`.
 *
 * Missing keys, malformed JSON, and envelopes of another schema version all
 * read as absent, so a stale draft of a different shape can never leak into a
 * form.
 */
export function readProjectDraft(key: string, schemaVersion: number): unknown {
  const storage = readLocalStorage()
  if (storage === null) return null
  let raw: string | null
  try {
    raw = storage.getItem(key)
  } catch {
    return null
  }
  if (raw === null) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw) as unknown
  } catch {
    return null
  }
  if (!isRecord(parsed) || parsed.schemaVersion !== schemaVersion) return null
  return parsed.value
}

/**
 * Persist one draft value under its versioned envelope.
 *
 * An oversized or rejected write drops the stored entry instead of keeping a
 * value that cannot round-trip.
 */
export function writeProjectDraft(key: string, schemaVersion: number, value: unknown): void {
  const storage = readLocalStorage()
  if (storage === null) return
  const envelope: DraftEnvelope = { schemaVersion, value }
  let payload: string
  try {
    payload = JSON.stringify(envelope)
  } catch {
    return
  }
  if (new TextEncoder().encode(payload).length > MAX_PROJECT_DRAFT_BYTES) {
    removeQuietly(storage, key)
    console.warn("[freesearch] project draft exceeds the size cap; removed the stored draft.")
    return
  }
  try {
    storage.setItem(key, payload)
  } catch (error) {
    removeQuietly(storage, key)
    const name = error instanceof Error ? error.name : "unknown error"
    console.warn(`[freesearch] project draft was not persisted: localStorage rejected the write (${name}).`)
  }
}

/** Drop one stored draft, tolerating an unavailable storage. */
export function clearProjectDraft(key: string): void {
  removeQuietly(readLocalStorage(), key)
}
