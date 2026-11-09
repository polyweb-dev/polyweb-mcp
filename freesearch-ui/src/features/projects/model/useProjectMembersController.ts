import { useCallback, useState } from "react"
import { ApiError } from "@/shared/api/http"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import {
  addProjectMember,
  clearProjectDraft,
  isProjectRoleKey,
  listProjectMembers,
  projectMutationMessage,
  projectStorageKey,
  readProjectDraft,
  removeProjectMember,
  setProjectMemberStatus,
  updateProjectMember,
  writeProjectDraft,
} from "@/domains/projects"
import type {
  MembershipStatus,
  ProjectMember,
  ProjectRoleKey,
} from "@/domains/projects"

/** Persisted add-member draft of one project. */
export interface MemberDraft {
  email: string
  role: ProjectRoleKey
}

const EMPTY_DRAFT: MemberDraft = { email: "", role: "project_member" }
const DRAFT_SCHEMA_VERSION = 1

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

/** Read the stored member draft, or the empty draft for any invalid value. */
function readMemberDraft(key: string): MemberDraft {
  const value = readProjectDraft(key, DRAFT_SCHEMA_VERSION)
  if (!isRecord(value) || typeof value.email !== "string") return { ...EMPTY_DRAFT }
  return {
    email: value.email,
    role: isProjectRoleKey(value.role) && (value.role === "project_admin" || value.role === "project_member") ? value.role : EMPTY_DRAFT.role,
  }
}

export interface UseProjectMembersControllerOptions {
  accountId: string
  projectId: string
  refreshAccess: () => void
}

export interface ProjectMembersController {
  members: ScopedResource<ProjectMember[]>
  draft: MemberDraft
  updateDraft: (next: MemberDraft) => void
  add: () => Promise<void>
  setStatus: (member: ProjectMember, status: MembershipStatus) => Promise<void>
  remove: (member: ProjectMember) => Promise<void>
  assign: (member: ProjectMember, role: ProjectRoleKey) => Promise<void>
  unassign: (member: ProjectMember, role: ProjectRoleKey) => Promise<void>
  pending: boolean
  message: string | null
  confirmingUserId: string | null
  requestRemove: (userId: string | null) => void
}

/**
 * Server copy that belongs under the add-form email field rather than in the
 * page alert above the table — unknown-account and invalid-email refusals.
 */
export function isEmailFieldMessage(message: string): boolean {
  return /email/i.test(message)
}

/**
 * Membership controller of one project.
 *
 * Every mutation reloads the member list and refreshes the caller's access:
 * a change can alter the caller's own roles, so the access descriptor is never
 * trusted to stay the same. A lost permission maps to the shared 403 copy and
 * triggers the same refresh. The add-member draft persists under the
 * project-scoped key and clears on a successful add.
 */
export function useProjectMembersController(
  options: UseProjectMembersControllerOptions
): ProjectMembersController {
  const { accountId, projectId, refreshAccess } = options
  const draftKey = projectStorageKey("member-draft", {
    accountId,
    projectId,
    schemaVersion: DRAFT_SCHEMA_VERSION,
  })
  const members = useScopedResource<ProjectMember[]>({
    scopeKey: `${accountId}:${projectId}:members`,
    load: (signal) => listProjectMembers(projectId, signal),
  })
  const reloadMembers = members.reload
  const [draft, setDraft] = useState<MemberDraft>(() => readMemberDraft(draftKey))
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [confirmingUserId, setConfirmingUserId] = useState<string | null>(null)

  const updateDraft = useCallback(
    (next: MemberDraft) => {
      setDraft(next)
      writeProjectDraft(draftKey, DRAFT_SCHEMA_VERSION, next)
    },
    [draftKey]
  )

  const mutate = useCallback(
    async (
      action: () => Promise<unknown>,
      fallback = "The change could not be saved.",
      emailLookup = false
    ) => {
      setPending(true)
      setMessage(null)
      try {
        await action()
        reloadMembers()
        refreshAccess()
      } catch (error) {
        setMessage(error instanceof ApiError && error.status === 404 && !emailLookup
          ? "This action is not available yet."
          : projectMutationMessage(error, fallback, { emailLookup }))
        if (error instanceof ApiError && error.status === 403) refreshAccess()
      } finally {
        setPending(false)
      }
    },
    [reloadMembers, refreshAccess]
  )

  const add = useCallback(async () => {
    const email = draft.email.trim()
    if (!email) {
      setMessage("Enter the email address of the account to add")
      return
    }
    await mutate(async () => {
      await addProjectMember(projectId, { email, initial_role: draft.role })
      setDraft({ ...EMPTY_DRAFT })
      clearProjectDraft(draftKey)
    }, "The member could not be added.", true)
  }, [draft, projectId, draftKey, mutate])

  const setStatus = useCallback(
    (member: ProjectMember, status: MembershipStatus) =>
      mutate(() => setProjectMemberStatus(projectId, member.user_id, status)),
    [mutate, projectId]
  )

  const remove = useCallback(
    async (member: ProjectMember) => {
      setConfirmingUserId(null)
      await mutate(() => removeProjectMember(projectId, member.user_id))
    },
    [mutate, projectId]
  )

  const assign = useCallback(
    (member: ProjectMember, role: ProjectRoleKey) =>
      mutate(() => updateProjectMember(projectId, member.user_id, { role: role === "project_admin" ? "admin" : "developer" })),
    [mutate, projectId]
  )

  const unassign = useCallback(
    (member: ProjectMember, _role: ProjectRoleKey) =>
      mutate(() => updateProjectMember(projectId, member.user_id, { role: "developer" })),
    [mutate, projectId]
  )

  return {
    members,
    draft,
    updateDraft,
    add,
    setStatus,
    remove,
    assign,
    unassign,
    pending,
    message,
    confirmingUserId,
    requestRemove: setConfirmingUserId,
  }
}
