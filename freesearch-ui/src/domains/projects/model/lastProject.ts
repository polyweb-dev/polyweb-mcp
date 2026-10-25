/**
 * Remembered last project per account.
 *
 * The preference is navigation convenience only: a stored id is honored only
 * while it still appears in the validated project list, so a revoked or stale
 * project can never be auto-selected.
 */

const LAST_PROJECT_PREFIX = "freesearch:last-project:v1"

/** Return the storage key of one account's last-project preference. */
export function lastProjectKey(accountId: string): string {
  return `${LAST_PROJECT_PREFIX}:${accountId}`
}

function readLocalStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

/** Return the remembered project id of one account, or `null`. */
export function readLastProject(accountId: string): string | null {
  const storage = readLocalStorage()
  if (storage === null) return null
  try {
    return storage.getItem(lastProjectKey(accountId))
  } catch {
    return null
  }
}

/** Remember one project id for one account, tolerating unavailable storage. */
export function writeLastProject(accountId: string, projectId: string): void {
  const storage = readLocalStorage()
  if (storage === null) return
  try {
    storage.setItem(lastProjectKey(accountId), projectId)
  } catch {
    // A rejected write only loses the navigation preference.
  }
}

/**
 * Return the remembered project id only when it survives validation.
 *
 * `projects` is the already-decoded list the caller can read; an id absent
 * from it (removed membership, unknown project) resolves to `null`.
 */
export function resolveLastProject(
  accountId: string,
  projects: readonly { id: string }[]
): string | null {
  const stored = readLastProject(accountId)
  if (stored === null || stored === "") return null
  return projects.some((project) => project.id === stored) ? stored : null
}
