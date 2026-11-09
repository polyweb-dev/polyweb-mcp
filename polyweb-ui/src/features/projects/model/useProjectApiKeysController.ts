import { useCallback, useMemo, useState } from "react"
import { ApiError } from "@/shared/api/http"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import {
  apiKeyMutationMessage,
  issueProjectApiKey,
  listProjectApiKeys,
  listProjectMembers,
  revokeProjectApiKey,
  rotateProjectApiKey,
} from "@/domains/projects"
import type {
  IssueApiKeyInput,
  IssuedApiKey,
  ProjectApiKey,
  RotateApiKeyInput,
} from "@/domains/projects"

export interface UseProjectApiKeysControllerOptions {
  accountId: string
  projectId: string
  refreshAccess: () => void
  /** Load the member list for creator emails only with `members.read`. */
  canReadMembers: boolean
}

export interface ProjectApiKeysController {
  keys: ScopedResource<ProjectApiKey[]>
  /** Creator emails by user id, or `null` when members are not readable. */
  emailsByUserId: ReadonlyMap<string, string> | null
  pending: boolean
  message: string | null
  showMessage: (message: string | null) => void
  /** Raw key of the last issue or rotation, until the reveal closes. */
  revealedKey: string | null
  dismissReveal: () => void
  issue: (input: IssueApiKeyInput) => Promise<boolean>
  rotate: (key: ProjectApiKey, input: RotateApiKeyInput) => Promise<boolean>
  revoke: (key: ProjectApiKey) => Promise<void>
  confirmingRevokeId: string | null
  requestRevoke: (keyId: string | null) => void
  rotatingKey: ProjectApiKey | null
  openRotate: (key: ProjectApiKey | null) => void
}

interface Revealed {
  scopeKey: string
  rawKey: string
}

/**
 * API key controller of one project.
 *
 * The raw key of an issue or a rotation lives only in this hook's local
 * state, tagged with its `accountId:projectId` scope: it is never written to
 * a store, a draft, a URL or a log, it clears when the reveal closes, it dies
 * with the page on unmount, and a scope change clears it (the getter also
 * hides a key of another scope, so it never renders for one frame). Every
 * mutation reloads the list; a lost permission (403) refreshes the access.
 */
export function useProjectApiKeysController(
  options: UseProjectApiKeysControllerOptions
): ProjectApiKeysController {
  const { accountId, projectId, refreshAccess, canReadMembers } = options
  const scopeKey = `${accountId}:${projectId}`
  const keys = useScopedResource<ProjectApiKey[]>({
    scopeKey: `${scopeKey}:api-keys`,
    load: (signal) => listProjectApiKeys(projectId, signal),
  })
  const members = useScopedResource({
    scopeKey: `${scopeKey}:members`,
    load: (signal) => listProjectMembers(projectId, signal),
    enabled: canReadMembers,
  })
  const reloadKeys = keys.reload
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [revealed, setRevealed] = useState<Revealed | null>(null)
  const [confirmingRevokeId, setConfirmingRevokeId] = useState<string | null>(null)
  const [rotatingKey, setRotatingKey] = useState<ProjectApiKey | null>(null)
  const [stateScope, setStateScope] = useState(scopeKey)

  // A scope change clears the raw key and every per-scope interaction during
  // render (no effect), so returning to the earlier scope cannot bring it back.
  if (stateScope !== scopeKey) {
    setStateScope(scopeKey)
    setRevealed(null)
    setRotatingKey(null)
    setConfirmingRevokeId(null)
    setMessage(null)
  }

  const emailsByUserId = useMemo(() => {
    if (members.status !== "ready") return null
    return new Map(members.data.map((member) => [member.user_id, member.email]))
  }, [members])

  const run = useCallback(
    async (action: () => Promise<IssuedApiKey | void>, fallback: string): Promise<boolean> => {
      setPending(true)
      setMessage(null)
      try {
        const result = await action()
        if (result) setRevealed({ scopeKey, rawKey: result.rawKey })
        void reloadKeys()
        return true
      } catch (error) {
        setMessage(apiKeyMutationMessage(error, fallback))
        if (error instanceof ApiError && error.status === 403) refreshAccess()
        return false
      } finally {
        setPending(false)
      }
    },
    [scopeKey, reloadKeys, refreshAccess]
  )

  const issue = useCallback(
    (input: IssueApiKeyInput) =>
      run(() => issueProjectApiKey(projectId, input), "The key could not be issued."),
    [run, projectId]
  )

  const rotate = useCallback(
    async (key: ProjectApiKey, input: RotateApiKeyInput) => {
      const done = await run(
        () => rotateProjectApiKey(projectId, key.id, input),
        "The key could not be rotated."
      )
      if (done) setRotatingKey(null)
      return done
    },
    [run, projectId]
  )

  const revoke = useCallback(
    async (key: ProjectApiKey) => {
      setConfirmingRevokeId(null)
      await run(() => revokeProjectApiKey(projectId, key.id), "The key could not be revoked.")
    },
    [run, projectId]
  )

  const dismissReveal = useCallback(() => setRevealed(null), [])

  const openRotate = useCallback((key: ProjectApiKey | null) => {
    setMessage(null)
    setRotatingKey(key)
  }, [])

  return {
    keys,
    emailsByUserId,
    pending,
    message,
    showMessage: setMessage,
    revealedKey: revealed !== null && revealed.scopeKey === scopeKey ? revealed.rawKey : null,
    dismissReveal,
    issue,
    rotate,
    revoke,
    confirmingRevokeId,
    requestRevoke: setConfirmingRevokeId,
    rotatingKey,
    openRotate,
  }
}
