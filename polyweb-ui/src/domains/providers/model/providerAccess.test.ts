import { describe, expect, it } from "vitest"
import {
  ALL_BITS,
  FETCH_BIT,
  GLOBAL_BIT,
  SEARCH_BIT,
  decodeProviderAccess,
  isProviderOperationEnabled,
} from "./providerAccess"

describe("providerAccess mask contract", () => {
  it("exposes the canonical bit constants", () => {
    expect(GLOBAL_BIT).toBe(1)
    expect(SEARCH_BIT).toBe(2)
    expect(FETCH_BIT).toBe(4)
    expect(ALL_BITS).toBe(7)
  })

  it("decodes raw admin choices without consulting support", () => {
    // Brave canonical: admin wants everything (7) but the system only
    // supports search (3). Raw choices stay ON for fetch.
    expect(decodeProviderAccess(7, 3)).toEqual({
      enableMask: 7,
      supportMask: 3,
      globalEnabled: true,
      searchEnabled: true,
      fetchEnabled: true,
    })
    expect(decodeProviderAccess(3, 3)).toMatchObject({
      globalEnabled: true,
      searchEnabled: true,
      fetchEnabled: false,
    })
    expect(decodeProviderAccess(7, 7)).toMatchObject({
      globalEnabled: true,
      searchEnabled: true,
      fetchEnabled: true,
    })
  })

  it("preserves tool choices while global access stays OFF", () => {
    // Global OFF (bit 0 clear) keeps both tool bits: 6 = search + fetch.
    const view = decodeProviderAccess(6, 7)
    expect(view.globalEnabled).toBe(false)
    expect(view.searchEnabled).toBe(true)
    expect(view.fetchEnabled).toBe(true)
    expect(view.enableMask).toBe(6)
  })

  it("decodes every all-OFF mask without a default-ON fallback", () => {
    expect(decodeProviderAccess(0, 0)).toEqual({
      enableMask: 0,
      supportMask: 0,
      globalEnabled: false,
      searchEnabled: false,
      fetchEnabled: false,
    })
    expect(decodeProviderAccess(0, 7)).toMatchObject({
      globalEnabled: false,
      searchEnabled: false,
      fetchEnabled: false,
    })
  })

  it("rejects malformed masks instead of defaulting ON", () => {
    for (const bad of [true, false, 1.5, "7", null, undefined, Number.NaN, -1, 8, 9, 255]) {
      expect(() => decodeProviderAccess(bad, 7)).toThrow()
      expect(() => decodeProviderAccess(7, bad)).toThrow()
    }
  })

  it("grants effective access only through enable AND support with the global gate", () => {
    // Fully supported provider: both tools pass.
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 7 }, "search")).toBe(true)
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 7 }, "fetch")).toBe(true)
    // Brave canonical: search passes, fetch fails on support.
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 3 }, "search")).toBe(true)
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 3 }, "fetch")).toBe(false)
    // Tool OFF affects only that tool.
    expect(isProviderOperationEnabled({ enableMask: 5, supportMask: 7 }, "search")).toBe(false)
    expect(isProviderOperationEnabled({ enableMask: 5, supportMask: 7 }, "fetch")).toBe(true)
    expect(isProviderOperationEnabled({ enableMask: 3, supportMask: 7 }, "search")).toBe(true)
    expect(isProviderOperationEnabled({ enableMask: 3, supportMask: 7 }, "fetch")).toBe(false)
  })

  it("blocks both tools while global access stays OFF even with tool bits ON", () => {
    expect(isProviderOperationEnabled({ enableMask: 6, supportMask: 7 }, "search")).toBe(false)
    expect(isProviderOperationEnabled({ enableMask: 6, supportMask: 7 }, "fetch")).toBe(false)
    expect(isProviderOperationEnabled({ enableMask: 0, supportMask: 7 }, "search")).toBe(false)
    expect(isProviderOperationEnabled({ enableMask: 0, supportMask: 7 }, "fetch")).toBe(false)
  })

  it("blocks tools whose system support bit stays OFF even with admin ON", () => {
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 5 }, "search")).toBe(false)
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 5 }, "fetch")).toBe(true)
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 6 }, "search")).toBe(false)
    expect(isProviderOperationEnabled({ enableMask: 7, supportMask: 6 }, "fetch")).toBe(false)
  })

  it("returns false for operations outside search and fetch", () => {
    expect(
      isProviderOperationEnabled(
        { enableMask: 7, supportMask: 7 },
        "extract" as "search",
      ),
    ).toBe(false)
  })
})
