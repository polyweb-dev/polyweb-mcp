import { describe, expect, it, vi } from "vitest"
import { canRefreshKey, decodeKeyBalances, listKeyBalances, syncKeyBalance } from "./keyBalances"
import { requestJson } from "@/shared/api/client"

vi.mock("@/shared/api/client", () => ({ requestJson: vi.fn() }))

const wire = {
  key_id: "key/1",
  label: "Work key",
  owner_email: "owner@example.com",
  auth_mode: "api_key",
  oauth_connected: null,
  balance: { remaining: "12.50", native_unit: "usd", observed_at: "2026-01-01T12:00:00Z" },
  secret: "must-not-survive",
}

describe("key balances", () => {
  it("decodes only safe fields and accepts a missing observation", () => {
    const result = decodeKeyBalances([wire, { ...wire, key_id: "2", balance: null }])
    expect(result).toEqual([
      { keyId: "key/1", label: "Work key", ownerEmail: "owner@example.com", authMode: "api_key", oauthConnected: null, balance: { remaining: "12.50", unit: "usd", observedAt: "2026-01-01T12:00:00Z" } },
      { keyId: "2", label: "Work key", ownerEmail: "owner@example.com", authMode: "api_key", oauthConnected: null, balance: null },
    ])
    expect(JSON.stringify(result)).not.toContain("must-not-survive")
  })

  it("keeps native balances from the USD vault response", () => {
    const balance = {
      remaining: "42", native_unit: "CREDIT", observed_at: null,
      tiers: [{ native_unit: "CREDIT", native_remaining: "42", remaining_usd: "0.336" }],
    }
    expect(decodeKeyBalances([{ ...wire, balance }])[0]?.balance).toEqual({
      remaining: "42", unit: "CREDIT", observedAt: null,
    })
  })

  it("rejects malformed responses", () => {
    expect(() => decodeKeyBalances({})).toThrow()
    expect(() => decodeKeyBalances([{ ...wire, owner_email: null }])).toThrow()
    expect(() => decodeKeyBalances([{ ...wire, balance: { ...wire.balance, remaining: {} } }])).toThrow()
    expect(() => decodeKeyBalances([{ ...wire, auth_mode: "oauth", oauth_connected: null }])).toThrow()
    expect(() => decodeKeyBalances([{ ...wire, auth_mode: "api_key", oauth_connected: true }])).toThrow()
    expect(() => decodeKeyBalances([{ ...wire, auth_mode: "unknown" }])).toThrow()
  })

  it.each([true, false])("decodes OAuth connection state %s", (connected) => {
    expect(decodeKeyBalances([{ ...wire, auth_mode: "oauth", oauth_connected: connected }])[0])
      .toMatchObject({ authMode: "oauth", oauthConnected: connected })
  })

  it("permits only an administrator or the key owner", () => {
    const key = decodeKeyBalances([wire])[0]
    if (!key) throw new Error("Missing key")
    expect(canRefreshKey(key, true, null)).toBe(true)
    expect(canRefreshKey(key, false, "OWNER@example.com")).toBe(true)
    expect(canRefreshKey(key, false, "other@example.com")).toBe(false)
    expect(canRefreshKey(key, false, null)).toBe(false)
  })

  it("uses encoded provider and key paths for reads and sync", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce([wire]).mockResolvedValueOnce({ status: "synced" })
    const signal = new AbortController().signal
    await expect(listKeyBalances("youcom", signal)).resolves.toHaveLength(1)
    await syncKeyBalance("youcom", "key/1")
    expect(requestJson).toHaveBeenNthCalledWith(1, "/api/v1/providers/you/limits/keys", { signal })
    expect(requestJson).toHaveBeenNthCalledWith(2, "/api/v1/providers/you/limits/keys/key%2F1/sync", { method: "POST" })
  })
})
