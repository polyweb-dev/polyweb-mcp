import { expect, it } from "vitest"
import contract from "./permissionContract.json"
import { DEVELOPER_BITS, memberPermissionSummary, PERMISSION_COPY, PERMISSION_PRESETS, PROJECT_PERMISSION_BITS } from "./permissionCatalog"

it("pins project permission bits and presets to the backend contract", () => {
  expect(PROJECT_PERMISSION_BITS).toEqual({
    search: 1, fetch: 2, traces: 4, usage: 8, settingsWrite: 16,
    settingsCopy: 32, providersConfigure: 64, tokens: 128, providerOwner: 32768,
  })
  expect(DEVELOPER_BITS).toBe(255)
  expect(PERMISSION_PRESETS).toEqual({ "Read only": 12, Standard: 15, "Full developer": 255 })
})

it("matches the shared permission data contract", () => {
  const bits = Object.fromEntries(contract.permissions.map(({ key, bit }) => [key, bit]))
  expect(Object.fromEntries(Object.entries(PERMISSION_COPY).map(([key, value]) => [key, value.bit]))).toEqual(bits)
  expect(PERMISSION_PRESETS).toEqual(contract.presets)
})

it("counts Base access and every displayed permission without counting the owner bit", () => {
  expect(memberPermissionSummary(PERMISSION_PRESETS.Standard)).toBe("5 of 9 permissions")
  expect(memberPermissionSummary(PERMISSION_PRESETS.Standard | PROJECT_PERMISSION_BITS.providerOwner)).toBe("5 of 9 permissions")
  expect(memberPermissionSummary(0)).toBe("1 of 9 permissions")
  expect(memberPermissionSummary(DEVELOPER_BITS)).toBe("9 of 9 permissions")
})
