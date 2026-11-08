/**
 * Wire decoders of the projects surface.
 *
 * Every payload arrives as `unknown` and is checked field by field before the
 * UI uses it. A malformed body fails with one stable `ApiError(0)` so a schema
 * drift never reaches the view layer as an untyped surprise.
 */
import { ApiError } from "@/shared/api/http"
import type {
  MembershipStatus,
  Project,
  ProjectAccess,
  ProjectMember,
  ProjectRolloutState,
  ProjectStatus,
  SystemAccess,
} from "../model/types"

const INVALID_RESPONSE = "The server returned an unexpected project response."

export function invalidProjectResponse(): ApiError {
  return new ApiError(0, INVALID_RESPONSE, null)
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null
}

function asStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  const items: string[] = []
  for (const item of value) {
    if (typeof item !== "string") return null
    items.push(item)
  }
  return items
}

function isRolloutState(value: unknown): value is ProjectRolloutState {
  return value === "preview" || value === "strict" || value === "fair"
}

function isProjectStatus(value: unknown): value is ProjectStatus {
  return value === "active" || value === "archived"
}

function isMembershipStatus(value: unknown): value is MembershipStatus {
  return value === "active" || value === "suspended"
}

/** Decode the system-scope access payload of `GET /api/v1/system/access`. */
export function decodeSystemAccess(value: unknown): SystemAccess {
  const record = asRecord(value)
  if (record === null) throw invalidProjectResponse()
  const permissions = asStringList(record.permissions)
  if (!isRolloutState(record.rollout_state) || permissions === null) {
    throw invalidProjectResponse()
  }
  return { rollout_state: record.rollout_state, permissions }
}

/** Decode one project projection. */
export function decodeProject(value: unknown): Project {
  const record = asRecord(value)
  if (record === null) throw invalidProjectResponse()
  const id = asString(record.id)
  const accountId = asString(record.account_id)
  const name = asString(record.name)
  const slug = asString(record.slug)
  const createdBy = asString(record.created_by)
  const createdAt = asString(record.created_at)
  if (
    id === null ||
    accountId === null ||
    name === null ||
    slug === null ||
    createdBy === null ||
    createdAt === null ||
    !isProjectStatus(record.status) ||
    typeof record.version !== "number"
  ) {
    throw invalidProjectResponse()
  }
  return {
    id,
    account_id: accountId,
    name,
    slug,
    status: record.status,
    created_by: createdBy,
    created_at: createdAt,
    version: record.version,
  }
}

/** Decode the project list payload of `GET /api/v1/projects`. */
export function decodeProjectList(value: unknown): Project[] {
  if (!Array.isArray(value)) throw invalidProjectResponse()
  return value.map((item) => decodeProject(item))
}

/** Decode the access payload of `GET /api/v1/projects/{id}/access`. */
export function decodeProjectAccess(value: unknown): ProjectAccess {
  const record = asRecord(value)
  if (record === null) throw invalidProjectResponse()
  const projectId = asString(record.project_id)
  const permissions = asStringList(record.permissions)
  const roles = asStringList(record.roles)
  if (
    projectId === null ||
    permissions === null ||
    roles === null ||
    typeof record.policy_revision !== "number"
  ) {
    throw invalidProjectResponse()
  }
  return {
    project_id: projectId,
    permissions,
    roles,
    policy_revision: record.policy_revision,
  }
}

function validMemberExtension(record: Record<string, unknown>): record is Record<string, unknown> & {
  role: "admin" | "developer"
  permissions: number
  provider_owner: boolean
} {
  return (record.role === "admin" || record.role === "developer") &&
    typeof record.permissions === "number" && Number.isInteger(record.permissions) && record.permissions >= 0 &&
    typeof record.provider_owner === "boolean"
}

/** Decode one member projection. */
export function decodeProjectMember(value: unknown): ProjectMember {
  const record = asRecord(value)
  if (record === null) throw invalidProjectResponse()
  const projectId = asString(record.project_id)
  const userId = asString(record.user_id)
  const email = asString(record.email)
  const roles = asStringList(record.roles)
  if (
    projectId === null ||
    userId === null ||
    email === null ||
    roles === null ||
    !isMembershipStatus(record.status) ||
    typeof record.version !== "number" ||
    !validMemberExtension(record)
  ) {
    throw invalidProjectResponse()
  }
  return {
    project_id: projectId,
    user_id: userId,
    email,
    status: record.status,
    roles,
    version: record.version,
    role: record.role,
    permissions: record.permissions,
    provider_owner: record.provider_owner,
  }
}

/** Decode the member list payload of `GET /api/v1/projects/{id}/members`. */
export function decodeProjectMemberList(value: unknown): ProjectMember[] {
  if (!Array.isArray(value)) throw invalidProjectResponse()
  return value.map((item) => decodeProjectMember(item))
}
