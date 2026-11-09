import { describe, expect, it } from "vitest"
import { decodeIssuedApiKey, decodeProjectApiKey, decodeProjectApiKeyList } from "./apiKeysWire"

const WIRE = {
  id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  project_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  label: "CI runner",
  prefix: "fs_live_abcd",
  scopes: ["search.execute"],
  created_by: "11111111-1111-4111-8111-111111111111",
  created_at: "2026-10-02T10:00:00Z",
  expires_at: null,
  revoked_at: null,
  last_used_at: "2026-10-03T10:00:00Z",
  rotated_from_id: null,
  status: "active",
}

/** Opaque stand-in for a one-time key; it is not a real credential. */
const ONE_TIME_VALUE = "fs_live_test-only-opaque-value"

describe("decodeProjectApiKey", () => {
  it("decodes the ProjectApiKeyRead shape with null timestamps", () => {
    expect(decodeProjectApiKey(WIRE)).toEqual(WIRE)
  })

  it("reads absent optional timestamps as null", () => {
    const minimal: Record<string, unknown> = { ...WIRE }
    delete minimal.revoked_at
    delete minimal.last_used_at
    delete minimal.rotated_from_id
    expect(decodeProjectApiKey(minimal)).toMatchObject({
      revoked_at: null,
      last_used_at: null,
      rotated_from_id: null,
    })
  })

  it("never copies a raw key field into the metadata", () => {
    const decoded = decodeProjectApiKey({ ...WIRE, key: ONE_TIME_VALUE })
    expect("key" in decoded).toBe(false)
    expect(JSON.stringify(decoded)).not.toContain(ONE_TIME_VALUE)
  })

  it.each([
    ["an unknown status", { ...WIRE, status: "paused" }],
    ["a missing label", { ...WIRE, label: "" }],
    ["non-string scopes", { ...WIRE, scopes: [1] }],
    ["a numeric expiry", { ...WIRE, expires_at: 5 }],
    ["an array body", [WIRE]],
  ])("rejects %s", (_case, body) => {
    expect(() => decodeProjectApiKey(body)).toThrow("unexpected project response")
  })
})

describe("decodeProjectApiKeyList", () => {
  it("decodes every item and rejects a non-array", () => {
    expect(decodeProjectApiKeyList([WIRE, { ...WIRE, id: "d" }])).toHaveLength(2)
    expect(() => decodeProjectApiKeyList({ items: [] })).toThrow()
  })
})

describe("decodeIssuedApiKey", () => {
  it("splits the raw key from the metadata", () => {
    const issued = decodeIssuedApiKey({ ...WIRE, key: ONE_TIME_VALUE })
    expect(issued.rawKey).toBe(ONE_TIME_VALUE)
    expect(issued.apiKey).toEqual(WIRE)
    expect("key" in issued.apiKey).toBe(false)
  })

  it("rejects an issue response without a key", () => {
    expect(() => decodeIssuedApiKey(WIRE)).toThrow("unexpected project response")
  })
})
