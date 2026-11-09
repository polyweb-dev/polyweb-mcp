import { describe, expect, it } from "vitest"
import { canEditControls, canReadControls } from "./permissions"
import {
  SETTINGS_READER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
  systemAccessFixture,
} from "@/test/accessFixtures"

describe("control-plane capabilities", () => {
  it("grants read and edit to the system administrator", () => {
    const access = systemAccessFixture(SYSTEM_ADMIN_PERMISSIONS)
    expect(canReadControls(access)).toBe(true)
    expect(canEditControls(access)).toBe(true)
  })

  it("grants read only with system.settings.read", () => {
    const access = systemAccessFixture(SETTINGS_READER_PERMISSIONS)
    expect(canReadControls(access)).toBe(true)
    expect(canEditControls(access)).toBe(false)
  })

  it("grants nothing without system permissions, to project permissions, or before access loads", () => {
    expect(canReadControls(systemAccessFixture([]))).toBe(false)
    expect(canReadControls(systemAccessFixture(["settings.read", "settings.write"]))).toBe(false)
    expect(canEditControls(systemAccessFixture(["settings.write"]))).toBe(false)
    expect(canReadControls(null)).toBe(false)
    expect(canEditControls(undefined)).toBe(false)
  })
})
