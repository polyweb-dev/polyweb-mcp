/**
 * Wire decoders of the project API key routes.
 *
 * Every payload arrives as `unknown`. The raw key of an issue or a rotation is
 * split from its metadata here, so no decoded list item can carry it.
 */
import type { ApiKeyStatus, IssuedApiKey, ProjectApiKey } from "../model/apiKeys"
import { invalidProjectResponse } from "./wire"

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null
}

/** Decode an optional timestamp: `null` stays `null`, anything else must be text. */
function asNullableString(value: unknown): string | null | undefined {
  if (value === null || value === undefined) return null
  return asString(value) ?? undefined
}

function asStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  return value.every((item) => typeof item === "string") ? [...value] : null
}

function isApiKeyStatus(value: unknown): value is ApiKeyStatus {
  return value === "active" || value === "expired" || value === "revoked"
}

function requireString(record: Record<string, unknown>, field: string): string {
  const value = asString(record[field])
  if (value === null) throw invalidProjectResponse()
  return value
}

function optionalString(record: Record<string, unknown>, field: string): string | null {
  const value = asNullableString(record[field])
  if (value === undefined) throw invalidProjectResponse()
  return value
}

/** Decode one key metadata projection; a raw `key` field is never copied. */
export function decodeProjectApiKey(value: unknown): ProjectApiKey {
  const record = asRecord(value)
  if (record === null) throw invalidProjectResponse()
  const scopes = asStringList(record.scopes)
  if (scopes === null || !isApiKeyStatus(record.status)) throw invalidProjectResponse()
  return {
    id: requireString(record, "id"),
    project_id: requireString(record, "project_id"),
    label: requireString(record, "label"),
    prefix: requireString(record, "prefix"),
    scopes,
    created_by: requireString(record, "created_by"),
    created_at: requireString(record, "created_at"),
    expires_at: optionalString(record, "expires_at"),
    revoked_at: optionalString(record, "revoked_at"),
    last_used_at: optionalString(record, "last_used_at"),
    rotated_from_id: optionalString(record, "rotated_from_id"),
    status: record.status,
  }
}

/** Decode the list payload of `GET /api/v1/projects/{id}/api-keys`. */
export function decodeProjectApiKeyList(value: unknown): ProjectApiKey[] {
  if (!Array.isArray(value)) throw invalidProjectResponse()
  return value.map((item) => decodeProjectApiKey(item))
}

/** Decode an issue or rotation payload into its metadata and its raw key. */
export function decodeIssuedApiKey(value: unknown): IssuedApiKey {
  const record = asRecord(value)
  if (record === null) throw invalidProjectResponse()
  const rawKey = asString(record.key)
  if (rawKey === null) throw invalidProjectResponse()
  return { apiKey: decodeProjectApiKey(record), rawKey }
}
