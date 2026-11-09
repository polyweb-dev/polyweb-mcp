import { describe, expect, it } from "vitest"
import type { SettingsField } from "@/domains/settings"
import { controlValue, draftChanges, isInheritPending } from "./settingsDraft"

function field(id: string, overrides: Partial<SettingsField> = {}): SettingsField {
  return {
    id,
    section: id.split(".")[0] ?? "",
    attribute: id.split(".")[1] ?? "",
    effectiveValue: 3,
    provenance: "system_default",
    systemDefault: 3,
    projectOverride: null,
    overrideAllowed: true,
    systemLimit: null,
    constraintApplied: false,
    ...overrides,
  }
}

const ATTEMPTS = field("routing.max_attempts", { projectOverride: 5, effectiveValue: 5, provenance: "project_override" })
const PREFERRED = field("routing.preferred_providers", { effectiveValue: [], systemDefault: [] })
const RETENTION = field("trace.retention_days", { effectiveValue: 30, systemDefault: 30 })
const FIELDS = [ATTEMPTS, PREFERRED, RETENTION]

describe("draftChanges", () => {
  it("sends only changed fields, across sections", () => {
    const draft = { "routing.max_attempts": 5, "routing.preferred_providers": ["tavily"], "trace.retention_days": 10 }
    expect(draftChanges(draft, FIELDS)).toEqual({
      "routing.preferred_providers": ["tavily"],
      "trace.retention_days": 10,
    })
  })

  it("sends null for an inherited override and nothing for inheriting an inherited field", () => {
    expect(draftChanges({ "routing.max_attempts": null }, FIELDS)).toEqual({ "routing.max_attempts": null })
    expect(draftChanges({ "trace.retention_days": null }, FIELDS)).toEqual({})
  })
})

describe("draft display helpers", () => {
  it("shows the draft, the system default on inherit, else the effective value", () => {
    expect(controlValue({}, ATTEMPTS)).toBe(5)
    expect(controlValue({ "routing.max_attempts": 7 }, ATTEMPTS)).toBe(7)
    expect(controlValue({ "routing.max_attempts": null }, ATTEMPTS)).toBe(3)
    expect(isInheritPending({ "routing.max_attempts": null }, ATTEMPTS)).toBe(true)
    expect(isInheritPending({}, ATTEMPTS)).toBe(false)
  })

  it("treats an unchanged list as no change", () => {
    expect(draftChanges({ "routing.preferred_providers": [] }, [field("routing.preferred_providers", { projectOverride: [] })])).toEqual({})
  })

  it("treats an inherited field edited back to its shown value as no change", () => {
    expect(draftChanges({ "trace.retention_days": 30, "routing.preferred_providers": [] }, FIELDS)).toEqual({})
  })
})
