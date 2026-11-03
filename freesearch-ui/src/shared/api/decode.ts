/**
 * Generic decoding helpers for payloads read as `unknown`.
 *
 * Decoders build their output from these readers field by field, so a field
 * the client did not name never reaches a view model.
 */

export type JsonRecord = Record<string, unknown>

/** Return the value as a plain object, or `null`. */
export function asRecord(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : null
}

/** Return a string field, or `null` when absent or not a string. */
export function readString(record: JsonRecord, key: string): string | null {
  const value = record[key]
  return typeof value === "string" ? value : null
}

/** Return an integer field, or `null`. */
export function readInt(record: JsonRecord, key: string): number | null {
  const value = record[key]
  return typeof value === "number" && Number.isInteger(value) ? value : null
}

/** Return whether a field is exactly `true`. */
export function readFlag(record: JsonRecord, key: string): boolean {
  return record[key] === true
}

/** Return the members of a field drawn from one closed set, in set order. */
export function readMembers<T extends string>(
  record: JsonRecord,
  key: string,
  allowed: readonly T[]
): T[] {
  const value = record[key]
  if (!Array.isArray(value)) return []
  return allowed.filter((member) => value.includes(member))
}

/** Return a field when it is one member of a closed set, else `null`. */
export function readEnum<T extends string>(
  record: JsonRecord,
  key: string,
  allowed: readonly T[]
): T | null {
  const value = record[key]
  return allowed.find((member) => member === value) ?? null
}

/** Decode a list payload; rows that do not decode are dropped. */
export function decodeList<T>(
  payload: unknown,
  decode: (value: unknown) => T | null,
  what: string
): T[] {
  if (!Array.isArray(payload)) throw new Error(`${what} is not a list`)
  const rows: T[] = []
  for (const value of payload) {
    const row = decode(value)
    if (row !== null) rows.push(row)
  }
  return rows
}

/** Decode one object payload or throw. */
export function decodeOne<T>(
  payload: unknown,
  decode: (value: unknown) => T | null,
  what: string
): T {
  const row = decode(payload)
  if (row === null) throw new Error(`${what} could not be read`)
  return row
}
