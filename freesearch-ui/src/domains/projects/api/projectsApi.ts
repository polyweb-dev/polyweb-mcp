/**
 * Projects domain API: the project routes of the backend.
 *
 * Every call goes through the shared transport, so the Authorization header,
 * the abort signal, and the error normalization stay in one place. Every
 * payload is decoded from `unknown` before the UI uses it. An aborted request
 * surfaces as `ApiError(0)` through the shared transport; callers that scope a
 * load decide staleness from their own signal or generation, not the status.
 */
import { requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"
import type {
  MembershipStatus,
  Project,
  ProjectAccess,
  ProjectMember,
  ProjectRoleKey,
  SystemAccess,
} from "../model/types"
import {
  decodeProject,
  decodeProjectAccess,
  decodeProjectList,
  decodeProjectMember,
  decodeProjectMemberList,
  decodeSystemAccess,
} from "./wire"

const BASE = "/api/v1"

/** Conflict code of the last-administrator guard. */
export const LAST_PROJECT_ADMIN_CODE = "LAST_PROJECT_ADMIN"

/** User-facing copy for the mapped project failures. */
export const LAST_PROJECT_ADMIN_MESSAGE =
  "A project must keep at least one active administrator."
export const UNKNOWN_ACCOUNT_EMAIL_MESSAGE = "No active account uses that email address."
export const PERMISSION_LOST_MESSAGE = "You no longer have permission for this action."
export const PROJECT_UNAVAILABLE_MESSAGE =
  "You do not have access to this project, or it does not exist."

/** Return whether the failure is the backend last-administrator conflict. */
export function isLastProjectAdminError(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 409) return false
  const body = error.raw
  if (typeof body !== "object" || body === null) return false
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail !== "object" || detail === null) return false
  return (detail as { code?: unknown }).code === LAST_PROJECT_ADMIN_CODE
}

/** Return whether the failure is an inaccessible-or-unknown project read. */
export function isProjectUnavailableError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/**
 * Map a project mutation failure to safe user-facing copy.
 *
 * The mapping is identical for an email and an id path: a 400 means the named
 * account does not exist or is inactive, a 403 means the caller lost the
 * permission, and a last-admin conflict keeps its own message.
 */
export function projectMutationMessage(error: unknown, fallback: string): string {
  if (isLastProjectAdminError(error)) return LAST_PROJECT_ADMIN_MESSAGE
  if (error instanceof ApiError) {
    if (error.status === 403) return PERMISSION_LOST_MESSAGE
    if (error.status === 400) return UNKNOWN_ACCOUNT_EMAIL_MESSAGE
    if (error.detail) return error.detail
  }
  return fallback
}

/** Return the caller's live system-scope access descriptor. */
export async function getSystemAccess(signal: AbortSignal): Promise<SystemAccess> {
  return decodeSystemAccess(await requestJson<unknown>(`${BASE}/system/access`, { signal }))
}

/** Return the projects the caller can currently read, archived included. */
export async function listProjects(signal: AbortSignal): Promise<Project[]> {
  return decodeProjectList(
    await requestJson<unknown>(`${BASE}/projects?include_archived=true`, { signal })
  )
}

/** Create one project naming its first administrator by email. */
export async function createProject(input: {
  name: string
  slug?: string
  initial_admin_email: string
}): Promise<Project> {
  const body: Record<string, unknown> = {
    name: input.name,
    initial_admin_email: input.initial_admin_email,
  }
  if (input.slug !== undefined && input.slug !== "") body.slug = input.slug
  return decodeProject(
    await requestJson<unknown>(`${BASE}/projects`, {
      method: "POST",
      body: JSON.stringify(body),
    })
  )
}

/** Return the caller's live access descriptor for one project. */
export async function getProjectAccess(
  projectId: string,
  signal: AbortSignal
): Promise<ProjectAccess> {
  return decodeProjectAccess(
    await requestJson<unknown>(`${BASE}/projects/${projectId}/access`, { signal })
  )
}

/** Return the members of one project. */
export async function listProjectMembers(
  projectId: string,
  signal: AbortSignal
): Promise<ProjectMember[]> {
  return decodeProjectMemberList(
    await requestJson<unknown>(`${BASE}/projects/${projectId}/members`, { signal })
  )
}

/** Add one existing account to a project by email with an initial role. */
export async function addProjectMember(
  projectId: string,
  input: { email: string; initial_role: ProjectRoleKey }
): Promise<ProjectMember> {
  return decodeProjectMember(
    await requestJson<unknown>(`${BASE}/projects/${projectId}/members`, {
      method: "POST",
      body: JSON.stringify({ email: input.email, initial_role: input.initial_role }),
    })
  )
}

/** Suspend or reactivate one membership. */
export async function setProjectMemberStatus(
  projectId: string,
  userId: string,
  status: MembershipStatus
): Promise<ProjectMember> {
  return decodeProjectMember(
    await requestJson<unknown>(`${BASE}/projects/${projectId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    })
  )
}

/** Remove one membership and its project roles. */
export async function removeProjectMember(projectId: string, userId: string): Promise<void> {
  await requestJson<unknown>(`${BASE}/projects/${projectId}/members/${userId}`, {
    method: "DELETE",
  })
}

/** Assign one extra project-scoped role to a member. */
export async function assignProjectRole(
  projectId: string,
  userId: string,
  roleKey: ProjectRoleKey
): Promise<void> {
  await requestJson<unknown>(
    `${BASE}/projects/${projectId}/members/${userId}/roles/${roleKey}`,
    { method: "PUT" }
  )
}

/** Remove one project role from a member. */
export async function removeProjectRole(
  projectId: string,
  userId: string,
  roleKey: ProjectRoleKey
): Promise<void> {
  await requestJson<unknown>(
    `${BASE}/projects/${projectId}/members/${userId}/roles/${roleKey}`,
    { method: "DELETE" }
  )
}
